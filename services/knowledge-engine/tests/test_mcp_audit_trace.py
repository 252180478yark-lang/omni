from pathlib import Path
import sys

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


def test_audit_wrapper_has_trace_start_and_terminal_paths_without_approximate_join():
    source = (SERVICE_ROOT / "app" / "mcp" / "audit.py").read_text(encoding="utf-8")
    assert "emit_audit_event" in source
    assert "EventType.STARTED" in source
    assert "EventType.COMPLETED" in source
    assert "EventType.FAILED" in source
    assert "tool_name+time" not in source
