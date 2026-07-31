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

## 多阶段机制的非保证范围

```text
Exact-effect approval  绑定本地已校验参数与可生成的 preview；它不能替代远端系统的
                       幂等、事务或补偿机制，也无法撤销已发送的网络请求。
Approval recovery      completed 可重放已保存结果；executing/failed 会故意拒绝自动重试，
                       以避免重复副作用，恢复需要人工判断后重新规划。
Approval storage       使用进程内锁、fsync 和原子替换；不是多进程、跨主机或分布式审批锁。
Execution boundary     批准后的 preview 会在执行回调后、进程内 workspace 锁下再次校验；这不能把不受
                       CodeMuse 控制的外部进程文件写入变成跨进程原子事务。
Policy gate            覆盖已注册 ToolSpec 与已实现 preview；新增工具若未提供目标状态预览，
                       不能获得同等级的 stale 检测，应先补齐再作为高风险能力发布。
Reviewer gate          仅精确 `REVIEW_DECISION: approved` 可放行 artifact；reviewer 仍不是形式化验证、静态分析或人工代码评审的替代品。
```

## 会话、Git 与记忆边界

```text
Session DAG            保留本地会话/turn head 和 sibling history；不提供多人实时协作、分支合并、
                       冲突解决或跨机器同步。
Safe rewind            恢复来源是有校验的文件快照，不是用户仓库的 Git 历史操作；会废止检查点后的当前分支审批，
                       并拒绝未决执行；不会恢复远端状态、
                       Git remote、已提交后的外部副作用，且忽略 .git、.data、node_modules 等目录。
Snapshot capacity      快照最多 20,000 个文件、1 GiB；符号链接会被拒绝。大型仓库或包含链接的工作区
                       需要自行选择更合适的备份/恢复方案。
Chroma memory          Chroma 是可选的本地持久化后端，安装失败或运行失败会退回 JSON 索引；使用的是
                       确定性 hashed embedding，不是经训练的语义 embedding 模型。
Memory privacy         本地检索索引不会自动做加密、保留期管理、租户隔离或敏感信息脱敏；索引前应审查输入范围。
```

## 扩展与信任边界

```text
Skills                 lazy discovery 降低初始化开销，不会把不可信 Skill 变成安全内容；被激活的正文会
                       注入模型上下文，应按不可信提示词/指令来源审查。
MCP activation         server name 必须唯一；Runtime 的 mcp_activate 有审批并使用 preview 对应配置；但显式 SDK 的 resources/prompts 发现会连接并激活
                       server，调用方必须自行建立等价的外部操作授权。
MCP lifecycle          仍没有完整 OAuth、可靠自动重连、订阅通知、完整 SSE lifecycle 或跨进程会话协调。
Workspace trust        workspace 配置默认不能覆盖 provider/base_url/api_key_env，且目标 workspace .env 不会自动加载；
                       mcp.json 仍可声明 command/URL。没有 workspace trust prompt、签名或每仓库密钥隔离；
                       带真实密钥时仍应在受限环境中处理不可信仓库。
```
