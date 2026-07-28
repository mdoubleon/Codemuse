# CodeMuse Known Limitations

这份清单只记录当前真实边界，避免把已实现能力写成待办，也避免把受控实现描述成完整浏览器或自治团队。

## 已对齐的核心能力

```text
Runtime             流式 Provider、tool-call 累积、生命周期 Hook、steering/follow-up、压缩和取消。
Session             持久化、树形 fork、turn head、checkpoint、安全 rewind 和 session 级配置覆盖。
Machine API         Python SDK、HTTP API、版本化 JSON lines 和 stdio RPC。
Skills              分层发现、显式启用、描述匹配自动激活和 context 注入。
Extensions          manifest 发现、声明式动态工具、context hook 和 lifecycle hook。
MCP                 mock、stdio、HTTP/streamable HTTP JSON-RPC，tools/resources/prompts 发现与调用。
SubAgent            allowlist、DAG、blackboard、并行研究、重试、取消、worktree patch artifact 和审批应用。
Learning            安全启发式候选、JSONL 审核存储、approve/reject 和项目记忆提升。
Browser             SSRF 防护的静态导航、tab、snapshot、link ref、click 和缓存 history。
Web Search          静态 provider 搜索，支持 web/news/github 路由和审批预览。
UI                  静态 Web workbench、CLI 和无第三方依赖的交互 TUI。
Eval                deterministic baseline、history/trend 报告、demo 和 release-readiness doctor。
```

## 仍然存在的边界

```text
Live models         OpenAI-compatible（含自定义中转站）/ Bailian / DeepSeek 已实现；真实 probe 需要用户配置 API key。
Browser             不执行 JavaScript，不提供 CDP、表单输入、截图或真实 DOM 自动化。
Web Search          默认 DuckDuckGo 静态 HTML provider；news/github 模式是查询路由，不保证实时索引。
Extensions          不导入或执行任意 Python entrypoint；只运行 manifest 声明式能力。
MCP                 没有完整 OAuth、自动重连、订阅通知和完整 SSE lifecycle。
SubAgent            是有界工作流，不是长期自治团队；阻塞网络、subprocess、LLM 请求只能协作式取消。
Learning            默认只生成候选，不自动写项目记忆；提取器是保守启发式，不是 LLM curator。
Web UI              是静态 workbench，不是 React/Vite 级完整产品界面。
Repo/Git            支持 import、status/diff、worktree artifact；不负责完整远程同步和分支治理。
Benchmark           live provider 成本和延迟只有配置 key 后才能采样。
```

## 完成标准

新增高风险能力必须同时具备：用户入口、安全边界、审批或显式配置、审计事件、测试，以及 doctor/readiness 检查。受控边界不是“未实现”，但必须在 API 和文档中明确标注。
