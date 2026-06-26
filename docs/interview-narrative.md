# CodeMuse Interview Narrative

## 一句话

CodeMuse 是一个完整 Coding Agent 骨架，加上 Repo Blueprint Memory 的差异化能力。

## 项目亮点

```text
1. 统一 AgentRuntime + ToolRegistry，不把仓库分析做成孤立脚本。
2. 工具结果以 role="tool" 写回消息，保留 ReAct observation 闭环。
3. 写文件、shell、web fetch 都通过 policy / approval / effect preview 控制风险。
4. Repo Blueprint 把仓库结构经验沉淀为可检索记忆，并用于 project plan。
5. WebSessionManager、HTTP API、CLI、SDK 共用同一条 runtime 链路。
6. deterministic baseline eval 和 doctor strict gate 让能力完成度可验证。
```

## 可以怎么讲

```text
我不是只做了一个聊天壳，而是拆出了 runtime、tool、approval、storage、memory、server、eval 这些 coding agent 必需边界。
CodeMuse 的特色是 Repo Blueprint：它可以把仓库拆成结构化 blueprint，再把经验保存成 memory，在新项目规划时召回。
为了避免 demo 只能靠手动展示，我实现了 deterministic baseline 和 doctor strict gate，能自动检查核心能力是否退化。
```

## 当前诚实边界

```text
真实 live provider、60/100-case eval、Web 产品化、真实 clone/cache、MCP/Skill/Extension runtime 还在后续阶段。
当前已完成的是完整本地 deterministic coding-agent MVP 和可验证 release gate。
```

## Stage 37 Updated Boundary

```text
Live provider source support is implemented; only user API keys are environment-dependent.
The deterministic eval is now above the original 60-case gate and covers memory/RAG, repo/git, web data APIs, MCP status, dynamic extensions, and subagent plans.
Web productization now has a packaged workbench instead of only a minimal chat shell.
Repo/Git now has approved local import, repo cache metadata, status/diff, and imported repo indexing.
MCP/Skill/Extension runtime now has mcp_status, run_skill, run_extension, and manifest-declared dynamic extension tools.
The remaining boundaries are deliberate safety boundaries: real network clone, real MCP stdio/http transports, and arbitrary extension Python entrypoint execution require explicit approval/sandbox configuration.
```
