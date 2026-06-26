# CodeMuse Source Map

本文档记录 CodeMuse 的主要代码路径和运行链路，方便开发者从入口一路追到 Runtime、工具、记忆、存储和 Web API。

## Main Runtime Path

```text
scripts/run_agent.py
-> codemuse.cli.main
-> codemuse.api.sdk.run / approve / rewind
-> codemuse.app.bootstrap.build_agent
-> codemuse.config.manager.ConfigManager
-> codemuse.mcp.manager.MCPManager
-> codemuse.mcp.adapter.MCPToolAdapter
-> codemuse.subagents.manager.SubAgentManager
-> codemuse.runtime.runtime.AgentRuntime
-> codemuse.memory.retrieval_hook.MemoryContextProvider
-> codemuse.memory.file_memory_store.FileMemoryStore
-> codemuse.llm.registry.create_llm_provider
-> codemuse.llm.provider.base.LLMProvider
-> codemuse.llm.fake.FakeLLM by default
-> codemuse.tools.registry.ToolRegistry
-> codemuse.tools.*
-> codemuse.tools.policy.ToolPolicyEvaluator
-> codemuse.storage.approvals.PendingApprovalStore
-> codemuse.storage.checkpoints.CheckpointStore
-> codemuse.storage.timeline.TimelineStore
-> codemuse.storage.sessions.SessionStore
```

## CLI Path

```text
scripts/run_agent.py
-> codemuse.cli.main.main(...)
-> legacy prompt mode or grouped commands
-> codemuse.api.sdk
-> AgentRuntime / stores / capability catalog / config manager
```

## Timeline Path

```text
Write:
AgentRuntime._emit(...)
-> AgentEvent
-> TimelineStore.append(...)
-> .data/codemuse/timeline/{session_id}.jsonl

Read:
CLI timeline show
-> codemuse.api.sdk.list_timeline(...)
-> TimelineStore.list(...)
-> persisted AgentEvent payloads
```

## Benchmark / Eval Path

```text
scripts/run_eval.py
-> codemuse.benchmarks.baseline.run_cli(...)
-> codemuse.benchmarks.baseline.run_baseline(...)
-> temporary workspace per baseline case
-> codemuse.api.sdk
-> CodeMuse Runtime / tools / approval / memory / capability catalog
-> codemuse.benchmarks.report.build_report(...)
-> evals/reports/latest.json
-> evals/reports/latest.md

CLI:
scripts/run_agent.py benchmark run
-> codemuse.cli.main._handle_benchmark(...)
-> codemuse.benchmarks.baseline.run_baseline(...)
```

## Capability Catalog Path

```text
codemuse.api.sdk.list_capabilities(...)
-> codemuse.app.bootstrap.create_capability_catalog(...)
-> codemuse.app.bootstrap.create_tool_registry(...)
-> codemuse.capabilities.discovery.ToolCapabilityDiscoveryProvider
-> codemuse.app.skills_runtime.SkillCapabilityDiscoveryProvider
-> codemuse.app.extensions_runtime.ExtensionCapabilityDiscoveryProvider
-> codemuse.capabilities.catalog.CapabilityCatalog
-> CapabilityDescriptor list
```

## Skill / Extension Discovery Path

```text
skills:
codemuse.app.skills_runtime.SkillRuntime
-> codemuse.skills.loader.skill_search_roots(...)
-> .codemuse/skills/**/SKILL.md
-> skills/**/SKILL.md
-> CapabilityDescriptor(kind="skill")

extensions:
codemuse.app.extensions_runtime.ExtensionRuntime
-> codemuse.extensions.loader.extension_search_roots(...)
-> .codemuse/extensions/**/EXTENSION.json
-> extensions/**/EXTENSION.json
-> CapabilityDescriptor(kind="extension", metadata.execution="not_loaded")
```

## SDK API Path

```text
Python caller or CLI
-> codemuse.api.sdk
-> create_runtime(...)
-> build_agent(...)
-> AgentRuntime
-> AgentEvent list
-> result payload
```

## Config Path

