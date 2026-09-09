import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import invocation_logger


def test_logs_paired_call_and_result(tmp_path, monkeypatch):
    traffic_path = tmp_path / "mcp-traffic.jsonl"
    monkeypatch.setattr(invocation_logger, "WORKSPACE_DIR", str(tmp_path))

    entry_id = invocation_logger.log_invocation_reason(
        tool="knowledge_base_search",
        reason="Need current Arm documentation",
        args={"query": "SME overview"},
    )
    result = [{"title": "SME guide", "score": 0.9}]
    invocation_logger.log_tool_result(entry_id, "knowledge_base_search", result)

    entries = [json.loads(line) for line in traffic_path.read_text().splitlines()]
    assert entries == [
        {
            "id": entry_id,
            "timestamp": entries[0]["timestamp"],
            "tool": "knowledge_base_search",
            "args": {"query": "SME overview"},
            "invocation_reason": "Need current Arm documentation",
        },
        {
            "id": entry_id,
            "type": "result",
            "tool": "knowledge_base_search",
            "result": result,
        },
    ]


def test_logs_call_without_invocation_reason(tmp_path, monkeypatch):
    traffic_path = tmp_path / "mcp-traffic.jsonl"
    monkeypatch.setattr(invocation_logger, "WORKSPACE_DIR", str(tmp_path))

    entry_id = invocation_logger.log_invocation_reason(
        tool="knowledge_base_search",
        reason=None,
        args={"query": "SVE2"},
    )

    entry = json.loads(traffic_path.read_text())
    assert entry["id"] == entry_id
    assert entry["invocation_reason"] is None
