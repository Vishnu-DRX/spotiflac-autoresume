import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# The UI layer needs pywinauto + Windows. Stub it so the pure logic is testable anywhere.
try:
    import pywinauto  # noqa: F401
except ImportError:
    stub = types.ModuleType("pywinauto")
    stub.Desktop = object
    sys.modules["pywinauto"] = stub
    if not hasattr(__import__("ctypes"), "windll"):
        import ctypes
        ctypes.windll = types.SimpleNamespace(user32=types.SimpleNamespace())
