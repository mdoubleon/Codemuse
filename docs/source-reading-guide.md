# CodeMuse 源码阅读导览

这份文档的目标不是替代源码，而是帮你第一次通读时知道每个文件“在系统里干什么”。建议你按“推荐阅读顺序”先读主链路，再按目录补细节。

## 推荐阅读顺序

```text
scripts/run_agent.py
-> src/codemuse/cli/main.py
-> src/codemuse/api/sdk.py
-> src/codemuse/app/bootstrap.py
-> src/codemuse/runtime/runtime.py
-> src/codemuse/tools/registry.py
-> src/codemuse/tools/base.py
-> src/codemuse/tools/policy.py
-> src/codemuse/tools/effects.py
-> src/codemuse/storage/*
-> src/codemuse/memory/retrieval_hook.py
-> src/codemuse/server/http.py
-> src/codemuse/web/static/app.js
```

先把这条链路读顺，你就能讲清楚 CodeMuse 的核心：入口如何创建 Runtime，Runtime 如何调用模型和工具，工具如何审批，结果如何存储和展示。

## 主链路总览

```text
CLI / SDK / Web
-> build_agent(...)
-> AgentRuntime
-> LLMProvider.complete(...)
-> ToolRegistry.specs() / execute(...)
-> ToolPolicyEvaluator
-> ApprovalStore / CheckpointStore
-> SessionStore / TimelineStore
-> MemoryContextProvider
```

核心思想是：模型只提出文本和工具调用，真正能不能执行由 Runtime、ToolRegistry、Policy 和 Approval Gate 决定。

## scripts

- `scripts/run_agent.py`：CLI 启动脚本，把命令行参数交给 `codemuse.cli.main`。
- `scripts/run_server.py`：Web 服务启动脚本，启动本地 HTTP API 和静态前端。
- `scripts/run_eval.py`：评测入口，运行 deterministic baseline，并生成报告。

## src/codemuse/api

- `api/__init__.py`：导出 SDK 的公共函数，方便外部 import。
- `api/sdk.py`：对外稳定 Python API。CLI、Web 和外部 Python 调用基本都通过这里进入 Runtime；包含 `run`、`approve`、`reject`、`rewind`、`list_sessions`、`search_memory` 等。

阅读重点：这是“外部世界调用 CodeMuse”的边界。你现在打开的 `sdk.py` 可以当作源码阅读起点。

## src/codemuse/app

- `app/__init__.py`：导出应用装配入口。
- `app/bootstrap.py`：最重要的装配文件。读取配置，创建存储、模型 provider、工具注册表、memory provider，最后构造 `AgentRuntime`。
- `app/skills_runtime.py`：把 workspace 里的 skill 发现结果转换成 capability。
- `app/extensions_runtime.py`：把 extension manifest 转换成 capability。
- `app/resources.py`：应用层资源辅助逻辑，目前偏占位或通用边界。

阅读重点：`build_agent()` 和 `create_tool_registry()`。面试里讲系统装配就讲这里。

## src/codemuse/runtime

- `runtime/runtime.py`：Agent 主循环。负责接收用户输入、调用模型、处理工具调用、审批暂停、checkpoint、保存 session、发布 timeline event。
- `runtime/state.py`：Runtime 当前状态，包括 messages、turn_id、phase、pending tool calls。
- `runtime/events.py`：AgentEvent 结构，给 CLI/Web/timeline 观察运行过程。
- `runtime/git_checkpoint.py`：workspace 文件快照创建与恢复。
- `runtime/safe_rewind.py`：编排 checkpoint rewind，恢复会话和 workspace。
- `runtime/cancellation.py`：取消任务相关边界。
- `runtime/compaction.py`：上下文压缩相关边界，目前是后续增强点。
- `runtime/control_plane.py`：Runtime 控制面抽象，偏后续扩展。
- `runtime/emitter.py`：事件发布相关辅助边界。
- `runtime/hooks.py`：Runtime hook 扩展点。
- `runtime/lifecycle.py`：生命周期辅助边界。
- `runtime/session_host.py`：SessionHost 抽象边界，连接 session 和 runtime。
- `runtime/tool_surface.py`：工具暴露面的辅助抽象。
- `runtime/turn_loop.py`：turn loop 拆分方向的边界文件。
- `runtime/__init__.py`：导出 Runtime 相关公共类型。

