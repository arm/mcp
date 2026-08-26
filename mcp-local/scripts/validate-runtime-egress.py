#!/usr/bin/env python3
"""Validate an immutable MCP image while outbound networking is disabled."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NETWORK_SYSCALL_RE = re.compile(r"\b(connect|sendto|sendmsg|sendmmsg)\(")
ADDRESS_RE = re.compile(
    r'(?:inet_addr\("([^"]+)"\)|inet_pton\([^,]+, "([^"]+)"\))'
)
PORT_RE = re.compile(r"sin6?_port=htons\((\d+)\)")
PID_RE = re.compile(r"^\s*(\d+)\s+")
SOCKET_RE = re.compile(
    r"\bsocket\(AF_INET6?,\s*(SOCK_STREAM|SOCK_DGRAM)[^)]*\)\s+=\s+(\d+)"
)
FD_RE = re.compile(r"\b(?:connect|sendto|sendmsg|sendmmsg)\((\d+),")

MCP_REQUESTS = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "runtime-egress-validator", "version": "1"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "knowledge_base_search",
            "arguments": {"query": "nginx performance tweaks"},
        },
    },
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "migrate_ease_scan",
            "arguments": {"scanner": "java"},
        },
    },
]

NEGATIVE_CONTROL = r"""
import json
import socket

checks = [
    ("dns", socket.SOCK_DGRAM, "203.0.113.1", 53),
    ("udp", socket.SOCK_DGRAM, "203.0.113.1", 9),
    ("tcp", socket.SOCK_STREAM, "203.0.113.1", 9),
    ("http", socket.SOCK_STREAM, "203.0.113.1", 80),
    ("https", socket.SOCK_STREAM, "203.0.113.1", 443),
]
results = []
for protocol, socket_type, address, port in checks:
    sock = socket.socket(socket.AF_INET, socket_type)
    sock.settimeout(2)
    try:
        sock.connect((address, port))
        if socket_type == socket.SOCK_DGRAM:
            sock.send(b"egress-negative-control")
        results.append({"protocol": protocol, "blocked": False})
    except OSError as exc:
        results.append({"protocol": protocol, "blocked": True, "error": str(exc)})
    finally:
        sock.close()
print(json.dumps(results))
if not all(result["blocked"] for result in results):
    raise SystemExit("negative-control egress was not blocked")
