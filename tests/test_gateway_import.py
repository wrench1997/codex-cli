import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_gateway_app_imports_context_compressor():
    if importlib.util.find_spec("gateway") is None:
        pytest.skip("当前精简发行包不包含可选 gateway 模块")
    module = importlib.import_module("gateway.app")
    assert module.app is not None
