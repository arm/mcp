# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Check that CLI termination reaches child-process cleanup and restores signals."""

from __future__ import annotations

import io
import signal
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from agent_evals.cli import main


class CliTests(unittest.TestCase):
    def test_sigterm_uses_interrupt_path_and_restores_handler(self):
        original_handler = signal.getsignal(signal.SIGTERM)

        def request_termination(*_args, **_kwargs):
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler))
            handler(signal.SIGTERM, None)

        with patch("agent_evals.cli.load_scenario", return_value=object()), \
             patch("agent_evals.cli.run_scenario", side_effect=request_termination), \
             redirect_stderr(io.StringIO()) as stderr:
            exit_code = main(["run", "scenario.json", "--output", "output"])

        self.assertEqual(exit_code, 128 + signal.SIGTERM)
        self.assertIs(signal.getsignal(signal.SIGTERM), original_handler)
        self.assertIn("Run interrupted", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