阅读重点：先精读 `runtime.py`，其他 runtime 文件可以先扫一遍。当前真正主逻辑仍集中在 `AgentRuntime`。

## src/codemuse/tools

- `tools/base.py`：工具基类、`ToolResult.as_chat_message()`、workspace 路径保护。
- `tools/registry.py`：工具注册表。负责注册工具、暴露 specs、按工具名执行。
- `tools/policy.py`：工具安全策略，根据 `ToolSpec` 判断 allow / ask / deny。
- `tools/effects.py`：副作用预览核心。生成写文件 diff、patch preview、shell 风险、web fetch preview，并做 digest/stale 校验。
- `tools/file_tools.py`：基础代码工具：列文件、读文件、搜索、写文件、替换、patch。
- `tools/shell_tool.py`：受审批保护的 shell 命令执行工具。
- `tools/repo_tools.py`：把仓库索引、蓝图分析、蓝图记忆暴露成 Agent 工具。
- `tools/repo_index.py`：扫描仓库，提取文件树、语言、入口、配置、测试等线索。
- `tools/repo_analysis.py`：把 RepoIndex 推断成 RepoBlueprint。
- `tools/repo_import.py`：把本地/GitHub 仓库来源规范成 import plan。
- `tools/repo_git.py`：安全本地 repo import、cache metadata、git status/diff 辅助。
- `tools/project_plan.py`：从 RepoBlueprint 生成项目计划。
- `tools/skill_tool.py`：把 discovered skill 暴露成 runtime tool。
- `tools/extension_tool.py`：把 discovered extension 暴露成 runtime tool。
- `tools/subagent_tool.py`：把 bounded subagent 执行暴露成普通工具。
- `tools/search_tool.py`：搜索工具相关边界。
- `tools/session_tools.py`：session 相关工具边界。
- `tools/metadata.py`：工具元数据辅助结构。
- `tools/legacy_hints_readiness.py`：兼容/ready hint 辅助文件。
- `tools/__init__.py`：导出工具模块公共入口。

阅读重点：先读 `base.py -> registry.py -> policy.py -> effects.py -> file_tools.py -> shell_tool.py`。这几份能讲清楚工具系统和 approval。

## src/codemuse/domain

- `domain/messages.py`：对话消息结构，包含 role、文本片段、tool call、序列化。
- `domain/tools.py`：工具协议数据结构：`ToolSpec`、`ToolCall`、`ToolResult`。
- `domain/checkpoints.py`：checkpoint record 数据结构。
- `domain/blueprint.py`：RepoIndex、RepoBlueprint、BlueprintMemoryItem 等仓库蓝图模型。
- `domain/repo_import.py`：仓库导入计划的数据模型。
- `domain/project_plan.py`：项目计划的数据模型。
- `domain/session.py`：session 领域边界。
- `domain/_legacy_types_impl.py`：旧类型兼容实现。
- `domain/__init__.py`：导出常用领域模型。

阅读重点：这是“系统里流动的数据长什么样”。读 Runtime 卡住时回来看 domain。

## src/codemuse/storage

- `storage/sessions.py`：把 session messages 和 system prompt 保存成 JSON。
- `storage/approvals.py`：保存 pending approval，支持 approve/reject/invalid/stale 状态。
- `storage/checkpoints.py`：保存 checkpoint record，并按 checkpoint_id 加载。
- `storage/timeline.py`：把 AgentEvent 追加到 JSONL，方便回看运行过程。
- `storage/settings.py`：本地设置存储边界。
- `storage/files.py`：文件存储辅助边界。
- `storage/migrations.py`：存储迁移边界。
- `storage/models.py`：存储模型辅助边界。
- `storage/__init__.py`：导出 storage 公共入口。

阅读重点：CodeMuse 是本地项目，很多状态都写在 `.data/codemuse`。读 storage 能理解 session、approval、checkpoint 怎么落盘。

## src/codemuse/llm

- `llm/models.py`：模型返回结构，统一成文本和 tool calls。
- `llm/fake.py`：确定性 FakeLLM，用规则模拟回复和工具调用，方便测试和 demo。
- `llm/registry.py`：根据配置创建 provider，并提供 provider readiness。
- `llm/usage.py`：usage/cost 相关辅助边界。
- `llm/provider/base.py`：LLMProvider 协议和 provider info。
- `llm/provider/openai_compatible.py`：OpenAI-compatible provider。
- `llm/provider/bailian.py`：百炼/DashScope compatible provider。
- `llm/provider/__init__.py`：导出 provider 公共入口。
- `llm/__init__.py`：导出 llm 公共入口。

