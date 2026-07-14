from src.codex.cli import (
    ChatAgent,
    _extract_response_text,
    _to_responses_tools,
    main,
)
from src.codex.config import CONFIG


def _sample_chat_tool():
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }


def test_chat_tools_are_flattened_for_responses():
    result = _to_responses_tools([_sample_chat_tool()])

    assert result == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "strict": False,
        }
    ]


def test_responses_payload_omits_gateway_private_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "send_temperature", False)
    agent = ChatAgent(str(tmp_path), agent_mode=False)
    agent.tool_transport = "native"
    agent._combined_tools = lambda: [_sample_chat_tool()]

    payload = agent._build_responses_payload("responses", stream=True)

    assert payload["stream"] is True
    assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["name"] == "read_file"
    assert "function" not in payload["tools"][0]
    assert "enable_thinking" not in payload
    assert "temperature" not in payload


def test_gateway_payload_keeps_legacy_schema(tmp_path):
    agent = ChatAgent(str(tmp_path), agent_mode=False)
    agent._combined_tools = lambda: [_sample_chat_tool()]

    payload = agent._build_responses_payload("gateway", stream=True)

    assert payload["tools"][0]["function"]["name"] == "read_file"
    assert payload["enable_thinking"] is True
    assert "temperature" in payload


def test_native_output_items_are_preserved(tmp_path):
    agent = ChatAgent(str(tmp_path), agent_mode=False)
    items = [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        },
    ]

    agent.add_response_output_items(items)
    agent.add_tool_result("call_1", "contents")

    assert agent.input_items[-3:] == items + [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "contents",
        }
    ]


def test_extract_response_text_from_output_items():
    response = {
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "hello"},
                    {"type": "output_text", "text": " world"},
                ],
            },
        ]
    }
    assert _extract_response_text(response) == "hello world"


def test_api_option_no_longer_overrides_environment_by_default():
    api_param = next(param for param in main.params if param.name == "api")
    assert api_param.default is None


def test_native_tool_loop_keeps_call_and_result_items(tmp_path):
    import asyncio

    agent = ChatAgent(str(tmp_path), agent_mode=True)
    responses = iter(
        [
            (
                "",
                {
                    "output": [
                        {"type": "reasoning", "id": "rs_1", "summary": []},
                        {
                            "type": "function_call",
                            "id": "fc_1",
                            "call_id": "call_1",
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    ]
                },
            ),
            (
                "finished",
                {
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_1",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "output_text", "text": "finished"}],
                        }
                    ]
                },
            ),
        ]
    )

    async def fake_stream_request(**_kwargs):
        agent._last_request_mode = "responses"
        return next(responses)

    async def fake_execute(name, args):
        assert name == "read_file"
        assert args == {"path": "README.md"}
        return True, "file contents"

    agent._stream_request = fake_stream_request
    agent.executor.execute = fake_execute

    result = asyncio.run(agent.run_turn())

    assert result == "finished"
    assert [item.get("type") for item in agent.input_items[1:]] == [
        "reasoning",
        "function_call",
        "function_call_output",
        "message",
    ]
    assert agent.input_items[3]["call_id"] == "call_1"


def test_strip_think_keeps_normal_text():
    from src.codex.cli import _strip_think

    assert _strip_think("normal answer") == "normal answer"
    assert _strip_think("<think>private</think>visible") == "visible"


def test_end_to_end_native_responses_tool_roundtrip(tmp_path):
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            requests.append(body)

            has_tool_output = any(
                isinstance(item, dict) and item.get("type") == "function_call_output"
                for item in body.get("input", [])
            )
            if not has_tool_output:
                output = [
                    {"type": "reasoning", "id": "rs_http", "summary": []},
                    {
                        "type": "function_call",
                        "id": "fc_http",
                        "call_id": "call_http",
                        "name": "read_file",
                        "arguments": '{"path":"README.md"}',
                    },
                ]
            else:
                output = [
                    {
                        "type": "message",
                        "id": "msg_http",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "roundtrip ok"}],
                    }
                ]

            response = {
                "id": "resp_http",
                "object": "response",
                "status": "completed",
                "output": output,
            }
            events = []
            for index, item in enumerate(output):
                events.append(
                    "data: "
                    + json.dumps(
                        {
                            "type": "response.output_item.done",
                            "output_index": index,
                            "item": item,
                        }
                    )
                    + "\n\n"
                )
            if has_tool_output:
                events.insert(
                    0,
                    "data: "
                    + json.dumps(
                        {"type": "response.output_text.delta", "delta": "roundtrip ok"}
                    )
                    + "\n\n",
                )
            events.append(
                "data: "
                + json.dumps({"type": "response.completed", "response": response})
                + "\n\n"
            )
            events.append("data: [DONE]\n\n")
            raw = "".join(events).encode()

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        agent = ChatAgent(
            str(tmp_path),
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            model="gpt-test",
            agent_mode=True,
        )
        agent.api_mode = "responses"
        agent._resolved_api_mode = "responses"
        agent.tool_transport = "native"

        async def fake_execute(name, args):
            assert name == "read_file"
            assert args == {"path": "README.md"}
            return True, "mock file contents"

        agent.executor.execute = fake_execute
        result = asyncio.run(agent.run_turn())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result == "roundtrip ok"
    assert len(requests) == 2
    assert requests[0]["tools"][0]["type"] == "function"
    assert "name" in requests[0]["tools"][0]
    assert "function" not in requests[0]["tools"][0]
    assert "enable_thinking" not in requests[0]
    assert "temperature" not in requests[0]

    second_input = requests[1]["input"]
    assert any(item.get("type") == "function_call" for item in second_input)
    assert any(
        item.get("type") == "function_call_output"
        and item.get("call_id") == "call_http"
        and item.get("output") == "mock file contents"
        for item in second_input
    )


