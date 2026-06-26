# CodeMuse Safety Boundaries

CodeMuse 默认把安全边界放在工具执行层，而不是只依赖模型“自觉”。

## 当前已实现

```text
workspace path containment      文件工具限制在 workspace 内
approval-required writes        write_file / replace_text / apply_patch 需要审批
effect preview                  写入前生成 diff / effect preview
stale guard                     审批前后摘要不一致时阻止落盘
checkpoint before writes        高风险写入前创建 checkpoint
workspace safe rewind           checkpoint 可恢复 workspace 文件
shell safety policy             高风险 shell 命令会被 block/stale
guarded web fetch               私有地址和本地地址会被阻止
safe GitHub import MVP          prepare_repo_import 只生成计划，不 clone
subagent allowlist              subagent 只能使用受控工具集合
doctor strict gate              发布前可运行 compile/test/web/eval gate
```

## 当前不会做的事

```text
不会静默写文件
不会在 GitHub import MVP 中真实 clone
不会执行 fetched 网页 JavaScript
不会让 subagent 递归创建 subagent
不会让 blocked shell 命令在 approve 后继续执行
不会把 strict release gate 的 warning 当作完整通过
```

## 高风险能力的完成要求

后续补真实 clone、live provider、动态 extension entrypoint 时，必须满足：

```text
有 effect preview
有 allow / ask / deny policy
有 approval 或显式配置开关
有审计事件
有 unit 或 baseline case
有 doctor/readiness 检查
```

