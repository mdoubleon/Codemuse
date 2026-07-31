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
└── releases/             发布说明目录
```

运行时数据写入 `.data/codemuse/`，workspace 配置可放在 `.codemuse/config.json`，真实 API Key 放在进程环境变量或 CodeMuse 用户级配置引用的环境变量中。这些目录和文件默认不提交。目标 workspace 的 `.env` 默认不会被启动脚本加载。

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
python scripts/run_agent.py models providers
python scripts/run_agent.py models use deepseek
python scripts/run_agent.py doctor --run-compile --web-smoke
```

运行测试：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## 模型配置

`.codemuse/config.json` 保存 workspace 级非密钥配置。默认情况下，其中的 `model.provider`、`model.base_url` 和 `model.api_key_env` 会被忽略，避免仓库配置改变已有环境密钥的投递目标：

```json
{
  "runtime": {
    "max_turns": 8,
    "history_token_budget": 16000
  },
  "capabilities": {
    "mcp_enabled": false
  }
}
```

进程环境变量保存真实密钥。`scripts/run_agent.py` 和 `scripts/run_server.py` 仅加载 CodeMuse 自身目录的 `.env`，不会自动读取目标 workspace 的 `.env`，也不会覆盖已存在的进程环境变量：

```env
# 自定义 OpenAI-compatible 中转站
CODEMUSE_API_KEY=your_api_key_here
CODEMUSE_BASE_URL=https://your-relay.example/v1
CODEMUSE_MODEL=your-model
CODEMUSE_PROVIDER=openai_compatible

# 或 DeepSeek 专用适配器
# DEEPSEEK_API_KEY=your_deepseek_api_key_here
# CODEMUSE_PROVIDER=deepseek
```

也可通过 CLI 一次性选择并保存 Provider；连接配置写入用户级配置，而不是目标 workspace：

```powershell
python scripts/run_agent.py models use openai_compatible `
  --model your-model `
  --base-url https://your-relay.example/v1 `
  --api-key-env CODEMUSE_API_KEY
python scripts/run_agent.py models use deepseek
```

前端和项目配置中的 `api_key_env` 只允许填写环境变量名，不应该填写真实 API Key。

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

## 多阶段 Runtime 约定

高风险工具调用的正式链路如下，维护 Runtime 或新增工具时不得绕过其中任一边界：

```text
provider ToolCall
-> Planner.create_plan()
-> 参数 schema 校验
-> ToolPolicyEvaluator（allow / ask / deny）
-> effect preview + digest（ask）
-> PendingApprovalStore
-> Executor.execute() / Executor.execute_approved()
-> ToolRegistry.execute()
```

`Planner` 位于 `runtime/planner.py`，负责把模型输出编译为 Plan；`Executor` 位于 `runtime/executor.py`，负责唯一的执行入口。新工具应在 `ToolSpec` 中声明 schema、permission domain 与副作用属性，并在需要审批时提供可复算的 effect preview。不要在 tool、adapter 或 HTTP 层直接调用 `ToolRegistry.execute()` 来规避 Plan、policy 或 approval。

审批记录包含 `plan_id`、`effect_digest`、`effect_preview`、来源 head 和执行状态。批准边界会重做参数、policy、digest、预览与 head 归属校验；完成的审批只返回持久化结果，执行中或失败的审批不应由恢复逻辑自动重跑。涉及外部系统时，工具实现仍应尽可能使用业务侧幂等键，因为本地执行状态不能消除远端已部分完成的副作用。

## 工作流、会话与回退

`subagents/orchestrator.py` 定义受限的 `research`、`debug` 和 `code_change` workflow。前两类是只读研究；代码变更必须走 `orchestrate_code_change`，其副作用是创建并使用隔离 Git worktree。该 workflow 的 reviewer 必须输出唯一精确行 `REVIEW_DECISION: approved` 才能把 artifact 标为 `approved`；缺失、格式错误或 `rejected` 均会失败。之后 `apply_patch_artifact` 还要经过常规精确 effect 审批并通过 `git apply --check`，才能触及父工作区。

会话记录在 `storage/sessions.py` 中保存 parent/root 关系、turn DAG、active head 和每个 head 的消息快照。SDK 对应入口为：

```python
resume_session(workspace, session_id)
branch_session(workspace, parent_session_id, head_id=...)
fork_session(workspace, parent_session_id, head_id=...)
navigate_session_head(workspace, session_id, head_id)
preview_rewind(workspace, checkpoint_id)
rewind(workspace, checkpoint_id, mode="conversation_and_workspace")
```

切换 head 是视图与后续执行起点的切换，不会删除 sibling history。审批绑定其来源 head，切换到 sibling 后不会恢复、批准或拒绝另一分支的 pending approval；旧记录则按当前消息中的 tool call 归属兼容判断。checkpoint 会记录当时的 active head；会话 rewind 后恢复该 head，因此下一次 turn 会成为保留历史上的新分支。rewind 会废止检查点后的当前分支审批，并拒绝存在未决 `executing` 审批的恢复。Git checkpoint 的恢复源是受校验文件快照，Git 元数据用于审计和比对，并不执行 Git 历史重写。

## 上下文与扩展的维护边界

短期消息窗口、`ConversationCompactor` 的中期摘要、memory retrieval 的长期召回共同组成分层上下文。`memory/chroma_index.py` 是可选后端，依赖 `codemuse[chroma]`；必须保留 JSON 向量索引/BM25 fallback，并保证 Chroma 导入、构建或查询失败不会让主任务失败。

Skill discovery 只扫描 `SKILL.md` 前 16 KiB 的元数据，正文仅在显式启用或描述匹配后按大小上限读取。新增 Skill 不能依赖 discovery 阶段执行代码。

MCP 的默认 lifecycle 是 `lazy`。`mcp_status` 不应启动外部连接；配置中 server name 必须唯一，非 mock server 要通过批准后的 `mcp_activate` 才能从 Runtime 注册可调用工具。`mcp_activate` 的 effect preview 必须覆盖将被启动的 server 配置（包括 timeout），配置文件改变后旧审批必须变 stale，激活时会刷新未激活配置以确保启动的目标与 preview 一致。注意 SDK 的 resources/prompts 发现方法是显式外部操作，当前会自行激活 server；它们不应被误描述为“无连接的状态查询”。

## Workspace 信任前提

模型连接配置默认从用户级配置或进程环境读取；workspace 的 `.codemuse/config.json` 无法覆盖 provider、`base_url` 或 `api_key_env`，目标 workspace 的 `.env` 也不会被启动脚本自动加载。MCP 配置仍可声明 command、args 或 URL，但非 mock server 必须经过 `mcp_activate` 的精确审批。已审查的本地 workspace 可显式设置 `CODEMUSE_TRUST_WORKSPACE_MODEL_CONFIG=1` 或 `CODEMUSE_TRUST_WORKSPACE_ENV=1` 恢复对应兼容行为。工程尚无 workspace trust 提示、配置签名和每仓库密钥隔离机制，因此测试不可信仓库时仍应使用无真实密钥的隔离进程或受限环境。
