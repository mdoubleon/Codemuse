# CodeMuse Known Limitations

这份清单用于避免把 MVP 边界误讲成完整产品能力。

## 当前限制

```text
Eval dataset        当前是 68-case deterministic baseline；live provider benchmark 仍需 API key。
Live models         OpenAI-compatible / Bailian 已实现；没有 API key 时只做 readiness/comparison，不发起 probe。
GitHub import       已支持显式批准后的本地 clone/import；自动远程同步和缓存治理仍有限。
Web UI              当前是 minimal static workbench，不是 React/Vite 级产品 UI。
MCP                 mock、stdio、http/streamable_http JSON-RPC 已接入；认证、重连和完整 SSE lifecycle 仍有限。
Skills              支持 descriptor discovery 和显式 run_skill；自动激活仍要补。
Extensions          当前有 manifest discovery，entrypoint/dynamic tools/hooks/resources 还要补。
SubAgent            支持 bounded plan、DAG handoff、并行研究和 Git worktree 元数据；自动 patch 应用、任务重试和 trace UI 仍有限。
Benchmark reports   当前有 latest、history index、trend、SVG chart、failure taxonomy；真实 provider cost/latency 仍待 live mode。
Repo/Git            已支持基础 cache、status/diff 和 imported repo indexing；完整分支治理仍有限。
```

## 判断标准

某项能力只有同时满足以下条件，才算完整：

```text
有用户入口
有安全边界
有测试或 baseline case
有 doctor/readiness 检查
有文档说明

```

## 已实现但仍有边界

```text
Memory/RAG          已支持本地 chunk、BM25、哈希向量、重排、索引刷新和 Runtime 上下文注入。
Repo/Git            已支持批准后的 import_repository、repo cache、status/diff 和导入仓库索引。
Web UI              已提供静态 workbench；复杂前端交互和实时流式渲染仍有限。
MCP                 mock、stdio、http/streamable_http JSON-RPC transport 已接入；认证、重连和更完整的 SSE 生命周期仍有限。
Extensions          manifest 动态工具可运行；任意 Python entrypoint 仍受安全边界限制。
SubAgent            bounded plan、DAG handoff、blackboard 和显式 orchestrate_agents 已可用；复杂自治编排仍有限。
Live models         源码已支持；release_ready 仍取决于用户提供 API key。
Runtime             已支持生命周期 Hook、steering/follow-up 队列、会话压缩、turn head 和统一流式事件；复杂暂停/恢复仍有限。
Session             已支持 active turn head 和按 head 分叉；完整 turn DAG 导航 UI 仍有限。
```