```text
.codemuse/config.json
-> codemuse.config.manager.ConfigManager
-> default config + project config + runtime overrides
-> codemuse.config.schema.CodeMuseConfig
-> codemuse.app.bootstrap.build_agent
-> AgentRuntime / ToolRegistry / MemoryContextProvider
```

## LLM Provider Path

```text
.codemuse/config.json model section
-> codemuse.config.schema.ModelConfig
-> codemuse.llm.registry.create_llm_provider(...)
-> fake / openai_compatible / bailian provider object
-> AgentRuntime.llm.complete(messages, tools)
```

Current MVP keeps `fake` as the only implemented provider. `openai_compatible` and `bailian` are declared provider slots, so future real network clients can be added inside `llm/` without changing the Runtime loop.

## Server API Path

```text
scripts/run_server.py
-> codemuse.server.http.run_server
-> CodeMuseRequestHandler
-> WebSessionManager
-> SessionHandle
-> session worker queue
-> AgentRuntime
-> AgentEvent list
-> GET /sessions/{session_id}/events
```

Stage 30 adds `/api/...` aliases and packaged static assets:

```text
GET /
-> codemuse.server.http.CodeMuseRequestHandler._send_static(...)
-> codemuse.web.static/index.html
-> app.js calls /api/health, /api/capabilities, /api/sessions
-> WebSessionManager
-> AgentRuntime
```

## Repo Import / Project Plan Path

```text
User asks for GitHub import
-> FakeLLM emits ToolCall(prepare_repo_import)
-> ToolRegistry.execute(...)
-> tools.repo_import.build_repo_import_plan(...)
-> RepoImportPlan

User asks for project plan
-> FakeLLM emits ToolCall(build_project_plan)
-> tools.repo_analysis.build_repo_blueprint(...)
-> tools.project_plan.build_project_plan_from_blueprint(...)
-> ProjectPlan
```

## Module Map

```text
src/codemuse/
  api/           SDK and external API boundary.
  app/           Bootstrap and system assembly.
  benchmarks/    Benchmark harness boundary.
  browser/       Browser automation boundary.
  capabilities/  Capability catalog and discovery.
  cli/           CLI commands.
  compat/        Compatibility helpers.
  config/        Runtime configuration.
  domain/        Shared message, session, tool, checkpoint, and blueprint models.
  extensions/    Extension loading boundary.
  learning/      Durable learning extraction.
  llm/           Model adapters and usage metadata.
  mcp/           MCP discovery, sessions, and tool adapters.
  memory/        Retrieval, memory stores, and blueprint memory persistence.
  prompts/       Prompt templates.
  runtime/       Agent loop, events, lifecycle, checkpoint and rewind.
  server/        HTTP/session backend.
  session/       Session configuration.
  skills/        Skill loading and materialization.
  storage/       Sessions, settings, approvals, checkpoints, timeline.
  subagents/     Bounded subagent orchestration.
  tools/         Tool specs, registry, file/repo/shell tools, repo analysis helpers, and policy.
  tui/           Terminal UI boundary.
  web/           Web backend helpers.
  web_tools/     Web fetch/search tools.
```

## Memory Hook Path

```text
AgentRuntime._messages_for_model()
-> MemoryContextProvider.transform_context(...)
-> BlueprintStore.search_memory(...)
-> FileMemoryStore + search_file_memory(...)
-> ChatMessage(role="system", metadata={"memory_recall": ...})
-> LLMProvider.complete(...)
```

## Project Memory Path

```text
Save:
ToolCall(save_project_memory)
-> ToolPolicyEvaluator asks approval
-> AgentRuntime._checkpoint_before_tool(...)
-> FileMemoryStore.add(...)
-> MemoryItem JSON file
-> ToolResult

Recall:
latest user message
-> MemoryContextProvider.transform_context(...)
-> search_file_memory(...)
-> build_memory_recall_text(...)
-> system memory recall message
```

## Approval Path

