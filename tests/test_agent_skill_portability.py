from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPARSE_POINT_ATTRIBUTE = 0x0400
S1_PATCH_PATHS = (
    "AGENTS.md",
    ".agents/skills",
    ".codex/hooks.json",
    ".github/workflows/ci.yml",
    "docs/archive/agents/AGENTS.pre-slim-2026-07-28.md",
    "docs/dev-changes/2026-07-29-system-convergence-s1-governance-foundation",
    "scripts/check_agent_policy.py",
    "scripts/check_agents_policy.py",
    "scripts/check_feature_contracts.py",
    "scripts/verify_agent_archives.py",
    "scripts/validate_prd.py",
    "tests/test_agents_policy.py",
    "tests/test_agent_skill_portability.py",
    "tests/test_prd_validator_entrypoint.py",
    "tests/test_feature_contracts.py",
)


def routed_skill_names(root: Path) -> list[str]:
    text = (root / "AGENTS.md").read_text(encoding="utf-8")
    names = re.findall(
        r"\.agents[\\/]+skills[\\/]+([A-Za-z0-9][A-Za-z0-9._-]*)",
        text,
    )
    return sorted(set(names), key=str.casefold)


def is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & REPARSE_POINT_ATTRIBUTE)


class AgentSkillPortabilityTests(unittest.TestCase):
    def test_clean_clone_applies_staged_s1_assets_as_ordinary_tracked_files(self) -> None:
        expected_skills = routed_skill_names(ROOT)
        self.assertEqual(len(expected_skills), 18)

        with tempfile.TemporaryDirectory(prefix="omni-s1-clean-") as temp_dir:
            clone = Path(temp_dir) / "clone"
            clone_result = subprocess.run(
                ["git", "clone", "--quiet", "--no-local", str(ROOT), str(clone)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(clone_result.returncode, 0, clone_result.stderr)

            patch = subprocess.run(
                ["git", "diff", "--cached", "--binary", "--", *S1_PATCH_PATHS],
                cwd=ROOT,
                check=False,
                capture_output=True,
            )
            self.assertEqual(patch.returncode, 0, patch.stderr.decode("utf-8", errors="replace"))
            if patch.stdout:
                apply = subprocess.run(
                    ["git", "apply", "--index", "--whitespace=nowarn"],
                    cwd=clone,
                    input=patch.stdout,
                    check=False,
                    capture_output=True,
                )
                self.assertEqual(
                    apply.returncode,
                    0,
                    apply.stderr.decode("utf-8", errors="replace"),
                )

            for skill_name in expected_skills:
                self.assertTrue(
                    (clone / ".agents" / "skills" / skill_name / "SKILL.md").is_file(),
                    skill_name,
                )

            reparse_paths = [
                path.relative_to(clone).as_posix()
                for path in (clone / ".agents" / "skills").rglob("*")
                if is_reparse_point(path)
            ]
            self.assertEqual(reparse_paths, [])

            policy = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "scripts/check_agent_policy.py",
                    "--require-tracked",
                    "--reject-reparse-points",
                ],
                cwd=clone,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(policy.returncode, 0, policy.stdout + policy.stderr)

            validator = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "scripts/validate_prd.py",
                    "--help",
                ],
                cwd=clone,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(validator.returncode, 0, validator.stdout + validator.stderr)


if __name__ == "__main__":
    unittest.main()
