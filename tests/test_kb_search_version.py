import sys
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / ".github/scripts"))

from check_kb_search_version import project_version, validate_version_change


class PackageVersionPolicyTests(unittest.TestCase):
    def test_package_inputs_require_a_version_increase(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\(0\.2\.0 -> 0\.2\.0\)"):
            validate_version_change(
                ["arm_kb_search/search.py"], (0, 2, 0), (0, 2, 0)
            )

    def test_invalid_project_metadata_has_a_clear_error(self) -> None:
        cases = (
            ("not valid = [", "invalid pyproject.toml"),
            ('[project]\nname = "arm-kb-search"\n', r"\[project\]\.version"),
        )
        for project_text, error in cases:
            with self.subTest(project_text=project_text), self.assertRaisesRegex(
                ValueError, error
            ):
                project_version(project_text)

    def test_application_changes_do_not_bump_package_version(self) -> None:
        self.assertEqual(
            validate_version_change(
                ["mcp-local/server.py", "embedding-generation/generate-chunks.py"],
                (0, 2, 0),
                (0, 2, 0),
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