```text
AgentRuntime receives ToolCall
-> ToolRegistry.get_spec(...)
-> ToolPolicyEvaluator.evaluate(...)
-> allow: ToolRegistry.execute(...)
-> ask: tools.effects.build_tool_effect_preview(...)
-> ask: tools.effects.build_effect_digest(...)
-> ask: PendingApprovalStore.create(..., details={"effect_preview": ..., "effect_digest": ...})
-> approve: tools.effects.validate_effect_digest(...)
-> approve invalid: PendingApprovalStore.mark(..., "invalid")
-> approve: tools.effects.validate_tool_effect_preview(...)
-> approve stale: PendingApprovalStore.mark(..., "stale")
-> approve valid: ToolRegistry.execute(...)
-> reject: PendingApprovalStore.mark(..., "rejected")
```

## Safe Write File Path

```text
User asks to create or write a file
-> FakeLLM emits ToolCall(write_file)
-> AgentRuntime receives Tool call
-> ToolRegistry.get_spec("write_file")
-> ToolPolicyEvaluator sees write + requires_confirmation + side_effect
-> tools.effects.build_tool_effect_preview(...)
-> tools.effects.build_effect_digest(...)
-> PendingApprovalStore.create(..., details={"effect_preview": ..., "effect_digest": ...})
-> approval_required event shows path, character delta, and unified diff
-> user approve
-> tools.effects.validate_effect_digest(...)
-> if invalid: approval_invalid event and no disk write
-> tools.effects.validate_tool_effect_preview(...)
-> if stale: approval_stale event and no disk write
-> if valid: continue
-> AgentRuntime._checkpoint_before_tool(...)
-> CheckpointStore.create(...)
-> ToolRegistry.execute("write_file", ...)
-> WriteFileTool.execute(...)
-> ToolResult.as_chat_message()
-> SessionStore.save(...)
```

## Safe Apply Patch Path

```text
User asks to apply a unified diff patch
-> FakeLLM emits ToolCall(apply_patch)
-> AgentRuntime receives Tool call
-> ToolRegistry.get_spec("apply_patch")
-> ToolPolicyEvaluator sees write + requires_confirmation + side_effect
-> tools.effects.build_apply_patch_effect_preview(...)
-> tools.effects.build_effect_digest(...)
-> PendingApprovalStore.create(..., details={"effect_preview": ..., "effect_digest": ...})
-> approval_required event shows changed files and per-file diff
-> user approve
-> tools.effects.validate_effect_digest(...)
-> if invalid: approval_invalid event and no disk write
-> tools.effects.validate_tool_effect_preview(...)
-> if stale: approval_stale event and no disk write
-> if valid: continue
-> AgentRuntime._checkpoint_before_tool(...)
-> CheckpointStore.create(...)
-> ToolRegistry.execute("apply_patch", ...)
-> ApplyPatchTool.execute(...)
-> tools.effects.apply_unified_patch(...)
-> ToolResult.as_chat_message()
-> SessionStore.save(...)
```

## Safe Replace Text Path

```text
User asks to replace text in a file
-> FakeLLM emits ToolCall(replace_text)
-> AgentRuntime receives Tool call
-> ToolRegistry.get_spec("replace_text")
-> ToolPolicyEvaluator sees write + requires_confirmation + side_effect
-> tools.effects.build_replace_text_effect_preview(...)
-> tools.effects.build_effect_digest(...)
-> PendingApprovalStore.create(..., details={"effect_preview": ..., "effect_digest": ...})
-> approval_required event shows match count, replacement count, and unified diff
-> user approve
-> tools.effects.validate_effect_digest(...)
-> if invalid: approval_invalid event and no disk write
-> tools.effects.validate_tool_effect_preview(...)
-> if stale: approval_stale event and no disk write
-> if valid: continue
-> AgentRuntime._checkpoint_before_tool(...)
-> CheckpointStore.create(...)
-> ToolRegistry.execute("replace_text", ...)
-> ReplaceTextTool.execute(...)
-> tools.effects.replace_text_in_file(...)
-> ToolResult.as_chat_message()
-> SessionStore.save(...)
```

## Safe Shell Tool Path

