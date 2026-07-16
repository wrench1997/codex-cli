import asyncio
import importlib
import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx


@contextmanager
def mock_openai_upstream():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            requests.append(
                {
                    "path": self.path,
                    "body": body,
                    "authorization": self.headers.get("Authorization"),
                }
            )

            has_tool_result = any(
                "<tool_response>" in str(message.get("content", ""))
                for message in body.get("messages", [])
                if isinstance(message, dict)
            )
            if has_tool_result:
                content = "tool output received"
            else:
                content = (
                    "<tool_call>\n"
                    "<function=read_file>\n"
                    "<parameter=path>\nREADME.md\n</parameter>\n"
                    "</function>\n"
                    "</tool_call>"
                )

            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                midpoint = max(1, len(content) // 2)
                for piece in (content[:midpoint], content[midpoint:]):
                    event = {
                        "id": "upstream-stream",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": piece},
                                "finish_reason": None,
                            }
                        ],
                    }
                    self.wfile.write(
                        f"data: {json.dumps(event)}\n\n".encode("utf-8")
                    )
                self.wfile.write(b"data: [DONE]\n\n")
                return

            response = {
                "id": "upstream-response",
                "object": "chat.completion",
                "created": 1,
                "model": body.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
            raw = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def load_gateway(base_url: str, kind: str = "vllm"):
    os.environ["UPSTREAM_BASE_URL"] = base_url
    os.environ["UPSTREAM_KIND"] = kind
    os.environ["UPSTREAM_API_KEY"] = "test-upstream-key"
    os.environ["MODEL_NAME"] = "Qwen/Test"
    os.environ["GATEWAY_ENABLE_METRICS"] = "false"
    os.environ["GATEWAY_ENABLE_THINKING"] = "false"
    module = importlib.import_module("gateway.app")
    return importlib.reload(module)


def request_app(app, method: str, path: str, **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://gateway.test"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_gateway_normalizes_old_vllm_root_and_forwards_auth():
    with mock_openai_upstream() as (base_url, requests):
        gateway = load_gateway(base_url)
        assert gateway.UPSTREAM_CHAT_URL == f"{base_url}/v1/chat/completions"

        response = request_app(
            gateway.app,
            "POST",
            "/v1/chat/completions",
            json={
                "model": "Qwen/Test",
                "stream": False,
                "messages": [{"role": "user", "content": "read README"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "parameters": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                            },
                        },
                    }
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["finish_reason"] == "tool_calls"
        call = data["choices"][0]["message"]["tool_calls"][0]
        assert call["function"]["name"] == "read_file"
        assert json.loads(call["function"]["arguments"]) == {"path": "README.md"}
        assert requests[0]["path"] == "/v1/chat/completions"
        assert requests[0]["authorization"] == "Bearer test-upstream-key"


def test_responses_old_tool_roundtrip_uses_prompt_tool_result():
    with mock_openai_upstream() as (base_url, requests):
        gateway = load_gateway(base_url)
        first = request_app(
            gateway.app,
            "POST",
            "/v1/responses",
            json={
                "model": "Qwen/Test",
                "stream": False,
                "input": [
                    {"type": "message", "role": "user", "content": "read README"}
                ],
                "tools": [
                    {
                        "type": "function",
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    }
                ],
            },
        )
        assert first.status_code == 200
        function_call = first.json()["output"][0]
        assert function_call["type"] == "function_call"

        second = request_app(
            gateway.app,
            "POST",
            "/v1/responses",
            json={
                "model": "Qwen/Test",
                "stream": False,
                "input": [
                    {"type": "message", "role": "user", "content": "read README"},
                    function_call,
                    {
                        "type": "function_call_output",
                        "call_id": function_call["call_id"],
                        "output": "README contents",
                    },
                ],
            },
        )
        assert second.status_code == 200
        assert second.json()["output"][0]["content"][0]["text"] == "tool output received"
        sent_messages = requests[-1]["body"]["messages"]
        assert any(
            message.get("role") == "user"
            and "<tool_response>" in message.get("content", "")
            for message in sent_messages
        )
        assert not any(message.get("role") == "tool" for message in sent_messages)


def test_chat_stream_converts_xml_call_to_standard_tool_call_event():
    with mock_openai_upstream() as (base_url, _requests):
        gateway = load_gateway(base_url)

        async def run():
            transport = httpx.ASGITransport(app=gateway.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                async with client.stream(
                    "POST",
                    "/v1/chat/completions",
                    json={
                        "model": "Qwen/Test",
                        "stream": True,
                        "messages": [{"role": "user", "content": "read README"}],
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "parameters": {"type": "object", "properties": {}},
                                },
                            }
                        ],
                    },
                ) as response:
                    text = (await response.aread()).decode("utf-8")
                    return response.status_code, text

        status_code, text = asyncio.run(run())
        assert status_code == 200
        assert '"tool_calls"' in text
        assert '"name": "read_file"' in text
        assert "data: [DONE]" in text
