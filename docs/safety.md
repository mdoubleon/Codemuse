# CodeMuse Safety Boundaries

CodeMuse 把安全边界放在工具执行层，而不是依赖模型自行判断。

## 已实现

```text
workspace containment     文件路径必须位于 workspace 内。
approval-required effects 写文件、shell、网络和 artifact 应用先进入审批。
effect preview/digest     审批前展示 diff、命令或 URL 风险，并保存稳定摘要。
stale guard               参数、文件或网络目标变化后拒绝旧审批。
checkpoint before effects 高风险动作执行前创建 checkpoint。
safe rewind               支持 conversation_only、workspace_only 和组合恢复及预览。
shell policy              危险命令直接 block，允许命令仍需审批。
network policy            HTTP/HTTPS 白名单、DNS/IP 检查、私有地址阻断和大小/跳转限制。
static browser            不执行 JavaScript，不使用 cookie、profile 或认证状态。
subagent isolation        只读 allowlist；写入仅在 Git worktree，产物回主目录必须再次审批。
learning review           敏感文本和临时日志过滤，候选默认不自动写项目记忆。
extension boundary        只安装声明式 hook/tool，不执行任意 Python entrypoint。
```

## 明确不会静默执行

CodeMuse 不会静默写文件、自动应用 SubAgent patch、执行网页 JavaScript、访问私有网络、让 SubAgent 递归创建 SubAgent，也不会因为用户批准而绕过 stale/digest 校验。被拒绝的 patch artifact 会标记为 rejected 并清理隔离 worktree。

## 新高风险能力要求

真实浏览器/CDP、扩展 Python entrypoint、远程认证或更强自治编排如果以后接入，必须增加 effect preview、allow/ask/deny policy、显式审批或配置开关、审计事件、单元/基线测试和 doctor 检查。

## Planner / Executor 与精确审批

模型输出不能直接执行。`Planner` 先查询 ToolSpec、校验 JSON schema、通过 Policy Gate 生成 `allow`、`ask` 或 `deny` 的 Plan；只有 `Executor` 能把已允许的 Plan 交给 ToolRegistry。`ask` 调用会把下面的不可变审批合约写入队列：

```text
tool name + validated arguments + effect_preview + effect_digest + plan_id + head_id
```

`effect_digest` 覆盖工具名、已校验参数和预览。用户批准后，Runtime 先校验来源 head，Executor 再校验 schema、当前 policy、digest 和当前 preview；创建 checkpoint 等执行前回调之后会在进程内 workspace 锁下再次校验 preview。参数/审批内容不一致会进入 `invalid`，目标状态或已声明 MCP 配置变化会进入 `stale`。切换到 sibling head 时不能恢复、批准或拒绝其他分支的 pending approval。因此“批准”只批准该条具体 effect，不是为同类工具授予长期通行证。

审批的执行状态独立于用户决定状态：

```text
pending -> executing -> completed
                     -> failed
```

执行前原子地领取 `execution_id`，完成结果会随审批记录持久化。重复批准已完成记录只重放该结果，不再执行副作用；发现记录仍为 `executing` 或已经 `failed` 时拒绝自动重试，以避免在崩溃或网络超时后重复产生效果。此时应人工检查外部结果，再生成新计划。

## 多 Agent 与 artifact 门禁

`research`、`debug` 与不带编辑权限的 `code_change` 只读执行。可编辑的 `orchestrate_code_change` 本身需要审批，实际修改发生在受管理的 Git worktree 中，父工作区保持不变。它的 effect preview 显示目标、并发上限和“isolated worktree”边界。

worker 产生的 patch 会保存为 artifact，reviewer 必须先给出唯一精确行 `REVIEW_DECISION: approved`；`rejected`、缺失或格式错误的结论都会失败。只有此后请求 `apply_patch_artifact` 并再次通过精确审批、preview 复核和 `git apply --check`，主工作区才会被修改。reviewer 不通过、artifact 不能干净应用或用户拒绝时，不会自动把修改带回主工作区。

## 检查点与安全回退

副作用执行前会创建 checkpoint。checkpoint 保存会话消息、active head 和工作区文件快照，另附 Git branch/HEAD/dirty metadata，并在快照目录初始化独立 commit 便于审计。恢复前会生成风险预览；`conversation_only`、`workspace_only` 和组合恢复均要求 checkpoint 属于当前 session。会话恢复会使检查点后当前分支创建或变更的审批进入 `stale`；只要同一 session 任一 head 存在未决 `executing` 审批，恢复会被拒绝，且其他 head 不能启动新的工具回合或审批执行，避免共享工作区在回退后仍被未知副作用修改。

文件恢复会校验 checkpoint identity、manifest 路径、文件大小和 SHA-256，拒绝符号链接，且先保留事务备份以便恢复失败时还原。实现不会在用户仓库运行 `git reset` 或变更其分支历史；快照受到文件数和总大小上限约束，无法满足约束的 workspace 会拒绝创建快照。

## Lazy Skills / MCP

Skills discovery 只读取有界元数据，正文在命中任务或显式启用后再按上限载入。Skill 文本会进入模型上下文，所以 workspace 中的 Skill 仍应视为可影响 Agent 行为的受信任输入。

默认 `lazy` 配置下，bootstrap 与 `mcp_status` 不启动 stdio 进程、不打开 HTTP 连接；若显式配置 `lifecycle: "eager"`，则会按配置启动。MCP server name 必须唯一。Runtime 内的 `mcp_activate` 始终要求精确审批，预览绑定 server、transport、command、args、URL、timeout、认证声明和静态工具列表；批准后配置有变化会因 preview 校验失败而不启动新目标，执行时会重新读取未激活 server 配置以确保连接目标与 preview 相同。显式 SDK resources/prompts 发现目前可能直接激活 server，它们是外部操作，不是无副作用的状态读取。

## Workspace 信任模型

模型连接属于用户信任域：用户级配置和进程环境可以设置 provider、`base_url` 与 `api_key_env`，而 workspace `.codemuse/config.json` 默认不能覆盖这些字段，目标 workspace `.env` 也不会被启动脚本自动加载。通过 `CODEMUSE_TRUST_WORKSPACE_MODEL_CONFIG=1` 或 `CODEMUSE_TRUST_WORKSPACE_ENV=1` 可以为已审查的本地 workspace 显式恢复对应兼容行为。

`mcp.json` 仍是仓库输入，可以声明外部 command 或 URL；非 mock server 不会因 bootstrap 或 `mcp_status` 启动，而要经过 `mcp_activate` 的精确审批。现阶段仍没有 workspace trust prompt、配置签名、每仓库密钥隔离或 provider endpoint allowlist。对不可信仓库应使用不含真实密钥的隔离进程，并在审查配置后再启用模型或 MCP。
