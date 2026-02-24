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
import time
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

def _encode_mcp_message(payload: dict) -> bytes:
    # FastMCP stdio expects raw JSON per message (newline-delimited).
    return (json.dumps(payload) + "\n").encode("utf-8")


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

    #Select the appropriate docker image based on platform
    if platform == constants.DEFAULT_PLATFORM:
        image = os.getenv("MCP_IMAGE", constants.MCP_DOCKER_IMAGE_ARM)
    else:
        image = os.getenv("MCP_IMAGE", constants.MCP_DOCKER_IMAGE_X86)
    
    print("\n***Docker Image: ", image)

    repo_root = Path(__file__).resolve().parents[1]
    print("\n***Repo Root: ", repo_root)
    with (
        DockerContainer(image)
        .with_volume_mapping(str(repo_root), "/workspace")
        .with_kwargs(stdin_open=True, tty=False)
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
            _encode_mcp_message({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        )

        def _read_response(expected_id: int, timeout: float = 10.0) -> dict:
            deadline = time.time() + timeout
            while time.time() < deadline:
                message = _read_mcp_message(raw_socket, timeout=timeout)
                if message.get("id") == expected_id:
                    return message
            raise TimeoutError(f"Timed out waiting for MCP response id={expected_id}.")

        print("\n***Test Passed: arm-mcp container initilized and ran successfully")

        #Check Image Tool Test
        raw_socket.sendall(_encode_mcp_message(constants.CHECK_IMAGE_REQUEST))
        check_image_response = _read_response(2, timeout=60)
        assert check_image_response.get("result")["structuredContent"] == constants.EXPECTED_CHECK_IMAGE_RESPONSE, "Test Failed: MCP check_image tool failed: content mismatch. Expected: {}, Received: {}".format(json.dumps(constants.EXPECTED_CHECK_IMAGE_RESPONSE,indent=2), json.dumps(check_image_response.get("result")["structuredContent"],indent=2))
        print("\n***Test Passed: MCP check_image tool succeeded")

        #Check Skopeo Tool Test
        raw_socket.sendall(_encode_mcp_message(constants.CHECK_SKOPEO_REQUEST))
        check_skopeo_response = _read_response(3, timeout=60)
        actual_os = json.loads(check_skopeo_response.get("result")["structuredContent"]["stdout"]).get("Os")
        actual_status = check_skopeo_response.get("result")["structuredContent"].get("status")
        assert actual_os == json.loads(constants.EXPECTED_CHECK_SKOPEO_RESPONSE["stdout"]).get("Os"), "Test Failed: MCP check_skopeo tool failed: Os mismatch. Expected: {}, Received: {}".format(constants.EXPECTED_CHECK_SKOPEO_RESPONSE["Os"], actual_os)
        assert actual_status == constants.EXPECTED_CHECK_SKOPEO_RESPONSE["status"], "Test Failed: MCP check_skopeo tool failed: Status mismatch. Expected: {}, Received: {}".format(constants.EXPECTED_CHECK_SKOPEO_RESPONSE["status"], actual_status)
        print("\n***Test Passed: MCP check_skopeo tool succeeded")

        #Check NGINX Query Test
        raw_socket.sendall(_encode_mcp_message(constants.CHECK_NGINX_REQUEST))
        check_nginx_response = _read_response(4, timeout=60)
        urls = json.dumps(check_nginx_response["result"]["structuredContent"])
        assert any(expected in urls for expected in constants.EXPECTED_CHECK_NGINX_RESPONSE), "Test Failed: MCP check_nginx tool failed: content mismatch., Expected one of: {}, Received: {}".format(json.dumps(constants.EXPECTED_CHECK_NGINX_RESPONSE,indent=2), json.dumps(check_nginx_response.get("result")["structuredContent"],indent=2))
        print("\n***Test Passed: MCP check_nginx tool succeeded")

        #Check Migrate Ease Tool Test
        raw_socket.sendall(_encode_mcp_message(constants.CHECK_MIGRATE_EASE_TOOL_REQUEST))
        check_migrate_ease_tool_response = _read_response(5, timeout=60)
        #assert only the status field to avoid mismatches due to dynamic fields
        assert check_migrate_ease_tool_response.get("result")["structuredContent"]["status"] == constants.EXPECTED_CHECK_MIGRATE_EASE_TOOL_RESPONSE_STATUS, "Test Failed: MCP check_migrate_ease_tool tool failed: status mismatch. Expected: {}, Received: {}".format(constants.EXPECTED_CHECK_MIGRATE_EASE_TOOL_RESPONSE_STATUS, check_migrate_ease_tool_response.get("result")["structuredContent"]["status"])
        print("\n***Test Passed: MCP check_migrate_ease_tool tool succeeded")

        #Check Sysreport Tool Test
        raw_socket.sendall(_encode_mcp_message(constants.CHECK_SYSREPORT_TOOL_REQUEST))
        check_sysreport_response = _read_response(6, timeout=60)
        assert check_sysreport_response.get("result")["structuredContent"] == constants.EXPECTED_CHECK_SYSREPORT_TOOL_RESPONSE, "Test Failed: MCP sysreport_instructions tool failed: content mismatch. Expected: {}, Received: {}".format(json.dumps(constants.EXPECTED_CHECK_SYSREPORT_TOOL_RESPONSE,indent=2), json.dumps(check_sysreport_response.get("result")["structuredContent"],indent=2))
        print("\n***Test Passed: MCP sysreport_instructions tool succeeded")

        #Check MCA Tool Test - works only on platform=linux/arm64
        if platform == constants.DEFAULT_PLATFORM:
            raw_socket.sendall(_encode_mcp_message(constants.CHECK_MCA_TOOL_REQUEST))
            check_mca_response = _read_response(7, timeout=60)
            assert check_mca_response.get("result")["structuredContent"]["status"] == constants.EXPECTED_CHECK_MCA_TOOL_RESPONSE_STATUS, "Test Failed: MCP mca tool failed: status mismatch.Expected: {}, Received: {}".format(json.dumps(constants.EXPECTED_CHECK_MCA_TOOL_RESPONSE_STATUS,indent=2), json.dumps(check_mca_response.get("result")["structuredContent"]["status"],indent=2))
            print("\n***Test Passed: MCP mca tool succeeded")
        else:
            print("\n***Test NA: MCP mca tool is not supported on this platform: {}".format(platform))
        
if __name__ == "__main__":
    pytest.main([__file__])
