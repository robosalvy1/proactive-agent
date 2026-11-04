"""Real agent loop and local mock provider: recall, persisted replay, and restart."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from hermes_state import SessionDB
from hermes_state_home import HomeStore


def test_home_recall_reaches_provider_and_replays_identically_after_restart(tmp_path):
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append(request)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if request.get("stream") else "application/json")
            self.end_headers()
            if request.get("stream"):
                chunk = {"id": "test", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Fixture reply"}, "finish_reason": "stop"}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
            else:
                self.wfile.write(json.dumps({"id": "test", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Fixture reply"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}}).encode())

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from run_agent import AIAgent

    with SessionDB(tmp_path / "state.db") as db:
        home = HomeStore(db).ensure_home()
        db.create_session("travel", "cli")
        db.append_message("travel", "user", "Lisbon trip budget is 1200 euros")
        from agent.home_dreaming import dream_once
        from hermes_state_dreams import DreamStore

        DreamStore(db).configure(enabled=True)

        def reflect(sources):
            row = sources[0]['messages'][0]
            return json.dumps({'notes': [{'kind': 'decision', 'text': 'Lisbon spending allowance: 1200 euros.',
                                         'sources': [{'id': row['id'], 'quote': row['text']}]}]})

        assert '1 source-linked' in dream_once(db, manual=True, model=reflect)

        def make_agent():
            return AIAgent(api_key="fixture-key", base_url=f"http://127.0.0.1:{server.server_port}/v1",
                           provider="openai-compat", model="fixture-model", enabled_toolsets=[],
                           quiet_mode=True, skip_context_files=True, skip_memory=False,
                           skip_background_review=True, save_trajectories=False, platform="cli",
                           session_db=db, session_id=home, max_iterations=2)

        try:
            with patch("agent.model_metadata.get_model_context_length", return_value=100000):
                first = make_agent()
                try:
                    first.run_conversation("What is our Lisbon budget?", conversation_history=[])
                finally:
                    first.close()
                first_request = [req for req in captured if "messages" in req][-1]
                first_user = next(row for row in first_request["messages"] if row["role"] == "user")
                assert "1200 euros" in first_user["content"]
                assert 'Home dream notes' in first_user['content']
                assert 'spending allowance' in first_user['content']
                assert '"source_session_id": "travel"' in first_user["content"]
                history = db.get_messages_as_conversation(home)
                assert history[0]["content"] == "What is our Lisbon budget?"
                assert history[0]["api_content"] == first_user["content"]
                db.append_message("travel", "assistant", "Hotel booking remains open")
                second = make_agent()
                try:
                    second.run_conversation("Give me an overview of progress", conversation_history=history)
                finally:
                    second.close()
                second_request = [req for req in captured if "messages" in req][-1]
                user_rows = [row for row in second_request["messages"] if row["role"] == "user"]
                assert user_rows[0] == first_user
                assert "Hotel booking remains open" in user_rows[-1]["content"]
                assert 'Home dream notes' not in user_rows[-1]['content']
                assert second_request["messages"][0] == first_request["messages"][0]
                assert all("api_content" not in row for row in second_request["messages"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
