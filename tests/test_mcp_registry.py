"""Behavioral checks for registry publication and recovery boundaries."""

import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mcp_registry", ROOT / ".github/scripts/mcp_registry.py"
)
registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registry)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "mcp-local/server.json").read_text())
        self.version = self.manifest["version"]
        self.record = {
            "server": copy.deepcopy(self.manifest),
            "_meta": {registry.OFFICIAL: {"status": "active"}},
        }
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "server.json"
        self.path.write_text(json.dumps(self.manifest))

    def test_rejects_arbitrary_version_or_image(self):
        for version in ("v3.0.0", "../main", "3.0.0; echo bad", "latest"):
            with self.assertRaises(ValueError):
                registry.version_value(version)
        self.manifest["packages"][0]["identifier"] = "docker.io/other/image:3.0.0"
        with self.assertRaises(ValueError):
            registry.validate_manifest(self.manifest, self.version)

    def test_rejects_draft_prerelease_and_withdrawn_releases(self):
        good = {
            "tag_name": "v3.0.0",
            "draft": False,
            "prerelease": False,
            "body": "",
            "name": "v3.0.0",
        }
        for mutation in (
            {"draft": True},
            {"prerelease": True},
            {"body": "<!-- arm-mcp-withdrawn -->"},
            {"name": "v3.0.0 — WITHDRAWN"},
        ):
            with patch.object(registry, "github", return_value=good | mutation):
                with self.assertRaises(ValueError):
                    registry.release("3.0.0")

    def test_retry_matching_publication_is_noop(self):
        with (
            patch.object(registry, "release"),
            patch.object(registry, "lookup", return_value=self.record),
            patch.object(registry.subprocess, "run") as publish,
        ):
            registry.publish(self.path)
            publish.assert_not_called()

    def test_retry_never_overwrites_conflict_or_reactivates(self):
        conflict = copy.deepcopy(self.record)
        conflict["server"]["packages"][0]["runtimeArguments"] = []
        deleted = copy.deepcopy(self.record)
        deleted["_meta"][registry.OFFICIAL]["status"] = "deleted"
        for record in (conflict, deleted):
            with (
                patch.object(registry, "release"),
                patch.object(registry, "lookup", return_value=record),
                patch.object(registry.subprocess, "run") as publish,
            ):
                with self.assertRaises(ValueError):
                    registry.publish(self.path)
                publish.assert_not_called()

    def test_new_publication_is_read_back_and_verified(self):
        with (
            patch.object(registry, "release"),
            patch.object(registry, "lookup", side_effect=[None, None, self.record]),
            patch.object(registry.subprocess, "run") as publish,
            patch.object(registry.time, "sleep"),
        ):
            registry.publish(self.path)
            publish.assert_called_once_with(
                ["mcp-publisher", "publish", str(self.path)], check=True
            )

    def test_withdrawal_does_not_create_missing_version(self):
        with (
            patch.object(registry, "lookup", return_value=None),
            patch.object(registry.subprocess, "run") as status,
        ):
            registry.withdraw(self.version)
            status.assert_not_called()

    def test_withdrawal_changes_only_requested_version(self):
        deleted = copy.deepcopy(self.record)
        deleted["_meta"][registry.OFFICIAL]["status"] = "deleted"
        with (
            patch.object(registry, "lookup", side_effect=[self.record, deleted]),
            patch.object(registry.subprocess, "run") as status,
        ):
            registry.withdraw(self.version)
            args = status.call_args.args[0]
            self.assertEqual(args[-2:], [registry.NAME, self.version])
            self.assertNotIn("--all-versions", args)
        with (
            patch.object(registry, "lookup", return_value=deleted),
            patch.object(registry.subprocess, "run") as status,
        ):
            registry.withdraw(self.version)
            status.assert_not_called()

    def test_lookup_does_not_treat_outage_as_missing(self):
        for code in (401, 403, 429, 500):
            with patch.object(
                registry,
                "urlopen",
                side_effect=HTTPError("url", code, "error", {}, None),
            ):
                with self.assertRaises(HTTPError):
                    registry.lookup(self.version)

    def test_prepare_rejects_unapproved_source(self):
        sha = "a" * 40
        with (
            patch.object(registry, "release", return_value={}),
            patch.object(registry, "github", return_value={"sha": sha}),
        ):
            with self.assertRaisesRegex(ValueError, "authorized source"):
                registry.prepare(self.version, "b" * 40, self.path)
        with (
            patch.object(registry, "release", return_value={}),
            patch.object(
                registry, "github", side_effect=[{"sha": sha}, {"status": "diverged"}]
            ),
        ):
            with self.assertRaisesRegex(ValueError, "ancestor"):
                registry.prepare(self.version, "", self.path)

    def test_prepare_requires_matching_digest_and_verified_provenance(self):
        sha = "a" * 40
        digest = "sha256:" + "b" * 64
        manifest_path = Path(self.temp.name) / "verified" / "server.json"
        source_responses = [
            {"sha": sha},
            {"status": "ahead"},
            {"content": base64.b64encode(json.dumps(self.manifest).encode()).decode()},
        ]
        for image_digest, verification_error in (
            ("sha256:" + "c" * 64, None),
            (digest, subprocess.CalledProcessError(1, "gh attestation verify")),
            (digest, None),
        ):
            outputs = [
                json.dumps({"digest": image_digest}),
                verification_error or "verified",
            ]
            with (
                patch.object(
                    registry,
                    "release",
                    return_value={"body": f"Immutable digest: `{digest}`"},
                ),
                patch.object(registry, "github", side_effect=source_responses),
                patch.object(registry, "run", side_effect=outputs) as run,
            ):
                if image_digest != digest or verification_error:
                    with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                        registry.prepare(self.version, sha, manifest_path)
                    self.assertFalse(manifest_path.exists())
                else:
                    registry.prepare(self.version, sha, manifest_path)
                    self.assertEqual(
                        json.loads(manifest_path.read_text()), self.manifest
                    )
                    self.assertIn(
                        f"oci://{registry.IMAGE}@{digest}", run.call_args.args
                    )
                    self.assertIn(sha, run.call_args.args)
                    self.assertIn("--bundle-from-oci", run.call_args.args)


if __name__ == "__main__":
    unittest.main()
