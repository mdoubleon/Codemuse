from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@unittest.skipUnless(shutil.which("node"), "Node.js is required for web frontend tests.")
class WebFrontendTests(unittest.TestCase):
    def test_chat_agent_mode_control_is_present(self) -> None:
        html = (ROOT / "src" / "codemuse" / "web" / "static" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "codemuse" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="api-tools-enabled"', html)
        self.assertIn('data-tools-enabled="false"', html)
        self.assertIn('data-tools-enabled="true"', html)
        self.assertIn(".mode-segmented", styles)

    def test_stream_deltas_render_as_one_assistant_message(self) -> None:
        source = (ROOT / "src" / "codemuse" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("boot().catch(showError);", source)
        source = source.replace("boot().catch(showError);", "", 1)
        source += r'''
const streamEvents = [
  { type: "message_delta", session_id: "session-1", turn_id: 3, delta: "你", timestamp: 1, event_id: 1 },
  { type: "message_delta", session_id: "session-1", turn_id: 3, delta: "好", timestamp: 2, event_id: 2 },
  { type: "message", session_id: "session-1", turn_id: 3, message: "你好", timestamp: 3, event_id: 3 }
];

function expect(condition, message) {
  if (!condition) throw new Error(message);
}

const compacted = compactAssistantStreamEvents(streamEvents);
expect(compacted.length === 1, "stream chunks must collapse to one terminal item");
expect(compacted[0].message === "你好", "final assistant message must replace the temporary stream text");
expect(conversationEvents(streamEvents).length === 1, "conversation must contain one assistant message");
expect(conversationEventKey(compacted[0]) === "assistant-stream:session-1:3", "one streamed response must keep a stable DOM key");
const interleaved = compactAssistantStreamEvents([
  { type: "message_delta", session_id: "session-1", turn_id: 5, delta: "A", event_id: 10 },
  { type: "tool_result", session_id: "session-1", turn_id: 5, tool_name: "list_files", event_id: 11 },
  { type: "message_delta", session_id: "session-1", turn_id: 5, delta: "B", event_id: 12 },
  { type: "message", session_id: "session-1", turn_id: 5, message: "AB", event_id: 13 }
]);
const interleavedMessage = conversationEvents(interleaved);
expect(interleavedMessage.length === 1 && interleavedMessage[0].message === "AB", "interleaved diagnostics must not create another stream bubble");
expect(conversationEventKey(interleavedMessage[0]) === "assistant-stream:session-1:5", "an interleaved stream must retain its DOM key");
const presentation = conversationPresentation(compacted[0]);
expect(presentation.kind === "assistant" && presentation.text === "你好", "streamed content must retain its assistant presentation");
const details = detailEvents([...streamEvents, { type: "tool_call", tool_name: "list_files" }]);
expect(details.length === 1 && details[0].type === "tool_call", "stream chunks must not appear in execution details");
expect(details.filter(event => event.type === "tool_call").length === 1, "only real tool_call events count as tool calls");
const meaningfulDetails = detailEvents([
  { type: "agent_start" },
  { type: "turn_start" },
  { type: "before_provider_request" },
  { type: "tool_call", tool_name: "list_files" },
  { type: "tool_result", tool_name: "list_files" },
  { type: "tool_calls_limited" }
]);
expect(meaningfulDetails.length === 3, "execution details must ignore lifecycle telemetry");
expect(meaningfulDetails.every(event => !["agent_start", "turn_start", "before_provider_request"].includes(event.type)), "lifecycle telemetry must not inflate execution details");
expect(!isAssistantEvent("prompt_completed"), "job completion is not an assistant message");
const restored = compactAssistantStreamEvents([
  { type: "message", session_id: "session-1", turn_id: 4, message: "first" },
  { type: "message", session_id: "session-1", turn_id: 4, message: "second" }
]);
expect(restored.length === 2, "separate completed messages must remain separate");

state.events = [];
state.eventIds.clear();
const appended = appendSessionEvents([
  { type: "tool_call", event_id: 20 },
  { type: "tool_call", event_id: 20 },
  { type: "tool_result", event_id: 21 }
]);
expect(appended === 2 && state.events.length === 2, "duplicate poll payloads must not inflate event counts");

(async () => {
  const chatButton = {
    dataset: { toolsEnabled: "false" },
    classList: { toggle() {} },
    setAttribute() {}
  };
  const agentButton = {
    dataset: { toolsEnabled: "true" },
    classList: { toggle() {} },
    setAttribute() {}
  };
  nodes.apiToolsEnabled = {
    dataset: {},
    querySelectorAll() { return [chatButton, agentButton]; }
  };
  nodes.apiKeyEnv = { value: "", focus() {} };
  nodes.apiTemperature = { value: "", focus() {} };
  nodes.apiMaxTokens = { value: "", focus() {} };
  nodes.apiProvider = { value: "fake" };
  nodes.apiModel = { value: "fake-local" };
  nodes.apiBaseUrl = { value: "" };
  state.busy = false;
  state.snapshot = null;
  state.config = { config: { runtime: { tools_enabled: true } } };
  setToolsEnabledControl(false);
  expect(toolsEnabledFromControl() === false, "Chat control must select tools_enabled=false");

  const requests = [];
  let createdSessions = 0;
  request = async (path, options = {}) => {
    requests.push({ path, options });
    return {};
  };
  refreshApiConfig = async () => {
    state.config = { config: { runtime: { tools_enabled: false } } };
  };
  renderApiConfig = () => {};
  createSession = async () => { createdSessions += 1; };
  showToast = () => {};

  await saveApiConfig();
  expect(requests.length === 2, "mode and model configuration must both be saved");
  expect(requests[0].path === "/api/config/set", "runtime mode must save before the model");
  expect(requests[0].options.body.path === "runtime.tools_enabled", "runtime mode must use the config path");
  expect(requests[0].options.body.value === false, "Chat must persist tools_enabled=false");
  expect(requests[1].path === "/api/models/select", "model save must follow runtime mode save");
  expect(createdSessions === 1, "switching modes must create a new session");
  expect(runtimeToolsEnabled() === false, "persisted runtime config must restore Chat mode");
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
'''
        with tempfile.TemporaryDirectory() as raw:
            script = Path(raw) / "web_stream_events_test.js"
            script.write_text(source, encoding="utf-8")
            result = subprocess.run(
                ["node", str(script)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(0, result.returncode, msg=result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
