# Compatibility validation

Validation date: 2026-07-16

## Passed locally

```text
python -m pytest -q tests --ignore=tests/test1.py --ignore=tests/test_ttft_cache.py
25 passed

PYTHONPATH=gateway python -m pytest -q gateway/test_context_compressor.py
6 passed

python -m compileall -q gateway src scripts
passed
```

The local integration tests start a mock OpenAI-compatible upstream and verify:

- server root normalization to `/v1/chat/completions`;
- upstream Bearer authentication;
- backward-compatible non-stream Chat Completions tool calls;
- backward-compatible streaming Chat Completions tool calls;
- Responses `function_call` and `function_call_output` roundtrip;
- tool results are sent through the prompt/XML protocol instead of an invalid tool message without `tool_call_id`.

## External endpoint result

The supplied endpoint `http://112.111.7.91:7980` could not be reached from the build environment. TCP connection attempts to port 7980 failed immediately for `/v1/models`, `/health`, `/metrics`, and `/v1/chat/completions`.

This only proves that the endpoint was unreachable from the build environment. It may still be reachable from the user's LAN, VPN, allowlisted IP, or local machine. Run the included probe locally:

```powershell
uv run python scripts/test_api_compat.py `
  --base "http://112.111.7.91:7980" `
  --model "Qwen/Qwen3.5-397B-A17B-FP8"
```
