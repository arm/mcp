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
                 "page_url": "https://example.org/step/", "parent_page_url": "https://example.org/"}]
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


def test_search_options_schema_validation_forwarding_and_defaults(tmp_path, monkeypatch):
    import asyncio
    import importlib.util
    import pytest
    from fastmcp import Client
    from fastmcp.exceptions import ToolError
    import arm_kb_search

    calls = []
    expected = [{"url": "https://example.org/guide/#section", "snippet": "Evidence"}]
    monkeypatch.setattr(arm_kb_search, "load_search_resources", lambda **kwargs: None)
    def search(query, resources, **options):
        calls.append((query, options))
        return [] if options.get("filters", {}).get("product") == "missing" else expected
    monkeypatch.setattr(arm_kb_search, "search", search)
    monkeypatch.setattr(invocation_logger, "WORKSPACE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("filter_options_server", Path(__file__).parents[1] / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)

    async def exercise():
        async with Client(server.mcp) as client:
            tool = next(t for t in await client.list_tools() if t.name == "knowledge_base_search")
            assert {"query", "invocation_reason", "filters", "k", "scope"} == set(tool.inputSchema["properties"])
            assert tool.inputSchema["properties"]["scope"]["enum"] == ["chunks", "page", "parent_resource"]
            integer_schema = next(s for s in tool.inputSchema["properties"]["k"]["anyOf"] if s["type"] == "integer")
            assert integer_schema["minimum"] == 1
            assert "maximum" not in integer_schema
            for options in ({}, {"filters": None, "k": None}, {"filters": {}}, {"filters": {"product": None}}):
                result = await client.call_tool(tool.name, {"query": "needle", **options})
                assert result.structured_content["result"] == expected
                assert calls[-1] == ("needle", {})
            result = await client.call_tool(tool.name, {"query": "needle", "k": 1,
                "filters": {"doc_type": " Learning Paths ", "product": "ARM", "platform": "Linux", "edition": "Open-Source"}})
            assert result.structured_content["result"] == expected
            assert calls[-1] == ("needle", {"k": 1, "filters": {
                "doc_type": "learning paths", "product": "arm", "platform": "linux", "edition": "open-source"}})
            await client.call_tool(tool.name, {"query": "needle", "k": 20})
            assert calls[-1] == ("needle", {"k": 20})
            for k in (21, 100):
                result = await client.call_tool(tool.name, {"query": "needle", "k": k})
                assert result.structured_content["result"] == expected
                assert calls[-1] == ("needle", {"k": k})
            empty = await client.call_tool(tool.name, {"query": "needle", "filters": {"product": "missing"}})
            assert empty.structured_content["result"] == []
            for scope in ("chunks", "page", "parent_resource"):
                await client.call_tool(tool.name, {"query": "needle", "scope": scope})
                assert calls[-1] == ("needle", {} if scope == "chunks" else {"scope": scope})
            before = len(calls)
            invalid = [{"k": v} for v in (0, -1, True, 1.5, "3")]
            invalid += [{"scope": v} for v in (None, "parent", "learning_path", "PAGE", [], True)]
            invalid += [{"filters": f} for f in ({"unknown": "x"}, {"product": " "}, {"product": 3}, {"product": ["Arm"]}, [])]
            for options in invalid:
                with pytest.raises(ToolError):
                    await client.call_tool(tool.name, {"query": "needle", **options})
            assert len(calls) == before
    asyncio.run(exercise())
    logged = [json.loads(x) for x in (tmp_path / "mcp-traffic.jsonl").read_text().splitlines()]
    assert logged[8]["args"] == {"query": "needle", "k": 1, "filters": {
        "doc_type": "learning paths", "product": "arm", "platform": "linux", "edition": "open-source"}}


def test_scope_expansion_through_mcp_and_missing_metadata_error(tmp_path, monkeypatch):
    import asyncio
    import importlib.util
    import pytest
    import arm_kb_search
    from fastmcp import Client
    from fastmcp.exceptions import ToolError
    from utils import error_handling

    url = "https://example.org/guide"
    rows = [{"url": url + "#section", "original_text": f"section {i}", "chunk_uuid": str(i),
             "document_context": {"format": 1, "url": url, "chunk_index": i, "chunk_count": 2}}
            for i in range(2)]
    state = arm_kb_search.SearchResources(list(reversed(rows)), object(), None, None, include_disclaimers=False)
    monkeypatch.setattr(arm_kb_search, "load_search_resources", lambda **kwargs: state)
    monkeypatch.setattr(arm_kb_search.resources, "hybrid_search", lambda *a, **kw: [{"metadata": rows[1]}])
    monkeypatch.setattr(invocation_logger, "WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(error_handling, "WORKSPACE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("context_scope_server", Path(__file__).parents[1] / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)

    async def exercise():
        async with Client(server.mcp) as client:
            baseline = await client.call_tool("knowledge_base_search", {"query": "guide"})
            assert [r["snippet"] for r in baseline.structured_content["result"]] == ["section 1"]
            for scope in ("page", "parent_resource"):
                expanded = await client.call_tool("knowledge_base_search", {"query": "guide", "scope": scope, "k": 1})
                assert [r["snippet"] for r in expanded.structured_content["result"]] == ["section 0", "section 1"]
                assert all(r["context"]["scope"] == "page" for r in expanded.structured_content["result"])
            rows[1].pop("document_context")
            with pytest.raises(ToolError, match="Regenerate chunks"):
                await client.call_tool("knowledge_base_search", {"query": "guide", "scope": "page"})
    asyncio.run(exercise())
    logs = [json.loads(line) for line in (tmp_path / "mcp-traffic.jsonl").read_text().splitlines()]
    assert logs[-2]["args"]["scope"] == "page" and logs[-1]["result"]["status"] == "error"