阅读重点：先读 `base.py` 和 `fake.py`。FakeLLM 能帮助你理解测试为什么稳定。

## src/codemuse/config

- `config/schema.py`：CodeMuse 配置结构，包括 model、runtime、capabilities。
- `config/manager.py`：合并默认配置、项目配置、运行时 override，产生 effective config。
- `config/patch.py`：配置合并、点路径设置、变更路径提取。
- `config/runtime_overrides.py`：进程内临时配置覆盖。
- `config/__init__.py`：导出配置入口。

阅读重点：读懂 `.codemuse/config.json` 如何影响 `build_agent()`。

## src/codemuse/memory

- `memory/retrieval_hook.py`：模型调用前注入记忆的入口。
- `memory/retrieval.py`：统一检索 project memory、blueprint memory、indexed files。
- `memory/recall_builder.py`：把检索结果构造成 recall snippet。
- `memory/file_memory_store.py`：用 JSON 保存项目记忆。
- `memory/file_memory_tools.py`：把 save/search project memory 暴露成工具。
- `memory/blueprint_memory.py`：保存和检索 RepoBlueprint memory。
- `memory/index_pipeline.py`：本地 memory/RAG 索引和检索总流程。
- `memory/indexer.py`：workspace 文件索引辅助。
- `memory/file_memory_chunker.py`：把文件切成可检索 chunk。
- `memory/file_memory_bm25.py`：本地 BM25 风格词法排名。
- `memory/file_memory_vector.py`：持久化本地向量索引。
- `memory/file_memory_search.py`：文件记忆检索辅助。
- `memory/embedding.py`：离线 deterministic embedding。
- `memory/reranker.py`：hybrid reranking。
- `memory/types.py`：memory 相关数据类型。
- `memory/auto_index.py`：自动索引边界。
- `memory/classification.py`：memory 分类边界。
- `memory/config.py`：memory 配置边界。
- `memory/chroma_telemetry.py`：Chroma telemetry 相关辅助。
- `memory/provider.py`：memory provider 抽象边界。
- `memory/sqlite_store.py`：SQLite store 边界。
- `memory/store.py`：通用 memory store 边界。
- `memory/vector_index.py`：向量索引边界。
- `memory/__init__.py`：导出 memory 公共入口。

阅读重点：先读 `retrieval_hook.py -> retrieval.py -> recall_builder.py -> file_memory_tools.py`。面试里讲 memory 就围绕“检索后构造 recall snippet 再注入上下文”。

## src/codemuse/mcp

- `mcp/config.py`：读取和解析 `mcp.json`。
- `mcp/descriptors.py`：MCP server/tool 描述结构。
- `mcp/session.py`：mock MCP client 和 session 管理，为真实 transport 预留位置。
- `mcp/manager.py`：统一管理 MCP 配置、工具发现和工具调用。
- `mcp/adapter.py`：把 MCP tool 适配成 CodeMuse BaseTool。
- `mcp/results.py`：MCP 调用结果结构。
- `mcp/__init__.py`：导出 MCP 公共入口。

阅读重点：MCP 没有绕过工具系统，而是被 adapter 转成普通工具，再走 Runtime/Policy。

## src/codemuse/subagents

- `subagents/specs.py`：SubAgentSpec、工具 allowlist、执行结果结构。
- `subagents/catalog.py`：管理可用子 Agent 规格。
- `subagents/manager.py`：创建受限 child runtime，用 allowlist 工具执行子任务。
- `subagents/__init__.py`：导出 subagent 公共入口。

阅读重点：重点看工具白名单。SubAgent 是能力扩展，不是绕过安全边界。

## src/codemuse/capabilities

- `capabilities/descriptor.py`：CapabilityDescriptor 数据结构。
- `capabilities/discovery.py`：从 ToolRegistry 等来源发现能力。
- `capabilities/catalog.py`：能力目录，支持 list/get。
- `capabilities/__init__.py`：导出 capability 公共入口。

阅读重点：Web/CLI 展示“当前 Agent 有哪些能力”时会走这里。

## src/codemuse/cli

