# CodeMuse 代码流线阅读图

这份文档按“用户输入之后代码怎么跑”的顺序读，不按文件夹字母顺序读。

## 1. 命令行入口

```text
scripts/run_agent.py
-> codemuse.cli.main.main(...)
```

`scripts/run_agent.py` 只是薄入口，真正的参数解析在 `src/codemuse/cli/main.py`。

CLI 有两种模式：

```text
旧模式：
python scripts/run_agent.py "list files"
-> _main_legacy(...)
-> sdk.run(...)

新命令模式：
python scripts/run_agent.py capabilities list
python scripts/run_agent.py models providers
-> _main_command(...)
-> _handle_xxx(...)
-> sdk.xxx(...)
```

你可以把 CLI 理解成“把用户命令翻译成 SDK 调用”的层。

## 2. SDK 稳定门面

```text
codemuse.api.sdk
-> create_runtime(...)
-> run / approve / reject / checkpoint / rewind / list_xxx
```

SDK 是外部调用 CodeMuse 的稳定门面。

它不直接实现 Agent 逻辑，而是：

```text
1. 调 build_agent(...) 创建 Runtime
2. 调 Runtime.prompt / approve / reject
3. 把 Runtime 返回的 AgentEvent 和状态包装成 dict
```

所以 CLI、测试、未来 Web 客户端都应该调用 SDK，而不是自己拼 Runtime。

## 3. Bootstrap 系统装配

```text
codemuse.app.bootstrap.build_agent(...)
```

这是系统组装中心。它负责把 Agent 运行需要的东西一次装齐：

```text
ConfigManager        读取 .codemuse/config.json 和 runtime override
SessionStore         创建或恢复会话
PendingApprovalStore 保存待审批工具调用
CheckpointStore      保存会话检查点
TimelineStore        保存运行事件
ToolRegistry         注册所有本地工具、MCP 工具、子 Agent 工具
MemoryContextProvider 模型调用前注入记忆
LLMProvider          根据 ModelConfig 创建模型 provider
AgentRuntime         最终被组装出来的运行主体
```

关键调用链：

```text
build_agent(...)
-> config_for_workspace(...)
-> create_tool_registry(...)
-> create_llm_provider(config.model)
-> AgentRuntime(...)
```

## 4. Runtime 主循环

```text
AgentRuntime.prompt(text)
-> ChatMessage(role="user")
-> _run_loop()
```

Runtime 是 Agent 的发动机，核心逻辑在 `src/codemuse/runtime/runtime.py`。

一轮主循环大概是：

```text
1. 保存用户消息
2. _messages_for_model() 构造模型上下文
3. memory_provider.transform_context(...) 注入记忆
4. llm.complete(messages, tool_specs) 调模型
5. 如果模型直接回答：保存 assistant message，结束
6. 如果模型返回 ToolCall：进入工具执行流程
7. 工具结果变成 role="tool" 的 ChatMessage
8. 回到第 2 步，让模型看到工具结果后继续推理
9. 超过 max_turns 则停止，避免无限循环
```

Runtime 只负责调度，不负责具体工具怎么干，也不负责具体模型厂商怎么调用。

## 5. LLM Provider 路径

```text
.codemuse/config.json
-> ModelConfig
-> create_llm_provider(...)
-> LLMProvider.complete(...)
```

当前实现：

```text
fake                已实现，用于本地学习和测试
openai_compatible   预留 stub
bailian             预留 stub
```

`FakeLLM` 会根据用户输入用规则模拟模型行为，例如看到 `list files` 就生成 `ToolCall(name="list_files")`。

以后接真实模型时，主要改：

```text
src/codemuse/llm/provider/*
src/codemuse/llm/registry.py
```

不应该改 Runtime 主循环。

## 6. 工具调用路径

```text
LLMProvider 返回 ToolCall
-> AgentRuntime 根据 tool name 查 ToolRegistry
-> ToolPolicyEvaluator 判断 allow / ask / deny
-> ToolRegistry.execute(...)
-> BaseTool.execute(...)
-> ToolResult.as_chat_message()
-> Runtime 把 tool message 写回 messages
```

工具的共同接口：

```text
ToolSpec   给模型看的工具说明
ToolCall   模型发出的工具调用请求
ToolResult 工具执行后的观察结果
```

当前主要工具：

