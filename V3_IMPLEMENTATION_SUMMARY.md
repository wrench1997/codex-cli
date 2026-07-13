# v3 Implementation Summary

- Preserves streamed `function_call` items when a relay's final `response.completed`
  event contains an empty or missing `output` array.
- Merges streamed output items with final response output by output index.
- Normalizes several non-standard relay tool-call shapes.
- Removes eager empty assistant prefix after tool results.
- Raises a visible diagnostic instead of silently accepting an empty response.
- Adds response-level debug summaries.
- Adds regression coverage for the exact empty-completed-output relay behavior.

Validation:

- `15 passed` in `tests/test_openai_responses_compat.py`
- `16 passed` including `tests/test_gateway_import.py`
- Python compileall passed