def test_prompt_xml_tool_call_is_executed_and_result_returned_as_message(tmp_path):
    import asyncio

    agent = ChatAgent(str(tmp_path), agent_mode=True)
    agent.tool_transport = "prompt"
    xml = (
        "<tool_call>\n"
        "<function=list_directory>\n"
        "<parameter=path>.</parameter>\n"
        "<parameter=depth>2</parameter>\n"
        "</function>\n"
        "</tool_call>"
    )
    responses = iter(
        [
            (
                xml,
                {
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": xml}],
                        }
                    ]
                },
            ),
            (
                "当前目录包含 README.md。",
                {
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "当前目录包含 README.md。"}
                            ],
                        }
                    ]
                },
            ),
        ]
    )

    async def fake_stream_request(**_kwargs):
        agent._last_request_mode = "responses"
        return next(responses)

    calls = []

    async def fake_execute(name, args):
        calls.append((name, args))
        return True, "README.md\nsrc/\ntests/"

    agent._stream_request = fake_stream_request
    agent.executor.execute = fake_execute

    result = asyncio.run(agent.run_turn())

    assert result == "当前目录包含 README.md。"
    assert calls == [("list_directory", {"path": ".", "depth": 2})]
    assert not any(item.get("type") == "function_call_output" for item in agent.input_items)
    tool_result_messages = [
        item for item in agent.input_items
        if item.get("type") == "message"
        and item.get("role") == "user"
        and "<tool_response>" in str(item.get("content", ""))
    ]
    assert len(tool_result_messages) == 1
    assert "README.md" in tool_result_messages[0]["content"]


def test_prompt_payload_injects_tools_without_native_tools_when_forced(tmp_path):
    agent = ChatAgent(str(tmp_path), agent_mode=True)
    agent.tool_transport = "prompt"
    agent._combined_tools = lambda: [_sample_chat_tool()]

    payload = agent._build_responses_payload("responses", stream=True)

    assert "tools" not in payload
    assert "tool_choice" not in payload
    system_text = payload["input"][0]["content"]
    assert "<tools>" in system_text
    assert '"name":"read_file"' in system_text
    assert "<tool_call>" in system_text


def test_stream_request_reconstructs_function_call_from_argument_events(tmp_path):
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            events = [
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "type": "function_call",
                        "id": "fc_delta",
                        "call_id": "call_delta",
                        "name": "read_file",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "delta": '{"path":"README',
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "delta": '.md"}',
                },
                {"type": "response.completed"},
            ]
            raw = "".join("data: " + json.dumps(evt) + "\n\n" for evt in events)
            raw += "data: [DONE]\n\n"
            encoded = raw.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        agent = ChatAgent(
            str(tmp_path),
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            model="gpt-test",
            agent_mode=True,
        )
        agent.api_mode = "responses"
        agent._resolved_api_mode = "responses"
        _, response = asyncio.run(agent._stream_request())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response["output"][0]["type"] == "function_call"
    assert response["output"][0]["call_id"] == "call_delta"
    assert response["output"][0]["arguments"] == '{"path":"README.md"}'


