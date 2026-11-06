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


def test_search_source_links_survive_mcp_response_and_logging(tmp_path, monkeypatch):
    import asyncio
    import importlib.util

    from fastmcp import Client

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    import arm_kb_search

    expected = [{"url": "https://example.org/step/#install", "snippet": "Run this.",
                 "page_url": "https://example.org/step/", "learning_path_url": "https://example.org/"}]
    monkeypatch.setattr(arm_kb_search, "load_search_resources", lambda **kwargs: None)
    monkeypatch.setattr(arm_kb_search, "search", lambda *args: expected)
    monkeypatch.setattr(invocation_logger, "WORKSPACE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("source_links_server", Path(__file__).parents[1] / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)

    async def exercise():
        async with Client(server.mcp) as client:
            assert {t.name for t in await client.list_tools()} == {
                "knowledge_base_search", "check_image", "migrate_ease_scan", "skopeo", "mca"}
            result = await client.call_tool("knowledge_base_search", {"query": "installation"})
            assert result.structured_content["result"] == json.loads(result.content[0].text) == expected

    asyncio.run(exercise())
    calls = [json.loads(line) for line in (tmp_path / "mcp-traffic.jsonl").read_text().splitlines()]
    assert len(calls) == 2 and calls[0]["id"] == calls[1]["id"]
    assert calls[1]["result"] == expected
