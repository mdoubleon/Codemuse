# CodeMuse Five-Minute Demo

这个 demo 用临时 workspace 运行，不会修改当前仓库文件。

## 一键演示

```powershell
python scripts\run_agent.py demo run --output artifacts\demo
```

输出报告：

```text
artifacts/demo/latest.json
artifacts/demo/latest.md
```

## 演示内容

```text
workspace_read       Agent 读取本地 workspace 文件
github_import_plan   GitHub URL 生成安全 import plan，不 clone
project_plan         从 repo blueprint 生成项目任务计划
approval_write       文件写入先进入审批，approve 后才落盘
checkpoint_rewind    checkpoint 可以恢复 workspace 内容
```

## 手动演示命令

```powershell
python scripts\run_agent.py "list files"
python scripts\run_agent.py "github import https://github.com/openai/codex"
python scripts\run_agent.py "project plan goal: add approval docs"
python scripts\run_agent.py "write file notes/demo.txt content: hello from web"
python scripts\run_agent.py doctor --run-compile --web-smoke --demo-smoke
python scripts\run_agent.py doctor --strict --eval-output evals\reports
```

## Web 演示

```powershell
python scripts\run_server.py --host 127.0.0.1 --port 8765
```

打开：

```text
http://127.0.0.1:8765/
```

可以输入：

```text
list files
github import https://github.com/openai/codex
project plan goal: add release readiness docs
write file notes/demo.txt content: hello from CodeMuse
```
