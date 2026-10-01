# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import constants
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

def _encode_mcp_message(payload: dict) -> bytes:
    # FastMCP stdio expects raw JSON per message (newline-delimited).
    return (json.dumps(payload) + "\n").encode("utf-8")


def _base_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", parsed.params, "", ""))


def _result_urls(structured_content: dict) -> list[str]:
    result = structured_content.get("result", [])
    if not isinstance(result, list):
        return []
    return [item.get("url") for item in result if isinstance(item, dict) and item.get("url")]


def _read_docker_frame(sock, timeout: float) -> bytes:
    deadline = time.time() + timeout
    header = b""
    while len(header) < 8:
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for docker frame header.")
        chunk = sock.recv(8 - len(header))
        if not chunk:
            time.sleep(0.01)
            continue
        header += chunk

    # Docker frame format can be either in multiplexed (each frame prefixed with an 8-byte header) or raw mode.
    # byte 0: stream type (0x01 = stdout, 0x02 = stderr)
    # bytes 1-3: Reserved, always \x00\x00\x00
    # bytes 4-7: Payload size (big-endian uint32)
    # This checks on header if frame is multiplexed or in raw mode. If bytes 1-3 are not zeros, the data is likely raw/unframed output, 
    # so the function returns it directly instead of trying to parse frame headers and extract payloads
    if header[1:4] != b"\x00\x00\x00":
        return header

    size = int.from_bytes(header[4:8], "big")
    payload = b""
    while len(payload) < size:
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for docker frame payload.")
        chunk = sock.recv(size - len(payload))
        if not chunk:
            time.sleep(0.01)
            continue
        payload += chunk
    return payload


