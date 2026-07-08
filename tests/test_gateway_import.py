import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_gateway_app_imports_context_compressor():
    module = importlib.import_module("gateway.app")
    assert module.app is not None
