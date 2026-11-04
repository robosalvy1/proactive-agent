"""Shared fixtures for tests/hermes_state."""
import pytest


@pytest.fixture
def worker(tmp_path):
    """A registered compute worker execution on session ``owned``: ``(db, RuntimeSessionStore)``."""
    # Imported here, not at module level: this conftest loads for every hermes_state test file.
    from agent.runtime_session_store import RuntimeSessionStore
    from hermes_state import SessionDB
    from hermes_state_runtime import begin_runtime_epoch, mutate_worker_execution, register_worker_execution

    db = SessionDB(tmp_path / 'state.db')
    db.create_session('owned', 'cli', system_prompt='prefix')
    db.create_session('foreign', 'cli', system_prompt='secret')
    epoch = begin_runtime_epoch(db, instance_id='fixture')
    scope = dict(epoch=epoch, execution_id='worker', session_id='owned', generation=0)
    register_worker_execution(db, **scope, kind='compute', adoption_secret='secret')
    def rpc(method, **params):
        from hermes_state_worker_home import read_worker_home
        if method == 'worker.home.recall':
            return read_worker_home(db, **params)
        return mutate_worker_execution(db, **params)

    store = RuntimeSessionStore(rpc, scope, tmp_path / 'outbox')
    yield db, store
    store.failure = None
    store.journal['pending'] = []
    store.close()
    db.close()


@pytest.fixture
def endpoint():
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []
    state = {'status': 200, 'vectors': {}, 'callback': None, 'response': None}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, dict(self.headers), data))
            if state['callback']:
                state['callback']()
            self.send_response(state['status'])
            self.end_headers()
            result = state['response']
            if result is None:
                result = {'data': [{'index': i, 'embedding': state['vectors'].get(text, [0, 0, 1])}
                                   for i, text in enumerate(data['input'])]}
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1', requests, state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
