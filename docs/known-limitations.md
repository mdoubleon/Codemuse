# CodeMuse Known Limitations

这份清单用于避免把 MVP 边界误讲成完整产品能力。

## 当前限制

```text
Eval dataset        当前是 60-case deterministic baseline，还不是 100-case 或 live benchmark。
Live models         OpenAI-compatible / Bailian 已实现；没有 API key 时只做 readiness/comparison，不发起 probe。
GitHub import       当前只生成 import plan，不执行真实 clone。
Web UI              当前是 minimal static workbench，不是 React/Vite 级产品 UI。
MCP                 当前有 MVP/catalog 能力，真实 lifecycle/auth/error handling 还要补。
Skills              当前有 descriptor loader，自动激活和上下文注入还要补。
Extensions          当前有 manifest discovery，entrypoint/dynamic tools/hooks/resources 还要补。
SubAgent            当前是 bounded read-only MVP，尚无多 subagent 编排和 trace UI。
Benchmark reports   当前有 latest、history index、trend、SVG chart、failure taxonomy；真实 provider cost/latency 仍待 live mode。
Repo/Git            还缺 repo cache、Git metadata、branch/status/diff、imported repo indexing。
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

## Stage 36 Update

```text
Skills              Now have descriptor discovery plus run_skill runtime execution.
Extensions          Now have manifest discovery plus safe run_extension manifest execution.
Still limited       No arbitrary extension Python entrypoint execution yet; no dynamic hooks/resources yet.
Reason              The next jump needs sandboxing, approval surfaces, and UI controls, not just a loader.
```

## Stage 37 Update

```text
Memory/RAG          Implemented locally with chunking, hashed embeddings, BM25, reranking, index refresh, CLI/API search, and runtime context injection.
Repo/Git            Implemented locally with approved import_repository, repo cache, git status/diff, and imported repo indexing.
Web UI              Upgraded to a packaged workbench with memory, repo, report, approval, checkpoint, capability, session, and timeline panels.
MCP                 mcp_status now reports lifecycle/discovery/errors; mock transport is runnable. Real stdio/http still needs explicit safe transport support.
Extensions          Manifest-declared dynamic tools are runnable. Arbitrary Python entrypoint execution remains intentionally gated for safety.
SubAgent            run_subagent_plan now supports bounded multi-task orchestration and trace aggregation.
Live models         Source support is implemented; release_ready still depends on user-provided API keys.
```