```text
tools/file_tools.py       list_files / read_file / search_text / write_file / apply_patch / replace_text
tools/shell_tool.py       run_shell
web_tools/tools.py        web_fetch
tools/repo_tools.py       index_repo_structure / analyze_repo_blueprint / save_blueprint_memory / search_blueprint_memory / prepare_repo_import / build_project_plan
memory/file_memory_tools.py save_project_memory / search_project_memory
tools/subagent_tool.py    spawn_subagent
mcp/adapter.py            MCP 工具适配成普通工具
```

## 7. 记忆注入路径

```text
AgentRuntime._messages_for_model()
-> MemoryContextProvider.transform_context(...)
-> BlueprintStore.search_memory(...)
-> FileMemoryStore + search_file_memory(...)
-> 生成 role="system" 的 memory recall message
-> LLMProvider.complete(...)
```

记忆不是直接替换用户输入，而是作为额外 system message 插入，让模型在回答或调用工具前看到历史经验。

当前有两类记忆：

```text
Blueprint memory：仓库最小架构总结
Project memory：通用项目学习记忆
```

## 8. 审批、检查点和时间线

当工具有副作用时，Runtime 会先经过安全策略：

```text
ToolCall
-> ToolPolicyEvaluator.evaluate(...)
-> allow: 直接执行
-> ask: build_tool_effect_preview(...) 生成审批前影响预览
-> ask: build_effect_digest(...) 绑定工具名、参数和预览
-> ask: PendingApprovalStore.create(...)
-> deny: 写入工具错误结果
```

以 `write_file`、`apply_patch`、`replace_text`、`run_shell` 和 `web_fetch` 为例：

```text
ToolCall(write_file / apply_patch / replace_text / run_shell / web_fetch)
-> ToolSpec(permission_domain="write" / "shell" / "network", requires_confirmation=True)
-> Runtime 创建 effect_preview，里面包含目标路径、字符变化和 unified diff
   -> write_file: 根据最终 content 生成单文件 diff
   -> apply_patch: 先在内存里应用 patch，再生成多文件 diff preview
   -> replace_text: 根据 old_text/new_text 生成单文件 diff，并记录匹配数量
   -> run_shell: 不执行命令，只生成风险等级、blocked 状态、超时和输出上限
   -> web_fetch: 不访问网页，只校验 URL 并展示网络访问风险和大小限制
-> Runtime 创建 effect_digest，绑定工具名、参数和 effect_preview
-> Runtime 创建 pending approval
-> 审批前文件不会写入磁盘
-> 用户 approve 后先校验 effect_digest 是否匹配
-> 如果审批单内容被篡改，发出 approval_invalid，不执行工具
-> digest 通过后再重新校验 effect_preview 是否过期
-> 如果目标文件已变更，发出 approval_stale，不执行工具
-> 如果预览 blocked，发出 approval_stale，不执行工具
-> 如果预览有效，先创建 checkpoint
-> ToolRegistry.execute(...)
-> WriteFileTool / ApplyPatchTool / ReplaceTextTool / RunShellTool / WebFetchTool 真正执行动作
```

审批恢复：

```text
CLI / SDK approve(approval_id)
-> PendingApprovalStore.load(...)
-> AgentRuntime.approve(...)
-> validate_effect_digest(...)
-> invalid: 标记 approval 为 invalid，写回 tool error，不执行工具
-> validate_tool_effect_preview(...)
-> stale: 标记 approval 为 stale，写回 tool error，不执行工具
-> valid: 创建 checkpoint 并执行原始 ToolCall
-> ToolResult 写回 messages
```

检查点：

```text
AgentRuntime.create_checkpoint(...)
AgentRuntime._checkpoint_before_tool(...)
-> CheckpointStore
-> WorkspaceSnapshotManager.create_snapshot(...)
```

回退：

```text
AgentRuntime.rewind(checkpoint_id)
-> CheckpointStore.load(...)
-> SafeRewindOrchestrator.rewind_workspace(...)
-> WorkspaceSnapshotManager.restore_snapshot(...)
-> 恢复 checkpoint.messages / turn_id
-> SessionStore.save(...)
```

时间线：

```text
AgentRuntime._emit(...)
-> AgentEvent
-> TimelineStore.append(...)
-> CLI timeline show / sdk.list_timeline(...)
```

Session 是给 Agent 恢复上下文用的，Timeline 是给用户/前端回看过程用的。

## 9. 子 Agent 路径

