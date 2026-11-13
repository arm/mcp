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


def test_search_options_schema_validation_forwarding_and_defaults(tmp_path, monkeypatch):
    import asyncio
    import importlib.util
    import pytest
    from fastmcp import Client
    from fastmcp.exceptions import ToolError
    import arm_kb_search
    from arm_kb_search import SearchFilters

    calls = []
    expected = [{"url": "https://example.org/guide/#section", "snippet": "Evidence",
                 "page_url": "https://example.org/guide/", "parent_page_url": "https://example.org/"}]
    monkeypatch.setattr(arm_kb_search, "load_search_resources", lambda **kwargs: None)
    def search(query, resources, *, filters, k, scope):
        assert filters is None or isinstance(filters, SearchFilters)
        calls.append((query, {"filters": filters, "k": k, "scope": scope}))
        return [] if filters is not None and filters.product == "missing" else expected
    monkeypatch.setattr(arm_kb_search, "search", search)
    monkeypatch.setattr(invocation_logger, "WORKSPACE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("filter_options_server", Path(__file__).parents[1] / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)

    async def exercise():
        async with Client(server.mcp) as client:
            tool = next(t for t in await client.list_tools() if t.name == "knowledge_base_search")
            assert {"query", "invocation_reason", "filters", "k", "scope"} == set(tool.inputSchema["properties"])
            assert tool.inputSchema["properties"]["scope"]["enum"] == ["chunks", "page"]
            integer_schema = tool.inputSchema["properties"]["k"]
            assert integer_schema.get("type") == "integer"
            assert integer_schema["default"] == 5
            assert "k" not in tool.inputSchema.get("required", [])
            assert integer_schema["minimum"] == 1
            assert integer_schema["maximum"] == 20
            filter_model_schema = next(s for s in tool.inputSchema["properties"]["filters"]["anyOf"]
                                       if s["type"] == "object")
            shared_schema = arm_kb_search.SearchFilters.model_json_schema()
            # FastMCP removes display titles while retaining validation and descriptions.
            assert filter_model_schema["properties"] == {
                name: {key: value for key, value in field.items() if key != "title"}
                for name, field in shared_schema["properties"].items()}
            assert filter_model_schema["additionalProperties"] is False
            filter_schema = filter_model_schema["properties"]
            for field in ("doc_type", "product", "platform", "edition"):
                options = filter_schema[field]["anyOf"]
                assert {option["type"] for option in options} == {"string", "array", "null"}
                array = next(option for option in options if option["type"] == "array")
                assert array["minItems"] == 1 and array["items"]["type"] == "string"
            for options, expected_filters in (
                ({}, None),
                ({"k": 5}, None),
                ({"filters": None}, None),
                ({"filters": {}}, SearchFilters()),
                ({"filters": {"product": None}}, SearchFilters()),
            ):
                result = await client.call_tool(tool.name, {"query": "needle", **options})
                assert result.structured_content["result"] == json.loads(result.content[0].text) == expected
                assert calls[-1] == ("needle", {"k": 5, "filters": expected_filters, "scope": "chunks"})
                logged_call = json.loads((tmp_path / "mcp-traffic.jsonl").read_text().splitlines()[-2])
                assert logged_call["args"] == {"query": "needle", "k": 5, "scope": "chunks",
                                               "filters": None if expected_filters is None else {}}
            result = await client.call_tool(tool.name, {"query": "needle", "k": 1,
                "filters": {"doc_type": " Learning Paths ", "product": "ARM", "platform": "Linux", "edition": "Open-Source"}})
            assert result.structured_content["result"] == expected
            assert calls[-1] == ("needle", {"k": 1, "scope": "chunks", "filters": SearchFilters(
                doc_type="learning paths", product="arm", platform="linux", edition="open-source")})
            alternatives = {"doc_type": [" Learning Paths ", "Install Guides", "learning paths"],
                            "platform": [" Linux ", "Windows"], "product": ["ARM"], "edition": ["OPEN-SOURCE"]}
            await client.call_tool(tool.name, {"query": "needle", "filters": alternatives, "k": 2})
            assert calls[-1] == ("needle", {"k": 2, "scope": "chunks", "filters": SearchFilters(
                doc_type=("learning paths", "install guides"), platform=("linux", "windows"),
                product=("arm",), edition=("open-source",))})
            await client.call_tool(tool.name, {"query": "needle", "filters": {"platform": ["linux", "windows"], "product": "Arm"}})
            assert calls[-1] == ("needle", {"k": 5, "scope": "chunks",
                                           "filters": SearchFilters(platform=("linux", "windows"), product="arm")})
            for k in (1, 20):
                result = await client.call_tool(tool.name, {"query": "needle", "k": k})
                assert result.structured_content["result"] == expected
                assert calls[-1] == ("needle", {"k": k, "filters": None, "scope": "chunks"})
            empty = await client.call_tool(tool.name, {"query": "needle", "filters": {"product": "missing"}})
            assert empty.structured_content["result"] == []
            for scope in ("chunks", "page"):
                await client.call_tool(tool.name, {"query": "needle", "scope": scope})
                assert calls[-1] == ("needle", {"k": 5, "filters": None, "scope": scope})
            before = len(calls)
            invalid = [{"k": v} for v in (None, 0, -1, 21, 100, True, 1.5, "3")]
            invalid += [{"scope": v} for v in (None, "parent_resource", "parent", "learning_path", "PAGE", [], True)]
            invalid += [{"filters": f} for f in ({"unknown": "x"}, {"product": " "}, {"product": 3}, [])]
            invalid += [{"filters": {"platform": v}} for v in ([], [None], ["linux", " "], ["linux", 3], [["linux"]])]
            for options in invalid:
                with pytest.raises(ToolError):
                    await client.call_tool(tool.name, {"query": "needle", **options})
            assert len(calls) == before
    asyncio.run(exercise())
    logged = [json.loads(x) for x in (tmp_path / "mcp-traffic.jsonl").read_text().splitlines()]
    assert len(logged) == 2 * len(calls)
    assert logged[0]["id"] == logged[1]["id"] and logged[1]["result"] == expected
    assert logged[0]["args"] == {"query": "needle", "k": 5, "filters": None, "scope": "chunks"}
    assert next(entry["args"] for entry in logged if entry.get("args", {}).get("filters")) == {"query": "needle", "k": 1, "scope": "chunks", "filters": {
        "doc_type": "learning paths", "product": "arm", "platform": "linux", "edition": "open-source"}}


def test_search_failures_are_mcp_errors_and_logged_for_every_scope(tmp_path, monkeypatch):
    import asyncio
    import importlib.util
    import arm_kb_search
    from fastmcp import Client
    from utils import error_handling

    monkeypatch.setattr(arm_kb_search, "load_search_resources", lambda **kwargs: None)

    def fail_search(*args, **kwargs):
        raise RuntimeError("Search backend unavailable")

    monkeypatch.setattr(arm_kb_search, "search", fail_search)
    monkeypatch.setattr(invocation_logger, "WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(error_handling, "WORKSPACE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("search_error_server", Path(__file__).parents[1] / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)

    async def exercise():
        async with Client(server.mcp) as client:
            for options in ({}, {"scope": "chunks"}, {"scope": "page"}):
                result = await client.call_tool(
                    "knowledge_base_search", {"query": "guide", **options}, raise_on_error=False)
                assert result.is_error
                assert any("Search backend unavailable" in item.text for item in result.content)
                logs = [json.loads(line) for line in (tmp_path / "mcp-traffic.jsonl").read_text().splitlines()]
                call, response = logs[-2:]
                assert call["id"] == response["id"]
                assert response["result"]["status"] == "error"
                assert response["result"]["error_type"] == "RuntimeError"
                assert response["result"]["message"] == "Search backend unavailable"
                assert response["result"]["args"] == call["args"]

    asyncio.run(exercise())


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
            expanded = await client.call_tool("knowledge_base_search", {"query": "guide", "scope": "page", "k": 1})
            assert [r["snippet"] for r in expanded.structured_content["result"]] == ["section 0", "section 1"]
            assert all(r["context"]["scope"] == "page" for r in expanded.structured_content["result"])
            rows[1].pop("document_context")
            with pytest.raises(ToolError, match="Regenerate chunks"):
                await client.call_tool("knowledge_base_search", {"query": "guide", "scope": "page"})
    asyncio.run(exercise())
    logs = [json.loads(line) for line in (tmp_path / "mcp-traffic.jsonl").read_text().splitlines()]
    assert logs[-2]["args"]["scope"] == "page" and logs[-1]["result"]["status"] == "error"
