# CodeMuse Developer Guide

本文档面向想阅读、运行或二次开发 CodeMuse 的开发者。它说明项目目标、核心流程、目录职责、本地运行方式和发布前检查。

## 项目目标

CodeMuse 是一个本地优先的 Coding Agent。它把一次任务拆成稳定的工程边界：

```text
用户输入
-> Web / CLI / SDK 入口
-> AgentRuntime 主循环
-> LLM Provider 生成文本或工具调用
-> ToolRegistry 查找工具
-> PolicyEvaluator 判断是否需要审批
-> ToolResult 写回上下文
-> Session / Timeline / Checkpoint 本地持久化
```

项目同时提供仓库蓝图能力：读取当前工作区结构，生成 RepoBlueprint，把可复用架构经验保存到本地记忆，后续任务可以自动召回。

## 顶层目录

```text
codemuse/
├── README.md             项目自述
├── PROJECT_GUIDE.md      开发者指南
├── pyproject.toml        包元数据和 CLI 入口
├── scripts/              CLI、评测、HTTP 服务启动脚本
├── src/codemuse/         核心 Python 包
├── tests/                单元测试和集成测试
├── docs/                 公开架构、安全、演示和限制文档
├── evals/                评测入口和报告输出目录
├── artifacts/            demo/benchmark 产物目录
├── skills/               项目级技能扩展目录
├── releases/             发布说明预留目录
└── web/                  Web 相关说明，实际静态资源在 src/codemuse/web/static
```

运行时数据写入 `.data/codemuse/`，本地配置可放在 `.codemuse/config.json`，真实 API Key 放在 `.env` 或进程环境变量中。这些目录和文件默认不提交。

## 核心包职责

| 包 | 职责 |
| --- | --- |
| `api` | Python SDK，供 CLI、HTTP 和外部调用者复用 |
| `app` | 统一装配 Runtime、工具、存储、模型和记忆组件 |
| `benchmarks` | baseline 评测、provider 对比和报告生成 |
| `capabilities` | 能力发现和能力目录 |
| `cli` | 命令行参数解析、命令分发和输出渲染 |
| `config` | 配置读取、运行时覆盖和 schema 校验 |
| `diagnostics` | doctor 健康检查和发布闸门 |
| `domain` | 消息、工具调用、检查点、仓库蓝图等共享数据模型 |
| `llm` | 模型 provider、FakeLLM 和 usage 统计 |
| `memory` | 项目记忆、仓库蓝图记忆、索引、检索和上下文注入 |
| `mcp` | MCP 配置、会话和工具适配边界 |
| `runtime` | Agent 主循环、事件、状态、取消、checkpoint、rewind |
| `server` | HTTP API、WebSessionManager 和静态资源服务 |
| `storage` | 本地 JSON/JSONL 存储 |
| `subagents` | 受控子 Agent 编排 |
| `tools` | 工具实现、注册表、策略和副作用预览 |
| `web_tools` | 受控网络访问工具 |

## 一次任务的流程

```text
浏览器或 CLI 输入 prompt
-> SessionHandle.prompt() 创建后台 job
-> AgentRuntime.prompt() 写入 user message
-> _messages_for_model() 组装 system/user/tool 上下文，并注入记忆召回
-> llm.complete() 返回文本或 tool_calls
-> ToolPolicyEvaluator 判断工具调用
   -> allow: 直接执行工具
   -> ask: 创建审批单并暂停
   -> deny: 写入工具错误
-> ToolRegistry.execute() 执行工具
-> ToolResult 转成 role="tool" 消息
-> Runtime 继续下一轮，直到模型给出最终回答
-> SessionStore / TimelineStore 保存结果和事件
```

## 本地运行

启动浏览器工作台：

```powershell
python scripts/run_server.py --host 127.0.0.1 --port 8765
```

运行 CLI：

```powershell
python scripts/run_agent.py "list files"
python scripts/run_agent.py memory search "ToolRegistry"
python scripts/run_agent.py doctor --run-compile --web-smoke
```

运行测试：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## 模型配置

`.codemuse/config.json` 保存非密钥配置：

```json
{
  "model": {
    "provider": "openai_compatible",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_key_env": "CODEMUSE_API_KEY"
  }
}
```

`.env` 或进程环境变量保存真实密钥：

```env
CODEMUSE_API_KEY=your_api_key_here
```

前端只允许填写环境变量名，不应该填写真实 API Key。

## 安全边界

工具通过 `ToolSpec` 声明权限域和副作用：

```text
read       读取本地信息
write      修改本地文件或本地状态
shell      执行命令
network    访问网络
external   调用外部能力
```

有副作用的工具默认进入审批门。审批单会保存 effect preview 和 effect digest，批准时会重新校验，避免用户批准的是旧预览或被篡改的参数。执行副作用工具前还会创建 checkpoint，便于回退。

## 发布前检查

```powershell
python scripts/run_agent.py doctor --run-compile --web-smoke
python scripts/run_agent.py doctor --strict --eval-output evals\reports
python -m unittest discover -s tests
```

开源前确认：

- `.env`、`.codemuse/`、`.data/`、`.private_notes/` 不进入提交。
- 生成报告只提交有意公开的示例。
- 文档不包含本机绝对路径、真实 API Key、私有中转站地址或个人学习记录。