```text
ToolCall(spawn_subagent)
-> SpawnSubAgentTool
-> SubAgentManager.run_sync(...)
-> restricted ToolRegistry
-> child AgentRuntime
-> SubAgentRunResult
-> ToolResult 回到父 Runtime
```

子 Agent 和父 Agent 的区别是：

```text
父 Agent：拥有完整工具注册表
子 Agent：只能拿 allowlist 中的工具，避免越权和递归失控
```

模型创建也必须走同一个 `llm_factory`，这样未来可以统一配置模型。

## 10. Server 路径

```text
scripts/run_server.py
-> codemuse.server.http.run_server(...)
-> CodeMuseRequestHandler
-> WebSessionManager
-> SessionHandle
-> AgentRuntime
```

服务端现在是 MVP：

```text
HTTP JSON API
SessionHandle 队列
事件列表查询
审批/checkpoint/rewind 接口
```

后续可以升级成 FastAPI + SSE/WebSocket + 更完整前端 UI。

Stage 30 补了最小浏览器工作台：

```text
GET /
-> server/http.py serves codemuse.web.static/index.html
-> app.js calls /api/sessions and /api/sessions/{id}/events
-> WebSessionManager queues prompt/approve/checkpoint jobs
-> SessionHandle records AgentEvent payloads for polling
```

Stage 29 补了 repo import / project plan 路径：

```text
prepare_repo_import
-> tools/repo_import.py
-> RepoImportPlan, no network clone

build_project_plan
-> tools/repo_analysis.py
-> tools/project_plan.py
-> ProjectPlan tasks and verification steps
```

## 11. Skill / Extension 发现路径

Stage 27 以后，能力目录不再只来自工具注册表。
`create_capability_catalog(...)` 会组合多个 discovery provider：

```text
ToolCapabilityDiscoveryProvider      已注册工具
SkillCapabilityDiscoveryProvider     SKILL.md 描述文件
ExtensionCapabilityDiscoveryProvider EXTENSION.json/extension.json manifest
```

当前 skill/extension 只是元数据能力：

```text
skills/loader.py
-> 读取 .codemuse/skills 和 skills 下的 SKILL.md
-> 解析 name / description
-> 输出 CapabilityDescriptor(kind="skill")

extensions/loader.py
-> 读取 .codemuse/extensions 和 extensions 下的 EXTENSION.json
-> 解析 name / description / entrypoint / provides / version
-> 输出 CapabilityDescriptor(kind="extension", metadata.execution="not_loaded")
```

这里故意不执行 extension entrypoint，也不把 skill body 注入模型上下文。
执行扩展和技能注入属于后续 RuntimeHooks / extension registry 阶段。

## 12. Benchmark / Eval 路径

Stage 28 以后，CodeMuse 有一个确定性 baseline runner：

```text
python scripts/run_eval.py
或者
python scripts/run_agent.py benchmark run
```

运行路径：

```text
codemuse.benchmarks.baseline.run_baseline(...)
-> default_cases()
-> 为每个 case 创建临时 workspace
-> 通过 codemuse.api.sdk 调用 Runtime
-> 验证 tool_result / approval_required / approval_stale / checkpoint_rewound 等事件
-> codemuse.benchmarks.report.build_report(...)
-> evals/reports/latest.json
-> evals/reports/latest.md
```

这不是替代单元测试，而是跨层回归：

```text
FakeLLM
-> SDK
-> bootstrap
-> Runtime
-> ToolRegistry / Approval / Rewind / Memory / SubAgent / Web / Capability Catalog
-> report
```

## 13. 推荐阅读顺序

第一次完整看代码，建议按这个顺序：

```text
1. domain/messages.py
2. domain/tools.py
3. tools/base.py
4. tools/registry.py
5. tools/file_tools.py
6. llm/provider/base.py
7. llm/fake.py
8. runtime/runtime.py
9. storage/sessions.py
10. app/bootstrap.py
11. api/sdk.py
12. cli/main.py
13. memory/retrieval_hook.py
14. tools/repo_tools.py
15. mcp/adapter.py 和 mcp/manager.py
16. subagents/manager.py
17. server/session_manager.py 和 server/http.py
18. skills/loader.py 和 extensions/loader.py
19. benchmarks/baseline.py 和 benchmarks/report.py
```

记住一句话：

```text
CLI/Server 接收输入，SDK 提供门面，Bootstrap 组装系统，Runtime 调度循环，LLM 决定下一步，Tool 执行动作，Storage 保存状态，Memory 补充上下文。
```