- `cli/main.py`：命令行参数解析和命令分发，调用 SDK 完成实际操作。
- `cli/render.py`：把 SDK 返回的事件和 payload 格式化为 CLI 输出。
- `cli/__init__.py`：导出 CLI 入口。

阅读重点：CLI 自己不直接操作 Runtime，而是通过 SDK。这个边界很适合面试讲“复用同一条 runtime 链路”。

## src/codemuse/server

- `server/http.py`：标准库 HTTP API，路由请求到 WebSessionManager，并服务静态前端。
- `server/session_manager.py`：Web 场景下管理 session handle、任务队列、事件缓存。
- `server/routes/config.py`：配置相关 HTTP route 边界。
- `server/routes/capability_config.py`：能力配置相关 route 边界。
- `server/routes/__init__.py`：routes 导出入口。
- `server/__init__.py`：server 公共入口。

阅读重点：读 `http.py` 和 `session_manager.py`，理解 Web UI 怎么和 Runtime 对话。

## src/codemuse/web/static

- `web/static/index.html`：前端页面入口。
- `web/static/app.js`：Web workbench 主要交互逻辑，负责调用 API、展示 session、events、approval、memory、config 等。
- `web/static/styles.css`：Web UI 样式。
- `web/static/assets/*`：Logo 和工作状态图片资源。
- `web/static/__init__.py`：把静态资源作为 package assets。

阅读重点：前端不是独立应用，它通过 HTTP API 消费 Runtime 事件和 session 状态。

## src/codemuse/web_tools

- `web_tools/guarded_fetch.py`：受保护的网页获取，不执行 JavaScript，包含 URL/SSRF/大小限制等策略。
- `web_tools/tools.py`：把 guarded fetch 注册成 Agent 工具。
- `web_tools/__init__.py`：web tools 公共入口。

阅读重点：网络访问必须走 preview 和 approval，不能让模型随便请求外部地址。

## src/codemuse/benchmarks

- `benchmarks/models.py`：baseline eval 的数据模型。
- `benchmarks/baseline.py`：deterministic baseline case 和 runner。
- `benchmarks/report.py`：生成并保存 benchmark report。
- `benchmarks/live.py`：真实 provider readiness 和 probe benchmark。
- `benchmarks/__init__.py`：benchmark 公共入口。

阅读重点：它证明的是工程链路不退化，不是证明真实模型能力强。

## src/codemuse/diagnostics

- `diagnostics/readiness.py`：doctor/release readiness 检查。
- `diagnostics/__init__.py`：diagnostics 公共入口。

阅读重点：发布前检查入口，适合和 eval 一起看。

## src/codemuse/demo

- `demo/runner.py`：在临时 workspace 跑一条 deterministic demo 流程。
- `demo/__init__.py`：demo 公共入口。

阅读重点：如果你想快速演示项目能力，先看这里。

## src/codemuse/extensions

- `extensions/loader.py`：发现 extension manifest，但不直接 import 执行代码。
- `extensions/__init__.py`：extension 公共入口。

阅读重点：extension 目前偏 manifest 和能力发现，真实任意代码执行需要更强沙箱。

## src/codemuse/skills

- `skills/loader.py`：发现 workspace skills，不执行它们。
- `skills/__init__.py`：skill 公共入口。

阅读重点：skill 是能力描述和材料，不等同于直接执行代码。

## 其他包

- `src/codemuse/__init__.py`：包版本和公共入口。
- `browser/__init__.py`：浏览器自动化边界占位。
- `compat/__init__.py`：兼容层边界。
- `learning/__init__.py`：学习/长期沉淀边界。
- `prompts/__init__.py`：prompt 模板边界。
- `session/__init__.py`：session 配置边界。
- `tui/__init__.py`：TUI 边界。
- `web/__init__.py`：Web 包边界。

这些文件大多是边界或占位，第一遍可以快速扫过。

## tests 阅读导览

