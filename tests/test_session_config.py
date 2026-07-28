from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codemuse.api import sdk
from codemuse.app.bootstrap import build_agent
from codemuse.config.schema import ConfigValidationError
from codemuse.session import SessionConfigStore


class SessionConfigTests(unittest.TestCase):
    def test_session_override_is_persisted_and_applied_on_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = build_agent(root)
            session_id = runtime.session_id
            sdk.set_session_config_path(root, session_id, "runtime.max_turns", 3)
            sdk.set_session_config_path(root, session_id, "runtime.history_token_budget", 2048)

            restored = build_agent(root, session_id=session_id)

            self.assertEqual(3, restored.max_turns)
            self.assertEqual(2048, restored.history_token_budget)
            self.assertEqual(3, sdk.get_session_config(root, session_id)["runtime"]["max_turns"])

    def test_invalid_override_restores_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session_id = build_agent(root).session_id
            sdk.set_session_config_path(root, session_id, "runtime.max_turns", 4)
            with self.assertRaises(ConfigValidationError):
                sdk.set_session_config_path(root, session_id, "runtime.max_turns", 500)
            self.assertEqual(4, SessionConfigStore(root).load(session_id)["runtime"]["max_turns"])

    def test_clear_removes_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session_id = build_agent(root).session_id
            sdk.set_session_config_path(root, session_id, "runtime.max_turns", 4)
            self.assertEqual({}, sdk.clear_session_config(root, session_id))
            self.assertEqual({}, sdk.get_session_config(root, session_id))


if __name__ == "__main__":
    unittest.main()
