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
