import os
from pathlib import Path

from utils.apx import (
    build_apx_ssh_mount_help,
    discover_run_keys_mounts,
    prepare_apx_ssh_paths,
    resolve_apx_ssh_mount_env,
)


def test_discover_run_keys_mounts_filters_and_decodes_targets(tmp_path: Path) -> None:
    mounts_path = tmp_path / "mounts"
    mounts_path.write_text(
        "\n".join(
            [
                "overlay / overlay rw 0 0",
                "/dev/sda1 /run/keys/id\\040rsa.pem ext4 ro 0 0",
                "/dev/sda2 /run/keys/known_hosts ext4 ro 0 0",
                "/dev/sda3 /workspace ext4 rw 0 0",
            ]
        ),
        encoding="utf-8",
    )

    assert discover_run_keys_mounts(mounts_path=mounts_path) == [
        "/run/keys/id rsa.pem",
        "/run/keys/known_hosts",
    ]


def test_resolve_apx_ssh_mount_env_populates_missing_env_vars(tmp_path: Path, monkeypatch) -> None:
    mounts_path = tmp_path / "mounts"
    mounts_path.write_text(
        "\n".join(
            [
                "/dev/sda1 /run/keys/team-prod.pem ext4 ro 0 0",
                "/dev/sda2 /run/keys/known_hosts ext4 ro 0 0",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("SSH_KEY_PATH", raising=False)
    monkeypatch.delenv("KNOWN_HOSTS_PATH", raising=False)
    monkeypatch.setattr("utils.apx.PROC_MOUNTS_PATH", mounts_path)

    resolved = resolve_apx_ssh_mount_env()

    assert resolved["key_path"] == "/run/keys/team-prod.pem"
    assert resolved["known_hosts_path"] == "/run/keys/known_hosts"
    assert os.environ["SSH_KEY_PATH"] == "/run/keys/team-prod.pem"
    assert os.environ["KNOWN_HOSTS_PATH"] == "/run/keys/known_hosts"


def test_resolve_apx_ssh_mount_env_preserves_existing_env_vars(tmp_path: Path, monkeypatch) -> None:
    mounts_path = tmp_path / "mounts"
    mounts_path.write_text(
        "\n".join(
            [
                "/dev/sda1 /run/keys/auto-key.pem ext4 ro 0 0",
                "/dev/sda2 /run/keys/known_hosts ext4 ro 0 0",
            ]
        ),
        encoding="utf-8",
    )

    custom_key = tmp_path / "custom-key.pem"
    custom_known_hosts = tmp_path / "custom-known_hosts"
    custom_key.write_text("private-key", encoding="utf-8")
    custom_known_hosts.write_text("host-key", encoding="utf-8")
    os.chmod(custom_key, 0o600)
    os.chmod(custom_known_hosts, 0o644)

    monkeypatch.setenv("SSH_KEY_PATH", str(custom_key))
    monkeypatch.setenv("KNOWN_HOSTS_PATH", str(custom_known_hosts))
    monkeypatch.setattr("utils.apx.PROC_MOUNTS_PATH", mounts_path)

    resolved = resolve_apx_ssh_mount_env()

    assert resolved["key_path"] == str(custom_key)
    assert resolved["known_hosts_path"] == str(custom_known_hosts)
    assert resolved["mount_targets"] == []
    assert resolved["key_reason"] is None
    assert resolved["known_hosts_reason"] is None


def test_prepare_apx_ssh_paths_stages_key_with_wrong_mode(tmp_path: Path) -> None:
    key_path = tmp_path / "ssh-key.pem"
    known_hosts_path = tmp_path / "known_hosts"
    runtime_keys_dir = tmp_path / "runtime-keys"

    key_path.write_text("private-key", encoding="utf-8")
    known_hosts_path.write_text("host-key", encoding="utf-8")
    os.chmod(key_path, 0o644)
    os.chmod(known_hosts_path, 0o644)

    prepared = prepare_apx_ssh_paths(
        key_path=str(key_path),
        known_hosts_path=str(known_hosts_path),
        runtime_keys_dir=runtime_keys_dir,
    )

    assert prepared["key_path"] == str(runtime_keys_dir / "ssh-key.pem")
    assert prepared["known_hosts_path"] == str(runtime_keys_dir / "known_hosts")
    assert oct((runtime_keys_dir / "ssh-key.pem").stat().st_mode & 0o777) == "0o600"
    assert oct((runtime_keys_dir / "known_hosts").stat().st_mode & 0o777) == "0o644"


def test_resolve_apx_ssh_mount_env_reports_multiple_key_like_mounts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mounts_path = tmp_path / "mounts"
    mounts_path.write_text(
        "\n".join(
            [
                "/dev/sda1 /run/keys/key-a.pem ext4 ro 0 0",
                "/dev/sda2 /run/keys/key-b.pem ext4 ro 0 0",
                "/dev/sda3 /run/keys/known_hosts ext4 ro 0 0",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("SSH_KEY_PATH", raising=False)
    monkeypatch.delenv("KNOWN_HOSTS_PATH", raising=False)
    monkeypatch.setattr("utils.apx.PROC_MOUNTS_PATH", mounts_path)

    resolved = resolve_apx_ssh_mount_env()

    assert resolved["key_path"] is None
    assert resolved["known_hosts_path"] == "/run/keys/known_hosts"
    assert "Multiple SSH key-like mount targets were found" in resolved["key_reason"]
    assert "/run/keys/key-a.pem" in resolved["key_reason"]
    assert "/run/keys/key-b.pem" in resolved["key_reason"]
    assert resolved["known_hosts_reason"] is None


def test_build_apx_ssh_mount_help_for_directory_mount(tmp_path: Path) -> None:
    run_keys_dir = tmp_path / "run-keys"
    run_keys_dir.mkdir()
    (run_keys_dir / "id_ed25519").write_text("private-key", encoding="utf-8")
    (run_keys_dir / "known_hosts").write_text("host-key", encoding="utf-8")

    help_text = build_apx_ssh_mount_help([str(run_keys_dir)], run_keys_dir=run_keys_dir)

    assert "Mount the SSH private key and known_hosts as individual files under /run/keys" in help_text["suggestion"]
    assert "No individual file mounts were discovered" in help_text["details"]
    assert str(run_keys_dir / "id_ed25519") in help_text["details"]
    assert str(run_keys_dir / "known_hosts") in help_text["details"]
    assert "-v /path/to/your/ssh/private_key:/run/keys/ssh-key.pem:ro" in help_text["details"]
    assert "-v /path/to/your/ssh/known_hosts:/run/keys/known_hosts:ro" in help_text["details"]
    assert "SSH_KEY_PATH" not in help_text["details"]
    assert "KNOWN_HOSTS_PATH" not in help_text["details"]


def test_build_apx_ssh_mount_help_for_missing_file_mounts() -> None:
    help_text = build_apx_ssh_mount_help(["/run/keys/ssh-key.pem"])

    assert "/run/keys/ssh-key.pem" in help_text["details"]
    assert "/run/keys/known_hosts" in help_text["details"]
    assert "SSH_KEY_PATH" not in help_text["details"]
    assert "KNOWN_HOSTS_PATH" not in help_text["details"]


def test_build_apx_ssh_mount_help_includes_resolution_reason() -> None:
    help_text = build_apx_ssh_mount_help(
        ["/run/keys/key-a.pem", "/run/keys/key-b.pem", "/run/keys/known_hosts"],
        key_reason=(
            "Multiple SSH key-like mount targets were found: "
            "['/run/keys/key-a.pem', '/run/keys/key-b.pem']."
        ),
    )

    assert "Resolution detail:" in help_text["details"]
    assert "Multiple SSH key-like mount targets were found" in help_text["details"]
