import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_agents_policy as policy  # noqa: E402
from check_agents_policy import (  # noqa: E402
    DEVELOPMENT_SKILL,
    MAX_AGENTS_BYTES,
    check_agents_policy,
    main,
)


class AgentsPolicyTests(unittest.TestCase):
    def make_repo(self, agents: str = "# Omni instructions\n") -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        (root / "AGENTS.md").write_text(agents, encoding="utf-8")
        development_skill = root / ".agents" / "skills" / DEVELOPMENT_SKILL
        development_skill.mkdir(parents=True)
        (development_skill / "SKILL.md").write_text(
            "---\n"
            f"name: {DEVELOPMENT_SKILL}\n"
            "description: Enforce contract-first development for connected Omni features.\n"
            "---\n\n"
            "# Development\n",
            encoding="utf-8",
        )
        return root

    def make_trackable_repo(self, agents: str = "# Omni instructions\n") -> Path:
        root = self.make_repo(agents)
        (root / ".codex").mkdir()
        (root / ".codex" / "hooks.json").write_text("{}\n", encoding="utf-8")
        scripts = root / "scripts"
        scripts.mkdir()
        for name in (
            "check_agent_policy.py",
            "check_agents_policy.py",
            "verify_agent_archives.py",
        ):
            (scripts / name).write_text("# tracked test asset\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        return root

    def test_valid_compact_agents_and_existing_skill_reference_pass(self):
        root = self.make_repo(
            "# Omni\nUse `.agents/skills/example/SKILL.md` when explicitly routed.\n"
        )
        skill = root / ".agents" / "skills" / "example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")

        self.assertEqual(check_agents_policy(root), [])

    def test_limit_counts_utf8_bytes_not_characters(self):
        root = self.make_repo("你" * ((MAX_AGENTS_BYTES // 3) + 1))

        findings = check_agents_policy(root)

        self.assertIn("agents-too-large", {finding.code for finding in findings})

    def test_invalid_utf8_is_rejected(self):
        root = self.make_repo()
        (root / "AGENTS.md").write_bytes(b"\xff\xfe")

        findings = check_agents_policy(root)

        self.assertIn("invalid-utf8", {finding.code for finding in findings})

    def test_dynamic_tool_totals_are_rejected(self):
        samples = (
            "omni 暴露 **154 个 tool**。",
            "doctor should print `all 154 ok`.",
            "154 tools registered.",
            "MCP tools: 154",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                root = self.make_repo(f"# Omni\n{sample}\n")
                findings = check_agents_policy(root)
                self.assertTrue(
                    any(finding.code.startswith(("doctor-total", "tool-total")) for finding in findings),
                    findings,
                )

    def test_stable_numeric_tool_routing_statement_is_allowed(self):
        root = self.make_repo("# Omni\n1 个 tool 路由 6 类素材。\n")

        self.assertEqual(check_agents_policy(root), [])

    def test_missing_referenced_skill_is_rejected_for_slash_and_backslash(self):
        root = self.make_repo(
            "# Omni\n`.agents/skills/missing-one`\n"
            "`.agents\\skills\\missing-two\\SKILL.md`\n"
        )

        findings = check_agents_policy(root)
        missing = {
            finding.path
            for finding in findings
            if finding.code == "missing-skill-reference"
        }

        self.assertEqual(
            missing,
            {
                ".agents/skills/missing-one/SKILL.md",
                ".agents/skills/missing-two/SKILL.md",
            },
        )

    def test_development_skill_is_required_even_without_an_explicit_reference(self):
        root = self.make_repo()
        (root / ".agents" / "skills" / DEVELOPMENT_SKILL / "SKILL.md").unlink()

        findings = check_agents_policy(root)

        self.assertIn("missing-development-skill", {finding.code for finding in findings})

    def test_development_skill_rejects_todo_and_tbd(self):
        for marker in ("TODO", "TBD"):
            with self.subTest(marker=marker):
                root = self.make_repo()
                skill = root / ".agents" / "skills" / DEVELOPMENT_SKILL / "SKILL.md"
                skill.write_text(
                    "---\n"
                    f"name: {DEVELOPMENT_SKILL}\n"
                    "description: Enforce connected Omni feature development.\n"
                    "---\n\n"
                    f"- {marker}: finish this later\n",
                    encoding="utf-8",
                )

                findings = check_agents_policy(root)

                self.assertIn("development-skill-todo", {finding.code for finding in findings})

    def test_development_skill_rejects_placeholder_description(self):
        root = self.make_repo()
        skill = root / ".agents" / "skills" / DEVELOPMENT_SKILL / "SKILL.md"
        skill.write_text(
            "---\n"
            f"name: {DEVELOPMENT_SKILL}\n"
            "description: One sentence - what this skill does and when to invoke it.\n"
            "---\n\n"
            "# Development\n",
            encoding="utf-8",
        )

        findings = check_agents_policy(root)

        self.assertIn(
            "placeholder-development-skill-description",
            {finding.code for finding in findings},
        )

    def test_development_skill_requires_description_frontmatter(self):
        root = self.make_repo()
        skill = root / ".agents" / "skills" / DEVELOPMENT_SKILL / "SKILL.md"
        skill.write_text("# Development\n", encoding="utf-8")

        findings = check_agents_policy(root)

        self.assertIn(
            "missing-development-skill-description",
            {finding.code for finding in findings},
        )

    def test_agents_override_is_also_checked(self):
        root = self.make_repo()
        (root / "AGENTS.override.md").write_text("all 7 ok\n", encoding="utf-8")

        findings = check_agents_policy(root)

        self.assertTrue(
            any(
                finding.code == "doctor-total" and finding.path == "AGENTS.override.md"
                for finding in findings
            )
        )

    def test_hook_mode_warns_but_never_blocks(self):
        root = self.make_repo("omni 暴露 99 个工具。\n")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exit_code = main(["--root", str(root), "--hook"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertIs(payload["continue"], True)
        self.assertIn("blocking in CI", payload["systemMessage"])
        self.assertIn("scripts/check_agent_policy.py", payload["systemMessage"])

    def test_normal_mode_returns_nonzero_for_ci(self):
        root = self.make_repo("doctor: all 99 ok\n")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exit_code = main(["--root", str(root)])

        self.assertEqual(exit_code, 1)
        self.assertIn("FAIL", output.getvalue())

    def test_require_tracked_rejects_untracked_routed_skill_asset(self):
        root = self.make_trackable_repo(
            "# Omni\nUse `.agents/skills/example/SKILL.md` when explicitly routed.\n"
        )
        skill = root / ".agents" / "skills" / "example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")
        subprocess.run(
            [
                "git",
                "add",
                "AGENTS.md",
                ".codex/hooks.json",
                "scripts",
                ".agents/skills/omni-feature-development",
            ],
            cwd=root,
            check=True,
        )

        findings = check_agents_policy(root, require_tracked=True)

        self.assertIn(
            ".agents/skills/example/SKILL.md",
            {finding.path for finding in findings if finding.code == "untracked-governance-asset"},
        )

    def test_require_tracked_accepts_regular_indexed_routed_skill_assets(self):
        root = self.make_trackable_repo(
            "# Omni\nUse `.agents/skills/example/SKILL.md` when explicitly routed.\n"
        )
        skill = root / ".agents" / "skills" / "example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)

        self.assertEqual(check_agents_policy(root, require_tracked=True), [])

    def test_require_tracked_rejects_reparse_skill_root(self):
        root = self.make_trackable_repo(
            "# Omni\nUse `.agents/skills/example/SKILL.md` when explicitly routed.\n"
        )
        skill = root / ".agents" / "skills" / "example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        original = policy._is_reparse_point

        with mock.patch.object(
            policy,
            "_is_reparse_point",
            side_effect=lambda path: path == skill or original(path),
        ):
            findings = check_agents_policy(root, require_tracked=True)

        self.assertIn("reparse-skill-reference", {finding.code for finding in findings})

    def test_reparse_skill_root_is_rejected_even_before_tracking_check(self):
        root = self.make_repo(
            "# Omni\nUse `.agents/skills/example/SKILL.md` when explicitly routed.\n"
        )
        skill = root / ".agents" / "skills" / "example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")
        original = policy._is_reparse_point

        with mock.patch.object(
            policy,
            "_is_reparse_point",
            side_effect=lambda path: path == skill or original(path),
        ):
            findings = check_agents_policy(root, reject_reparse_points=True)

        self.assertIn("reparse-skill-reference", {finding.code for finding in findings})


class HooksConfigTests(unittest.TestCase):
    def test_documented_public_entrypoint_exists(self):
        self.assertTrue((ROOT / "scripts" / "check_agent_policy.py").is_file())

    def test_repo_hooks_cover_session_pretool_and_stop(self):
        config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))

        self.assertEqual(set(config["hooks"]), {"SessionStart", "PreToolUse", "Stop"})
        for event in ("SessionStart", "PreToolUse", "Stop"):
            handlers = config["hooks"][event][0]["hooks"]
            self.assertEqual(len(handlers), 1)
            self.assertIn("scripts/hooks/development_gate.py", handlers[0]["command"])
            self.assertIn("development_gate.py", handlers[0]["commandWindows"])
            self.assertIn(f"--event','{event}", handlers[0]["commandWindows"])

    def test_windows_hook_command_runs_from_a_repository_subdirectory(self):
        config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        command = config["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]

        result = subprocess.run(
            command,
            cwd=ROOT / "frontend",
            shell=True,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
