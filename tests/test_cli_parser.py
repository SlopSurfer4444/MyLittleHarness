from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mylittleharness.cli_parser import build_parser


class CliParserTests(unittest.TestCase):
    def test_top_level_help_keeps_primary_commands_visible(self) -> None:
        help_text = build_parser().format_help()
        normalized_help = " ".join(help_text.split())
        for command in ("init", "check", "repair", "detach"):
            self.assertIn(command, help_text)
        self.assertIn("mylittleharness approval-decision --help", normalized_help)
        self.assertIn("does not waive human authority", normalized_help)
        self.assertIn("approve lifecycle", normalized_help)
        self.assertIn("provider, credential, archive, Git, or release", normalized_help)
        for hidden_command in ("roadmap", "memory-hygiene", "suggest"):
            self.assertNotIn(hidden_command, help_text)

        parser = build_parser()
        subparser_action = next(action for action in parser._actions if hasattr(action, "_choices_actions"))
        choice_actions = {action.dest: action.help for action in subparser_action._choices_actions}
        self.assertNotIn("approval-decision", choice_actions)

    def test_hidden_suggest_command_still_parses_with_positive_limit(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["suggest", "--intent", "phase closeout", "--limit", "2"])
        self.assertEqual(args.command, "suggest")
        self.assertEqual(args.intent, "phase closeout")
        self.assertEqual(args.limit, 2)

        with self.assertRaises(SystemExit) as raised:
            parser.parse_args(["suggest", "--intent", "phase closeout", "--limit", "0"])
        self.assertEqual(raised.exception.code, 2)

    def test_adapter_target_defaults_to_read_projection(self) -> None:
        args = build_parser().parse_args(["adapter", "--inspect"])
        self.assertEqual(args.command, "adapter")
        self.assertEqual(args.target, "mcp-read-projection")


if __name__ == "__main__":
    unittest.main()