"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Runnable image reference")
    parser.add_argument("--digest", required=True, help="Digest emitted by the image build")
    parser.add_argument("--platform", required=True, choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--strace", type=Path, default=Path("/usr/bin/strace"))
    parser.add_argument("--strace-package-version", required=True)
    return parser.parse_args()


def _prepare_tracer(strace: Path, tracer_dir: Path) -> None:
    tracer_dir.mkdir(parents=True, exist_ok=False)
    library_dir = tracer_dir / "lib"
    library_dir.mkdir()
    shutil.copy2(strace, tracer_dir / "strace")
    dependencies = _run(["ldd", str(strace)])
    if dependencies.returncode != 0:
        raise SystemExit(f"could not inspect strace dependencies: {dependencies.stderr}")
    library_paths = set(re.findall(r"(?:=>\s+)?(/[^\s]+)", dependencies.stdout))
    for library_path in library_paths:
        source = Path(library_path)
        if source.is_file():
            shutil.copy2(source.resolve(), library_dir / source.name)


def _trace_command(
    args: argparse.Namespace, tracer_dir: Path, command: list[str]
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--platform",
        args.platform,
        "--security-opt",
        "seccomp=unconfined",
        "--cap-add",
        "SYS_PTRACE",
        "-i",
        "-e",
        "LD_LIBRARY_PATH=/validation/lib",
        "-v",
        f"{tracer_dir.resolve()}:/validation:ro",
        "-v",
        f"{args.workspace.resolve()}:/workspace:ro",
        "--entrypoint",
        "/validation/strace",
        args.image,
        "-f",
        "-qq",
        "-s",
        "256",
        "-e",
        "trace=network",
        *command,
    ]


def _run(
    command: list[str], *, input_text: str | None = None, timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _run_mcp(
    command: list[str], requests: list[dict[str, Any]]
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin and process.stdout and process.stderr
    stderr_lines: list[str] = []
    stderr_reader = threading.Thread(
        target=lambda: stderr_lines.extend(process.stderr.readlines()), daemon=True
    )
    stderr_reader.start()
    stdout_lines: list[str] = []
    try:
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            expected_id = request.get("id")
            if expected_id is None:
                continue
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                remaining = max(0, deadline - time.monotonic())
                readable, _, _ = select.select([process.stdout], [], [], remaining)
                if not readable:
                    raise TimeoutError(
                        f"timed out waiting for MCP response id={expected_id}"
                    )
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError(
                        f"MCP process exited before response id={expected_id}"
                    )
                stdout_lines.append(line)
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if response.get("id") == expected_id:
                    break
            else:
                raise TimeoutError(f"timed out waiting for MCP response id={expected_id}")
        process.stdin.close()
        return_code = process.wait(timeout=60)
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        stderr_reader.join(timeout=5)
    return subprocess.CompletedProcess(
        command,
        return_code,
        "".join(stdout_lines),
        "".join(stderr_lines),
    )


def _is_permitted_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_loopback or parsed.is_unspecified


def parse_trace(trace_path: Path) -> list[dict[str, Any]]:
    """Return non-local IPv4/IPv6 connection attempts from a strace log."""
    attempts: list[dict[str, Any]] = []
    socket_types: dict[tuple[str, str], str] = {}
    if not trace_path.is_file():
        return attempts
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        pid_match = PID_RE.match(line)
        pid = pid_match.group(1) if pid_match else "single"
        socket_match = SOCKET_RE.search(line)
        if socket_match:
            socket_types[(pid, socket_match.group(2))] = socket_match.group(1)
            continue
        syscall_match = NETWORK_SYSCALL_RE.search(line)
        if not syscall_match or "AF_INET" not in line:
            continue
        address_match = ADDRESS_RE.search(line)
        if not address_match:
            continue
        address = next(value for value in address_match.groups() if value)
        if _is_permitted_address(address):
            continue
        port_match = PORT_RE.search(line)
        port = int(port_match.group(1)) if port_match else None
        if port == 53:
            protocol = "dns"
        elif port == 80:
            protocol = "http"
        elif port == 443:
            protocol = "https"
        fd_match = FD_RE.search(line)
        socket_type = (
            socket_types.get((pid, fd_match.group(1))) if fd_match else None
        )
        if port not in {53, 80, 443} and socket_type == "SOCK_DGRAM":
            protocol = "udp"
        elif port not in {53, 80, 443}:
            protocol = "tcp" if socket_type == "SOCK_STREAM" else "unknown"
        attempts.append(
            {
                "line": line_number,
                "syscall": syscall_match.group(1),
                "destination": address,
                "port": port,
                "protocol": protocol,
                "result": line.rsplit("=", 1)[-1].strip() if "=" in line else "unknown",
            }
        )
    return attempts


def _responses(stdout: str) -> dict[int, dict[str, Any]]:
    responses: dict[int, dict[str, Any]] = {}
    for line in stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("id"), int):
            responses[payload["id"]] = payload
    return responses


def _structured(response: dict[str, Any]) -> Any:
    return response.get("result", {}).get("structuredContent")


def validate_mcp_responses(stdout: str, platform: str) -> list[str]:
    responses = _responses(stdout)
    failures: list[str] = []
    if "serverInfo" not in responses.get(1, {}).get("result", {}):
        failures.append("MCP initialization did not return serverInfo")
    knowledge = _structured(responses.get(2, {}))
    if not isinstance(knowledge, dict) or not knowledge.get("result"):
        failures.append("embedded knowledge-base search returned no results")
    migration = _structured(responses.get(3, {}))
    if not isinstance(migration, dict) or migration.get("status") != "success":
        failures.append("bundled migrate-ease Java scan did not succeed")
    if platform == "linux/arm64":
        mca = _structured(responses.get(5, {}))
        if not isinstance(mca, dict) or mca.get("status") != "ok":
            failures.append("bundled llvm-mca analysis did not succeed")
    return failures


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = _arguments()
    if not DIGEST_RE.fullmatch(args.digest):
        raise SystemExit(f"invalid immutable image digest: {args.digest}")
    if "@" in args.image and args.image.rsplit("@", 1)[1] != args.digest:
        raise SystemExit(
            f"image reference {args.image} does not select build digest {args.digest}"
        )
    if not args.strace.is_file():
        raise SystemExit(f"strace is unavailable at {args.strace}")
    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    tracer_dir = args.evidence_dir.parent / f"{args.evidence_dir.name}-tracer"
    _prepare_tracer(args.strace, tracer_dir)

    requests = list(MCP_REQUESTS)
    flows = [
        "initialize",
        "knowledge_base_search",
        "migrate_ease_scan",
    ]
    if args.platform == "linux/arm64":
        requests.append(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "mca",
                    "arguments": {"input_path": "/workspace/tests/sum_test.s"},
                },
            }
        )
        flows.append("mca")

    runtime_command = _trace_command(
        args, tracer_dir, ["python", "-u", "server.py"]
    )
    try:
        runtime = _run_mcp(runtime_command, requests)
    except Exception as exc:
        runtime = subprocess.CompletedProcess(
            runtime_command, 124, "", f"validator error: {exc}\n"
        )
    (args.evidence_dir / "runtime.stdout").write_text(runtime.stdout, encoding="utf-8")
    (args.evidence_dir / "runtime.stderr").write_text(runtime.stderr, encoding="utf-8")
    runtime_trace = args.evidence_dir / "runtime.strace"
    # strace writes to Docker's captured stderr. Only the host persists that
    # stream, so the image under test cannot truncate or replace its trace.
    runtime_trace.write_text(runtime.stderr, encoding="utf-8")
    runtime_trace_present = runtime_trace.is_file()
    runtime_attempts = parse_trace(runtime_trace)
    response_failures = validate_mcp_responses(runtime.stdout, args.platform)

    negative = _run(
        _trace_command(
            args,
            tracer_dir,
            ["python", "-c", NEGATIVE_CONTROL],
        )
    )
    (args.evidence_dir / "negative-control.stdout").write_text(
        negative.stdout, encoding="utf-8"
    )
    (args.evidence_dir / "negative-control.stderr").write_text(
        negative.stderr, encoding="utf-8"
    )
    negative_trace = args.evidence_dir / "negative-control.strace"
    negative_trace.write_text(negative.stderr, encoding="utf-8")
    negative_trace_present = negative_trace.is_file()
    negative_attempts = parse_trace(negative_trace)
    try:
        negative_results = json.loads(negative.stdout.strip())
    except json.JSONDecodeError:
        negative_results = []
    detected_ports = {attempt["port"] for attempt in negative_attempts}
    negative_ok = (
        negative.returncode == 0
        and negative_trace_present
        and len(negative_results) == 5
        and all(result.get("blocked") for result in negative_results)
        and {9, 53, 80, 443}.issubset(detected_ports)
    )

    passed = (
        runtime.returncode == 0
        and runtime_trace_present
        and not response_failures
        and not runtime_attempts
        and negative_ok
    )
    evidence = {
        "schema_version": 1,
        "image": args.image,
        "digest": args.digest,
        "platform": args.platform,
        "network_mode": "none",
        "tracer": {
            "package": "strace",
            "package_version": args.strace_package_version,
            "output_channel": "docker stderr captured and persisted by host",
        },
        "permitted_traffic": [
            "stdio MCP client traffic",
            "AF_UNIX",
            "IPv4/IPv6 loopback",
        ],
        "exercised_flows": flows,
        "runtime": {
            "exit_code": runtime.returncode,
            "trace_present": runtime_trace_present,
            "response_failures": response_failures,
            "outbound_attempts": runtime_attempts,
        },
        "negative_control": {
            "exit_code": negative.returncode,
            "trace_present": negative_trace_present,
            "blocked_results": negative_results,
            "detected_attempts": negative_attempts,
            "passed": negative_ok,
        },
        "passed": passed,
    }
    _write_json(args.evidence_dir / "runtime-egress-evidence.json", evidence)

    summary = [
        f"### Runtime egress validation — `{args.platform}`",
        "",
        f"- Image digest: `{args.digest}`",
        f"- Tracer package: `strace={args.strace_package_version}`",
        "- Trace custody: Docker stderr captured and persisted by the host",
        f"- Result: **{'PASS' if passed else 'FAIL'}**",
        f"- Representative flows: {', '.join(f'`{flow}`' for flow in flows)}",
        f"- Unapproved runtime attempts: **{len(runtime_attempts)}**",
        f"- Negative control detected and blocked: **{'yes' if negative_ok else 'no'}**",
        "- Evidence: `runtime-egress-evidence.json` plus raw syscall traces",
        "",
    ]
    if response_failures:
        summary.extend(["#### Representative-flow failures", ""])
        summary.extend(f"- {failure}" for failure in response_failures)
        summary.append("")
    if runtime_attempts:
        summary.extend(
            [
                "#### Unapproved outbound attempts",
                "",
                "| Protocol | Destination | Port | Syscall | Result |",
                "| --- | --- | ---: | --- | --- |",
            ]
        )
        for attempt in runtime_attempts:
            summary.append(
                "| {protocol} | `{destination}` | {port} | `{syscall}` | `{result}` |".format(
                    **attempt
                )
            )
        summary.append("")
    (args.evidence_dir / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary))
    if not passed:
        print(json.dumps(evidence, indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