- `tests/test_api_sdk.py`：SDK 入口行为。
- `tests/test_cli_main.py`：CLI 参数和命令分发。
- `tests/test_server_api.py`：HTTP API 和 Web session。
- `tests/test_tool_registry.py`：工具注册和执行。
- `tests/test_approval_safety.py`：approval、digest、stale preview 安全。
- `tests/test_checkpoint_rewind.py`：checkpoint 和 rewind。
- `tests/test_memory_context.py`：memory recall 注入上下文。
- `tests/test_project_memory.py`：project memory 保存和检索。
- `tests/test_blueprint_memory.py`：Repo Blueprint memory。
- `tests/test_repo_import_plan.py`：repo import plan。
- `tests/test_mcp_integration.py`：MCP adapter/manager 集成。
- `tests/test_subagents.py`：SubAgent allowlist 和运行结果。
- `tests/test_web_fetch.py`：guarded web fetch。
- `tests/test_capabilities.py`：capability catalog。
- `tests/test_config_manager.py`：配置合并和 override。
- `tests/test_llm_provider.py`：provider registry/readiness。
- `tests/test_timeline.py`：timeline 事件记录。
- `tests/test_eval_baseline.py`：deterministic eval。
- `tests/test_demo.py`：demo flow。
- `tests/test_readiness.py`：doctor/readiness。

读测试的诀窍：先找和你刚读源码对应的测试。比如读完 `tools/effects.py` 就看 `test_approval_safety.py`。

## docs 阅读导览

- `docs/source-map.md`：主链路和模块地图，适合第一篇读。
- `docs/interview-qa.md`：面试 Q&A，适合背项目讲法。
- `docs/interview-narrative.md`：项目亮点和边界的短讲稿。
- `docs/safety.md`：安全、approval、权限边界说明。
- `docs/demo.md`：演示脚本。
- `docs/code-flowline.md`：代码流转说明。
- `docs/known-limitations.md`：当前限制。
- `docs/source-reading-guide.md`：当前这份源码导读。

## 两小时通读路线

### 第 1 阶段：入口到 Runtime，30 分钟

读：

```text
scripts/run_agent.py
src/codemuse/cli/main.py
src/codemuse/api/sdk.py
src/codemuse/app/bootstrap.py
```

你要能回答：用户从 CLI 进来后，谁创建 Runtime，谁保存 session。

### 第 2 阶段：Runtime 和工具，45 分钟

读：

```text
src/codemuse/runtime/runtime.py
src/codemuse/tools/base.py
src/codemuse/tools/registry.py
src/codemuse/tools/policy.py
src/codemuse/tools/effects.py
src/codemuse/tools/file_tools.py
src/codemuse/tools/shell_tool.py
```

你要能回答：工具为什么不是模型想调就直接执行。

### 第 3 阶段：存储和安全恢复，20 分钟

读：

```text
src/codemuse/storage/approvals.py
src/codemuse/storage/checkpoints.py
src/codemuse/storage/sessions.py
src/codemuse/storage/timeline.py
src/codemuse/runtime/git_checkpoint.py
src/codemuse/runtime/safe_rewind.py
```

你要能回答：approval、checkpoint、rewind 分别解决什么问题。

### 第 4 阶段：Memory 和 Repo Blueprint，25 分钟

读：

```text
src/codemuse/memory/retrieval_hook.py
src/codemuse/memory/retrieval.py
src/codemuse/memory/recall_builder.py
src/codemuse/tools/repo_index.py
src/codemuse/tools/repo_analysis.py
src/codemuse/memory/blueprint_memory.py
```

你要能回答：memory 为什么要构造成 recall snippet 再进入上下文。

### 第 5 阶段：Web、MCP、SubAgent，20 分钟

读：

```text
src/codemuse/server/http.py
src/codemuse/server/session_manager.py
src/codemuse/web/static/app.js
src/codemuse/mcp/adapter.py
src/codemuse/mcp/manager.py
src/codemuse/subagents/manager.py
src/codemuse/tools/subagent_tool.py
```

你要能回答：Web、MCP、SubAgent 为什么还是复用 Runtime/ToolRegistry/Policy。

## 第一遍读完后的自测问题

1. CLI 调用 `run` 后，完整经过哪些文件？
2. `ToolSpec.model_callable` 和 `ToolPolicyDecision.action` 有什么区别？
3. 写文件 approval 的 `effect_preview` 里有哪些字段？
4. approval 为什么需要 `effect_digest`？
5. checkpoint 能回滚什么，不能回滚什么？
6. memory recall snippet 是在哪一步注入模型上下文的？
7. MCP tool 是怎么变成普通 CodeMuse tool 的？
8. SubAgent 为什么必须有 allowlist？
9. Web UI 如何拿到 Runtime 事件？
10. deterministic baseline 能证明什么，不能证明什么？

如果这 10 个问题你能不用源码回答出来，这个项目的第一遍源码就算读通了。