def test_end_to_end_prompt_xml_relay_roundtrip(tmp_path):
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            requests.append(body)
            has_tool_response = any(
                isinstance(item, dict)
                and item.get("role") == "user"
                and "<tool_response>" in str(item.get("content", ""))
                for item in body.get("input", [])
            )
            if has_tool_response:
                text = "目录读取成功：README.md、src、tests。"
            else:
                text = (
                    "<tool_call>\n"
                    "<function=list_directory>\n"
                    "<parameter=path>.</parameter>\n"
                    "<parameter=depth>2</parameter>\n"
                    "</function>\n"
                    "</tool_call>"
                )
            response = {
                "id": "resp_prompt",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": text}],
                    }
                ],
            }
            raw = json.dumps(response, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        agent = ChatAgent(
            str(tmp_path),
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            model="gpt-test",
            agent_mode=True,
        )
        agent.api_mode = "responses"
        agent._resolved_api_mode = "responses"
        agent.tool_transport = "prompt"

        async def fake_execute(name, args):
            assert name == "list_directory"
            assert args == {"path": ".", "depth": 2}
            return True, "README.md\nsrc/\ntests/"

        agent.executor.execute = fake_execute
        result = asyncio.run(agent.run_turn())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result == "目录读取成功：README.md、src、tests。"
    assert len(requests) == 2
    assert "tools" not in requests[0]
    assert "<tools>" in requests[0]["input"][0]["content"]
    assert any(
        "README.md" in str(item.get("content", ""))
        for item in requests[1]["input"]
        if isinstance(item, dict)
    )


def test_completed_event_with_empty_output_does_not_drop_streamed_function_call(tmp_path):
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    expected_function_call = {
        "type": "function_call",
        "id": "fc_empty_completed",
        "call_id": "call_empty_completed",
        "name": "list_directory",
        "arguments": '{"path":".","depth":2}',
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            function_call = expected_function_call
            events = [
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": function_call,
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_empty_completed",
                        "object": "response",
                        "status": "completed",
                        "output": [],
                    },
                },
            ]
            raw = "".join("data: " + json.dumps(evt) + "\n\n" for evt in events)
            raw += "data: [DONE]\n\n"
            encoded = raw.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        agent = ChatAgent(
            str(tmp_path),
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            model="gpt-test",
            agent_mode=True,
        )
        agent.api_mode = "responses"
        agent._resolved_api_mode = "responses"
        _, response = asyncio.run(agent._stream_request())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response["output"] == [expected_function_call]


def test_end_to_end_empty_completed_output_still_executes_tool(tmp_path):
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            requests.append(body)
            has_tool_output = any(
                isinstance(item, dict) and item.get("type") == "function_call_output"
                for item in body.get("input", [])
            )

            if not has_tool_output:
                item = {
                    "type": "function_call",
                    "id": "fc_roundtrip_empty",
                    "call_id": "call_roundtrip_empty",
                    "name": "list_directory",
                    "arguments": '{"path":".","depth":2}',
                }
                events = [
                    {
                        "type": "response.output_item.done",
                        "output_index": 0,
                        "item": item,
                    },
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_roundtrip_empty",
                            "status": "completed",
                            "output": [],
                        },
                    },
                ]
            else:
                message = {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "目录里有 README.md。"}],
                }
                events = [
                    {"type": "response.output_text.delta", "delta": "目录里有 README.md。"},
                    {
                        "type": "response.output_item.done",
                        "output_index": 0,
                        "item": message,
                    },
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_roundtrip_final",
                            "status": "completed",
                            "output": [],
                        },
                    },
                ]

            raw = "".join("data: " + json.dumps(evt, ensure_ascii=False) + "\n\n" for evt in events)
            raw += "data: [DONE]\n\n"
            encoded = raw.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    tool_events = []

    try:
        agent = ChatAgent(
            str(tmp_path),
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            model="gpt-test",
            agent_mode=True,
        )
        agent.api_mode = "responses"
        agent._resolved_api_mode = "responses"
        agent.tool_transport = "native"

        async def fake_execute(name, args):
            assert name == "list_directory"
            assert args == {"path": ".", "depth": 2}
            return True, "README.md"

        async def on_tool_call(name, args):
            tool_events.append((name, args))

        agent.executor.execute = fake_execute
        result = asyncio.run(agent.run_turn(on_tool_call=on_tool_call))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result == "目录里有 README.md。"
    assert tool_events == [("list_directory", {"path": ".", "depth": 2})]
    assert len(requests) == 2
    assert any(
        item.get("type") == "function_call_output"
        and item.get("call_id") == "call_roundtrip_empty"
        for item in requests[1]["input"]
        if isinstance(item, dict)
    )


def test_prompt_json_tool_call_is_parsed():
    from src.codex.cli import _extract_function_call, _parse_tool_calls

    calls = _parse_tool_calls(
        '<mcodex_tool_call>{"name":"list_directory","arguments":{"path":".","depth":2}}</mcodex_tool_call>'
    )

    assert len(calls) == 1
    name, args, call_id = _extract_function_call(calls[0])
    assert name == "list_directory"
    assert args == {"path": ".", "depth": 2}
    assert call_id
    assert calls[0]["_mcodex_transport"] == "prompt"


