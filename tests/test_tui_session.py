from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codemuse.cli.main import main as cli_main
from codemuse.session import SessionClient
from codemuse.tui.controller import TuiController
from codemuse.tui.main import tui_main


class SessionClientTests(unittest.TestCase):
    def test_session_client_tracks_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch("codemuse.session.client.sdk.create_runtime") as create, patch("codemuse.session.client.sdk.run", return_value={"session_id": "s2", "assistant": "done"}):
            create.return_value.session_id = "s1"
            client = SessionClient(Path(temp))
            self.assertEqual("s1", client.new())
            self.assertEqual("done", client.prompt("hello")["assistant"])
            self.assertEqual("s2", client.session_id)


class TuiTests(unittest.TestCase):
    def test_controller_commands_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch("codemuse.tui.controller.SessionClient") as client_type:
            client = client_type.return_value
            client.session_id = "s1"
            client.new.return_value = "s1"
            client.prompt.return_value = {"assistant": "answer"}
            client.sessions.return_value = [{"session_id": "s1", "updated_at": 1}]
            controller = TuiController(Path(temp))
            self.assertEqual("answer", controller.submit("hello"))
            self.assertIn("s1", controller.submit("/sessions"))
            self.assertIn("/rewind", controller.submit("/help"))
            controller.submit("/quit")
            self.assertTrue(controller.should_exit)

    def test_tui_loop_handles_command_errors(self) -> None:
        source = io.StringIO("/unknown\n/quit\n")
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, patch("codemuse.tui.main.TuiController") as controller_type:
            controller = controller_type.return_value
            controller.session_id = "s1"
            controller.should_exit = False
            def submit(value):
                if value.strip() == "/unknown":
                    raise ValueError("bad command")
                controller.should_exit = True
                return "closed"
            controller.submit.side_effect = submit
            self.assertEqual(0, tui_main(Path(temp), stdin=source, stdout=output))
        self.assertIn("error: bad command", output.getvalue())

    def test_cli_dispatches_rpc_and_tui(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch("codemuse.api.rpc_mode.run_stdio_rpc") as rpc:
            self.assertEqual(0, cli_main(["rpc", "--workspace", temp]))
            rpc.assert_called_once()
        with tempfile.TemporaryDirectory() as temp, patch("codemuse.tui.tui_main", return_value=0) as tui:
            self.assertEqual(0, cli_main(["tui", "--workspace", temp, "--session", "s1"]))
            tui.assert_called_once()


if __name__ == "__main__":
    unittest.main()