def _read_mcp_message(sock, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    buffer = b""
    while True:
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for MCP response line.")
        try:
            frame = _read_docker_frame(sock, timeout)
        except TimeoutError:
            raise
        buffer += frame
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if not line:
                continue
            try:
                return json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                idx = line.find(b"{")
                if idx != -1:
                    try:
                        return json.loads(line[idx:].decode("utf-8"))
                    except json.JSONDecodeError:
                        continue

def test_mcp_stdio_transport_responds(platform):

    print("\n***Platform: ", platform)
    
    image = os.getenv("MCP_IMAGE", constants.MCP_DOCKER_IMAGE)
    print("\n***Docker Image: ", image)

    repo_root = Path(__file__).resolve().parents[1]
    print("\n***Repo Root: ", repo_root)

    with (
        DockerContainer(image)
        .with_volume_mapping(str(repo_root), "/workspace")
        .with_kwargs(stdin_open=True, tty=False, network_mode="none")
    ) as container:
        wait_for_logs(container, "Starting MCP server", timeout=60)
        socket_wrapper = container.get_wrapped_container().attach_socket(
            params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1}
        )
        raw_socket = socket_wrapper._sock
        raw_socket.settimeout(10)

        raw_socket.sendall(_encode_mcp_message(constants.INIT_REQUEST))
        response = _read_mcp_message(raw_socket, timeout=20)

        #Check Container Init Test
        assert response.get("id") == 1, "Test Failed: MCP initialize response id mismatch."
        assert "result" in response, "Test Failed: MCP initialize response missing result field."
        assert "serverInfo" in response["result"], "Test Failed: MCP initialize response missing serverInfo field."
        raw_socket.sendall(
            _encode_mcp_message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        )

        def _read_response(expected_id: int, timeout: float = 10.0) -> dict:
            deadline = time.time() + timeout
            while time.time() < deadline:
                message = _read_mcp_message(raw_socket, timeout=timeout)
                if message.get("id") == expected_id:
                    return message
            raise TimeoutError(f"Timed out waiting for MCP response id={expected_id}.")

        raw_socket.sendall(
            _encode_mcp_message(
                {"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": {}}
            )
        )
        tools = _read_response(8)["result"]["tools"]
        tool_names = {tool["name"] for tool in tools}
        assert tool_names == {"knowledge_base_search"}
        knowledge_search = next(
            tool for tool in tools if tool["name"] == "knowledge_base_search"
        )
        assert (
            "Use this tool for Arm-related runtime-performance, profiling, hotspot, "
            "benchmarking, and regression questions."
            in knowledge_search["description"]
        )
        assert (
            "Use this tool for Arm-related questions about collecting system architecture, "
            "CPU, memory, and other host hardware details."
            in knowledge_search["description"]
        )

        print("\n***Test Passed: arm-mcp container initialized and ran successfully")

        # Skills are available through both standard resource and prompt APIs.
        raw_socket.sendall(_encode_mcp_message(
            {"jsonrpc": "2.0", "id": 9, "method": "resources/list", "params": {}}
        ))
        resources = _read_response(9)["result"]["resources"]
        skill_uris = {r["uri"] for r in resources if r["uri"].endswith("/SKILL.md")}
        names = {"arm-container-inspect", "arm-migration-scan", "arm-assembly-analyze"}
        assert skill_uris == {f"skill://{name}/SKILL.md" for name in names}
        raw_socket.sendall(_encode_mcp_message(
            {"jsonrpc": "2.0", "id": 10, "method": "prompts/list", "params": {}}
        ))
        assert {p["name"] for p in _read_response(10)["result"]["prompts"]} == names
        for offset, name in enumerate(sorted(names)):
            request_id = 20 + offset * 2
            raw_socket.sendall(_encode_mcp_message({
                "jsonrpc": "2.0", "id": request_id, "method": "resources/read",
                "params": {"uri": f"skill://{name}/SKILL.md"},
            }))
            document = _read_response(request_id)["result"]["contents"][0]["text"]
            assert document.startswith("---\n")
            raw_socket.sendall(_encode_mcp_message({
                "jsonrpc": "2.0", "id": request_id + 1, "method": "prompts/get",
                "params": {"name": name},
            }))
            assert _read_response(request_id + 1)["result"]["messages"][0]["content"]["text"] == document

        #Check NGINX Query Test
        raw_socket.sendall(_encode_mcp_message(constants.CHECK_NGINX_REQUEST))
        check_nginx_response = _read_response(4, timeout=60)
        nginx_structured_content = check_nginx_response["result"]["structuredContent"]
        expected_nginx_urls = {_base_url(expected) for expected in constants.EXPECTED_CHECK_NGINX_RESPONSE}
        actual_nginx_urls = {_base_url(url) for url in _result_urls(nginx_structured_content)}
        assert expected_nginx_urls & actual_nginx_urls, "Test Failed: MCP check_nginx tool failed: content mismatch., Expected one of: {}, Received: {}".format(json.dumps(constants.EXPECTED_CHECK_NGINX_RESPONSE,indent=2), json.dumps(check_nginx_response.get("result")["structuredContent"],indent=2))
        print("\n***Test Passed: MCP check_nginx tool succeeded")

def test_bundled_clis_run_without_mcp(tmp_path):
    image = os.getenv("MCP_IMAGE", constants.MCP_DOCKER_IMAGE)
    source = tmp_path / "source"
    reports = tmp_path / "reports"
    source.mkdir()
    reports.mkdir()
    (source / "example.cpp").write_text("#include <immintrin.h>\n")
    (source / "loop.s").write_text("add x1, x1, x2\n")

    def run(executable, *arguments):
        return subprocess.run(
            ["docker", "run", "--rm", "--network", "none",
             "--mount", f"type=bind,src={source},dst=/workspace,readonly",
             "--mount", f"type=bind,src={reports},dst=/results",
             "--entrypoint", executable, image, *arguments],
            check=True, capture_output=True, text=True, timeout=120,
        )

    run("skopeo", "--version")
    for language in ("cpp", "python", "go", "js", "java"):
        run(f"migrate-ease-{language}", "--help")
    run("migrate-ease-cpp", "--march", "armv8-a", "--output", "/results/cpp.json", "/workspace")
    report = json.loads((reports / "cpp.json").read_text())
    assert report["issues"], "The x86-only include should produce a migration finding"
    analysis = run("llvm-mca", "--mtriple=aarch64", "--mcpu=neoverse-n1", "/workspace/loop.s")
    assert "Iterations:" in analysis.stdout
    assert "Block RThroughput:" in analysis.stdout


if __name__ == "__main__":
    pytest.main([__file__])