def test_missing_tool_name_with_paths_is_repaired():
    from src.codex.cli import _extract_function_call, _repair_local_tool_call

    repaired = _repair_local_tool_call(
        {
            "type": "function_call",
            "call_id": "call_missing_name",
            "name": "",
            "arguments": '{"paths":["."],"query":"noop"}',
        },
        {"list_directory", "read_file"},
    )

    name, args, call_id = _extract_function_call(repaired)
    assert name == "list_directory"
    assert args == {"path": "."}
    assert call_id == "call_missing_name"


def test_chat_payload_uses_messages_and_prompt_transport(tmp_path):
    agent = ChatAgent(str(tmp_path), agent_mode=True)
    agent.tool_transport = "prompt"
    agent._combined_tools = lambda: [_sample_chat_tool()]

    payload = agent._build_responses_payload("chat", stream=True)

    assert payload["stream"] is True
    assert "input" not in payload
    assert "tools" not in payload
    assert payload["messages"][0]["role"] == "system"
    assert "mcodex local agent tools" in payload["messages"][0]["content"]


def test_end_to_end_chat_completions_prompt_roundtrip(tmp_path):
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            paths.append(self.path)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            requests.append(body)
            has_tool_response = any(
                isinstance(message, dict)
                and message.get("role") == "user"
                and "<tool_response>" in str(message.get("content", ""))
                for message in body.get("messages", [])
            )
            content = (
                "目录读取成功：README.md、src。"
                if has_tool_response
                else '<mcodex_tool_call>{"name":"list_directory","arguments":{"path":".","depth":2}}</mcodex_tool_call>'
            )
            response = {
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "model": "gpt-test",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            }
            raw = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        agent = ChatAgent(
            str(tmp_path),
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            model="gpt-test",
            agent_mode=True,
        )
        agent.api_mode = "chat"
        agent._resolved_api_mode = "chat"
        agent.tool_transport = "prompt"

        async def fake_execute(name, args):
            assert name == "list_directory"
            assert args == {"path": ".", "depth": 2}
            return True, "README.md\nsrc/"

        agent.executor.execute = fake_execute
        result = asyncio.run(agent.run_turn())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result == "目录读取成功：README.md、src。"
    assert paths == ["/v1/chat/completions", "/v1/chat/completions"]
    assert len(requests) == 2
    assert "tools" not in requests[0]
    assert any("<tool_response>" in str(message.get("content", "")) for message in requests[1]["messages"])


def test_agent_refusal_is_corrected_and_retried(tmp_path):
    import asyncio

    agent = ChatAgent(str(tmp_path), agent_mode=True)
    agent.api_mode = "chat"
    agent._resolved_api_mode = "chat"
    agent.tool_transport = "native"

    responses = iter([
        (
            "我无法直接读取你的本地目录，也没有权限访问本地文件。",
            {
                "status": "completed",
                "output": [{
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "我无法直接读取你的本地目录，也没有权限访问本地文件。"}],
                }],
            },
        ),
        (
            '<mcodex_tool_call>{"name":"list_directory","arguments":{"path":".","depth":1}}</mcodex_tool_call>',
            {
                "status": "completed",
                "output": [{
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": '<mcodex_tool_call>{"name":"list_directory","arguments":{"path":".","depth":1}}</mcodex_tool_call>'}],
                }],
            },
        ),
        (
            "当前目录包含 README.md。",
            {
                "status": "completed",
                "output": [{
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "当前目录包含 README.md。"}],
                }],
            },
        ),
    ])

    async def fake_stream_request(**_kwargs):
        agent._last_request_mode = "chat"
        return next(responses)

    executed = []

    async def fake_execute(name, args):
        executed.append((name, args))
        return True, "README.md"

    agent._stream_request = fake_stream_request
    agent.executor.execute = fake_execute
    result = asyncio.run(agent.run_turn())

    assert result == "当前目录包含 README.md。"
    assert agent.tool_transport == "prompt"
    assert executed == [("list_directory", {"path": ".", "depth": 1})]
    assert any("mcodex Agent 纠正" in str(item.get("content", "")) for item in agent.input_items)


def test_explicit_env_file_overrides_stale_windows_style_environment(tmp_path):
    import os
    import subprocess
    import sys

    env_file = tmp_path / "mcodex.env"
    env_file.write_text('CODEX_MODEL="from-dotenv"\nCODEX_API_MODE="chat"\n', encoding="utf-8")
    env = os.environ.copy()
    env["CODEX_MODEL"] = "stale-shell-value"
    env["CODEX_ENV_FILE"] = str(env_file)
    env["CODEX_ENV_OVERRIDE"] = "true"

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.codex.config import CONFIG; print(CONFIG.model); print(CONFIG.api_mode)",
        ],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.splitlines() == ["from-dotenv", "chat"]
