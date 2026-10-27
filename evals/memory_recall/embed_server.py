"""Loopback OpenAI-compatible eval server: real local embeddings + a scripted chat model.

Runs in its own disposable venv (``pip install fastembed``), never a Hermes environment:
    python embed_server.py <port> <fastembed-model>   e.g. 18555 BAAI/bge-small-en-v1.5
The scripted chat model replays the dataset's assistant turns so other agents (OpenClaw)
can record the same synthetic history through their real turn loop.
"""
import hashlib
import json
import os
import sqlite3
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
from dataset import SESSIONS

from fastembed import TextEmbedding

PORT, MODEL = int(sys.argv[1]), sys.argv[2]
EMB = TextEmbedding(MODEL, cache_dir=os.environ.get('MEMORY_EVAL_MODEL_CACHE'))
LOCK = threading.Lock()
STATS = {'embed_requests': 0, 'embed_inputs': 0, 'embed_cache_hits': 0, 'chat_requests': 0}
# Optional persistent cache: benchmarks that re-ingest shared sessions embed each text once.
CACHE = sqlite3.connect(os.environ['MEMORY_EVAL_EMBED_CACHE'], check_same_thread=False) \
    if os.environ.get('MEMORY_EVAL_EMBED_CACHE') else None
if CACHE is not None:
    CACHE.execute('CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec BLOB)')


def _embed(inputs):
    if CACHE is None:
        return [v.tolist() for v in EMB.embed(inputs)]
    keys = [hashlib.sha256((MODEL + '\0' + t).encode()).hexdigest() for t in inputs]
    found = {}
    for i in range(0, len(keys), 500):
        part = keys[i:i + 500]
        found.update(CACHE.execute(f"SELECT key, vec FROM emb WHERE key IN ({','.join('?' * len(part))})", part))
    missing = [i for i, k in enumerate(keys) if k not in found]
    STATS['embed_cache_hits'] += len(keys) - len(missing)
    if missing:
        fresh = [v.tolist() for v in EMB.embed([inputs[i] for i in missing])]
        rows = [(keys[i], struct.pack(f'<{len(v)}f', *v)) for i, v in zip(missing, fresh)]
        CACHE.executemany('INSERT OR REPLACE INTO emb VALUES (?, ?)', rows)
        CACHE.commit()
        found.update(rows)
    return [list(struct.unpack(f'<{len(found[k]) // 4}f', found[k])) for k in keys]
REPLIES = {}
for _sid, turns in SESSIONS:
    for (role, text), nxt in zip(turns, turns[1:] + [None]):
        if role == 'user' and nxt and nxt[0] == 'assistant':
            REPLIES[text] = nxt[1]


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(p.get('text', '') for p in content if isinstance(p, dict))
    return ''


def _reply_for(messages):
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            text = _text(msg.get('content'))
            for key, reply in REPLIES.items():
                if key in text:
                    return reply
            return 'Okay.'
    return 'Okay.'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip('/').endswith('/models'):
            return self._json(200, {'object': 'list', 'data': [
                {'id': MODEL, 'object': 'model'}, {'id': 'scripted', 'object': 'model'}]})
        if self.path == '/stats':
            return self._json(200, STATS)
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if self.path.rstrip('/').endswith('/embeddings'):
            inputs = data.get('input')
            inputs = [inputs] if isinstance(inputs, str) else list(inputs)
            with LOCK:
                vecs = _embed(inputs)
                STATS['embed_requests'] += 1
                STATS['embed_inputs'] += len(inputs)
            return self._json(200, {'object': 'list', 'model': MODEL, 'usage': {'prompt_tokens': 0, 'total_tokens': 0},
                                    'data': [{'object': 'embedding', 'index': i, 'embedding': v}
                                             for i, v in enumerate(vecs)]})
        if self.path.rstrip('/').endswith('/chat/completions'):
            STATS['chat_requests'] += 1
            reply = _reply_for(data.get('messages', []))
            created, cid = int(time.time()), f'chatcmpl-{time.time_ns()}'
            usage = {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}
            if not data.get('stream'):
                return self._json(200, {'id': cid, 'object': 'chat.completion', 'created': created, 'model': 'scripted',
                                        'choices': [{'index': 0, 'finish_reason': 'stop',
                                                     'message': {'role': 'assistant', 'content': reply}}],
                                        'usage': usage})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()
            chunks = [{'role': 'assistant', 'content': ''}, {'content': reply}]
            for delta in chunks:
                evt = {'id': cid, 'object': 'chat.completion.chunk', 'created': created, 'model': 'scripted',
                       'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
                self.wfile.write(f'data: {json.dumps(evt)}\n\n'.encode())
            end = {'id': cid, 'object': 'chat.completion.chunk', 'created': created, 'model': 'scripted',
                   'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}], 'usage': usage}
            self.wfile.write(f'data: {json.dumps(end)}\n\ndata: [DONE]\n\n'.encode())
            self.wfile.flush()
            self.close_connection = True
            return
        self._json(404, {'error': 'not found'})

    def log_message(self, *_args):
        pass


ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
