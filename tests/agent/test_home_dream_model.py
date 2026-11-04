"""Real HTTP auxiliary routing, bounded requests, observer hooks, and single-attempt failure."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent.home_dream_model import reflect


@pytest.mark.parametrize('status', [200, 503, 402])
def test_reflection_uses_configured_auxiliary_route_once_with_no_tools(tmp_path, monkeypatch, status):
    from hermes_cli import plugins
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

    seen, events = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            if status != 200:
                self.wfile.write(json.dumps({'error': {'message': 'Can only afford 500 tokens', 'code': status}}).encode())
            else:
                self.wfile.write(json.dumps({'id': 'fixture', 'object': 'chat.completion', 'created': 0,
                    'model': 'fixture-model', 'choices': [{'index': 0, 'message': {'role': 'assistant',
                    'content': '{"notes":[]}'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 20, 'completion_tokens': 8, 'total_tokens': 28}}).encode())

        def log_message(self, *_args):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Exercise actual config loading and provider adapter resolution in an isolated profile.
    from hermes_constants import get_hermes_home
    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.yaml').write_text(
        'auxiliary:\n  transient_retries: 9\n  home_dream:\n    provider: openai\n'
        f'    model: fixture-model\n    base_url: http://127.0.0.1:{server.server_port}/v1\n'
        '    api_key: synthetic-fixture-key\n'
        '    extra_body: {max_tokens: 9000, tools: [{type: function}]}\n', encoding='utf-8')
    manager = PluginManager()
    monkeypatch.setattr(plugins, '_plugin_manager', manager)
    monkeypatch.setattr(plugins, '_plugin_managers_by_home', {})
    observer = PluginContext(PluginManifest(name='dream-observer', source='user'), manager)
    for name in ('pre_auxiliary_call', 'post_auxiliary_call', 'pre_api_request'):
        observer.register_hook(name, lambda _name=name, **kwargs: events.append((_name, kwargs)))
    try:
        if status == 200:
            assert reflect([{'messages': [{'id': 1, 'role': 'user', 'text': 'Prefer rail travel'}]}]) == '{"notes":[]}'
        else:
            with pytest.raises(Exception):
                reflect([])
        assert len(seen) == 1
        assert seen[0]['model'] == 'fixture-model'
        assert not seen[0].get('tools')
        assert seen[0].get('max_completion_tokens', seen[0].get('max_tokens')) == 1200
        assert [name for name, _ in events] == ['pre_auxiliary_call', 'post_auxiliary_call']
        assert all(event['aux_task'] == 'home_dream' for _, event in events)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
