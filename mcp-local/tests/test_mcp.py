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
import shutil
import subprocess
import tempfile
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
    
    image = os.getenv("MCP_IMAGE", constants.MCP_DOCKER_IMAGE)
    print("\n***Docker Image: ", image)

    repo_root = Path(__file__).resolve().parents[1]
    print("\n***Repo Root: ", repo_root)

    with tempfile.TemporaryDirectory(prefix="apx-test-keys-") as temp_keys_dir:
        temp_keys_path = Path(temp_keys_dir)
        pem_path = temp_keys_path / "ssh-key.pem"
        known_hosts_path = temp_keys_path / "known_hosts"
        pub_key_path = temp_keys_path / "ssh-key.pem.pub"

        external_ssh_key_path = os.getenv("APX_TEST_SSH_KEY_PATH")
        external_known_hosts_path = os.getenv("APX_TEST_KNOWN_HOSTS_PATH")

        if external_ssh_key_path:
            shutil.copyfile(external_ssh_key_path, pem_path)
        else:
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(pem_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            if pub_key_path.exists():
                pub_key_path.unlink()

        if external_known_hosts_path:
            shutil.copyfile(external_known_hosts_path, known_hosts_path)
        else:
            known_hosts_path.write_text(
                "172.17.0.1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKnownHostKeyForIntegrationTestsOnly\n",
                encoding="utf-8",
            )

        os.chmod(pem_path, 0o600)
        os.chmod(known_hosts_path, 0o644)

        print("\n***Generated Dummy SSH Key: ", pem_path)
        print("\n***Generated Dummy known_hosts: ", known_hosts_path)

        with (
            DockerContainer(image)
            .with_volume_mapping(str(repo_root), "/workspace")
            .with_volume_mapping(str(temp_keys_path), "/run/keys", mode="ro")
            .with_env("SSH_KEY_PATH", "/tmp/ssh-key.pem")
            .with_env("KNOWN_HOSTS_PATH", "/tmp/known_hosts")
            .with_kwargs(stdin_open=True, tty=False)
        ) as container:
            prep_paths_cmd = (
                "cp /run/keys/ssh-key.pem /tmp/ssh-key.pem && "
                "cp /run/keys/known_hosts /tmp/known_hosts && "
                "chown 0:0 /tmp/ssh-key.pem /tmp/known_hosts && "
                "chmod 600 /tmp/ssh-key.pem && "
                "chmod 644 /tmp/known_hosts"
            )
            prep_result = container.get_wrapped_container().exec_run(
                ["/bin/sh", "-lc", prep_paths_cmd]
            )
            prep_output = (
                prep_result.output.decode("utf-8", errors="replace")
                if isinstance(prep_result.output, (bytes, bytearray))
                else str(prep_result.output)
            )
            assert prep_result.exit_code == 0, (
                f"Failed to prepare SSH files in container. Exit code: {prep_result.exit_code}. "
                f"Output: {prep_output}"
            )

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

            #Check APX Recipe Run Tool Test
            apx_request = json.loads(json.dumps(constants.CHECK_APX_RECIPE_RUN_REQUEST))
            apx_args = apx_request["params"]["arguments"]
            apx_args["remote_ip_addr"] = os.getenv("APX_TEST_REMOTE_IP", apx_args["remote_ip_addr"])
            apx_args["remote_usr"] = os.getenv("APX_TEST_REMOTE_USER", apx_args["remote_usr"])
            apx_args["cmd"] = os.getenv("APX_TEST_CMD", apx_args["cmd"])

            print("\n***APX Remote User:", apx_args["remote_usr"])
            print("\n***APX Remote IP:", apx_args["remote_ip_addr"])
            print("\n***APX Workload Cmd:", apx_args["cmd"])

            raw_socket.sendall(_encode_mcp_message(apx_request))
            check_apx_recipe_run_response = _read_response(8, timeout=60)
            apx_structured = check_apx_recipe_run_response.get("result", {}).get("structuredContent", {})
            print("\n***APX Recipe Run Tool Response Structured Content: ", json.dumps(apx_structured, indent=2))
            assert apx_structured.get("recipe") == "code_hotspots", "Test Failed: MCP apx_recipe_run tool failed: recipe mismatch. Expected: code_hotspots, Received: {}".format(apx_structured.get("recipe"))
            assert apx_structured.get("status") in {"success"}, "Test Failed: MCP apx_recipe_run tool failed: unexpected status. Received: {}".format(apx_structured.get("status"))
            print("\n***Test Passed: MCP apx_recipe_run tool call completed")
        
if __name__ == "__main__":
    pytest.main([__file__])