```text
User asks to run a shell command
-> FakeLLM emits ToolCall(run_shell)
-> AgentRuntime receives Tool call
-> ToolRegistry.get_spec("run_shell")
-> ToolPolicyEvaluator sees shell + requires_confirmation + side_effect
-> tools.effects.build_shell_effect_preview(...)
-> tools.effects.classify_shell_command(...)
-> PendingApprovalStore.create(..., details={"effect_preview": ..., "effect_digest": ...})
-> approval_required event shows command, risk level, timeout, and output limit
-> user approve
-> tools.effects.validate_effect_digest(...)
-> if invalid: approval_invalid event and no command execution
-> tools.effects.validate_tool_effect_preview(...)
-> if blocked/stale: approval_stale event and no command execution
-> if valid: continue
-> AgentRuntime._checkpoint_before_tool(...)
-> CheckpointStore.create(...)
-> ToolRegistry.execute("run_shell", ...)
-> RunShellTool.execute(...)
-> subprocess.run(...)
-> ToolResult.as_chat_message()
-> SessionStore.save(...)
```

## Guarded Web Fetch Path

```text
User asks to fetch a URL
-> FakeLLM emits ToolCall(web_fetch)
-> AgentRuntime receives Tool call
-> ToolRegistry.get_spec("web_fetch")
-> ToolPolicyEvaluator sees network + requires_confirmation
-> tools.effects.build_web_fetch_effect_preview(...)
-> web_tools.guarded_fetch.build_fetch_preview(...)
-> approval_required event shows URL, host, timeout, byte/char limits, and SSRF policy
-> user approve
-> tools.effects.validate_effect_digest(...)
-> if invalid: approval_invalid event and no network request
-> tools.effects.validate_tool_effect_preview(...)
-> if blocked/stale: approval_stale event and no network request
-> if valid: continue
-> AgentRuntime._checkpoint_before_tool(...)
-> ToolRegistry.execute("web_fetch", ...)
-> WebFetchTool.execute(...)
-> GuardedFetcher.fetch(...)
-> readable text ToolResult
```

## Checkpoint / Rewind Path

```text
Manual checkpoint:
CLI --checkpoint
-> AgentRuntime.create_checkpoint(...)
-> CheckpointStore.create(...)
-> WorkspaceSnapshotManager.create_snapshot(...)
-> checkpoint_created event

Rewind:
CLI --rewind <checkpoint_id>
-> CheckpointStore.load(...)
-> AgentRuntime.rewind(...)
-> SafeRewindOrchestrator.rewind_workspace(...)
-> WorkspaceSnapshotManager.restore_snapshot(...)
-> SessionStore.save(...)

Risky tool execution:
ToolPolicyEvaluator allow/approve
-> AgentRuntime._checkpoint_before_tool(...)
-> WorkspaceSnapshotManager.create_snapshot(...)
-> ToolRegistry.execute(...)
```

## MCP Tool Path

```text
mcp.json / .codemuse/mcp.json
-> MCPManager.from_workspace(...)
-> MCPSessionManager.get_or_create(...)
-> MCPManager.discover_tools(...)
-> MCPToolAdapter
-> ToolRegistry.register_factory(...)
-> AgentRuntime receives ToolCall
-> ToolRegistry.execute(...)
-> MCPManager.call_mcp_tool(...)
-> MCPResult
-> ToolResult
```

## Subagent Path

```text
ToolCall(spawn_subagent)
-> ToolRegistry.execute(...)
-> SpawnSubAgentTool
-> SubAgentManager.run_sync(...)
-> restricted ToolRegistry from allowlist
-> child SessionRecord
-> child AgentRuntime
-> SubAgentRunResult
-> ToolResult to parent runtime
```

## Development Rule

新增能力前，先判断它属于哪一层：入口、应用装配、Runtime、工具、记忆、存储、Web API 或诊断系统。Repo Blueprint 不是单独的应用层，而是一组工具能力加一种可检索的记忆类型：

```text
domain/blueprint.py         data models
tools/repo_tools.py         agent-callable tools
tools/repo_index.py         repo fact collection helpers
tools/repo_analysis.py      repo summary helpers
memory/blueprint_memory.py  persistence and search
```
