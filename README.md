# CodeMuse


CodeMuse 是一个个人 Coding Agent 学习项目。

<img width="1254" height="686" alt="12dfde6d2d8e41c46d605482b207a86e" src="https://github.com/user-attachments/assets/684a9690-2d05-472d-87a4-a3c947678407" />


做这个项目的目的很简单：帮助刚开始学习 Agent 工程的人，能更快看懂一个本地 Coding Agent 是怎么组织起来的，也能参考其他 Agent 项目的常见设计思路，把“模型、工具、记忆、审批、会话、前端”这些概念真正串起来。

这个项目不是为了做一个最大、最复杂的 Agent，而是希望把核心链路拆得足够清楚：

```text
用户输入
-> Agent Runtime
-> 模型判断是否需要调用工具
-> ToolRegistry 执行工具
-> Policy / Approval 控制风险
-> Memory 召回历史知识
-> Session / Timeline 保存过程
-> Web UI 展示对话和运行事件
```

如果你正在学习：

- Coding Agent 的主循环怎么写
- 工具调用如何注册和执行
- 为什么写文件、跑命令、访问网络需要审批
- 长期记忆和检索增强怎么接入 Agent
- 会话、检查点、事件流如何保存
- 一个 Agent 项目如何从 CLI 逐步扩展到 Web UI

那这个仓库可以作为一个可以运行、可以拆开读、也可以继续改造的学习样例。

## 当前能做什么

CodeMuse 当前包含这些能力：

- 本地浏览器工作台：对话、树形会话与上下文分支、运行详情、审批、记忆检索、模型配置。
- CLI 和 Python SDK：支持单次任务、会话 fork、审批、checkpoint/rewind、doctor、benchmark、memory 等命令。
- 工具系统：读取文件、写文件、搜索、替换、应用补丁、运行 shell、受控网页获取、仓库分析。
- 安全机制：有副作用的工具默认进入审批，执行前生成影响预览，并自动创建检查点。
- 记忆系统：项目长期记忆、仓库蓝图记忆、工作区索引和每轮自动召回。
- 评测与诊断：确定性 baseline、报告生成、release readiness doctor。

## 快速运行

启动 Web 工作台：

```powershell
python scripts/run_server.py --host 127.0.0.1 --port 8765
```

打开浏览器：

```text
http://127.0.0.1:8765/
```

指定要操作的项目目录：

```powershell
python scripts/run_server.py --host 127.0.0.1 --port 8765 --workspace "D:\your\project"
```

运行 CLI：

```powershell
python scripts/run_agent.py "list files"
python scripts/run_agent.py "read README.md"
python scripts/run_agent.py memory search "runtime"
python scripts/run_agent.py doctor --run-compile --web-smoke
```

运行测试：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## 配置真实模型

默认情况下，CodeMuse 可以使用本地确定性 FakeLLM，方便离线测试和学习流程。

复制 CodeMuse 自身目录中的 `.env.example` 为 `.env`。`scripts/run_agent.py` 和 `scripts/run_server.py` 只会加载这份 CodeMuse 自身的 `.env`，且不会覆盖已存在的进程环境变量；传入的 workspace `.env` 默认不会被读取。对外部仓库，请通过进程环境变量或用户级模型配置显式提供凭据。

使用自定义 OpenAI-compatible 中转站（或官方 OpenAI endpoint）时：

```env
CODEMUSE_API_KEY=your_api_key_here
CODEMUSE_BASE_URL=https://your-relay.example/v1
CODEMUSE_MODEL=your-model
CODEMUSE_PROVIDER=openai_compatible
```

使用 DeepSeek 专用适配器时：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
CODEMUSE_PROVIDER=deepseek
```

项目配置文件可以放在：

```text
.codemuse/config.json
```

它只用于 workspace 级的非连接配置，例如 runtime 和 capability 开关。为防止陌生仓库改变环境密钥的投递目标，默认不会采用其中的 `model.provider`、`model.base_url` 或 `model.api_key_env`。模型连接由环境变量或用户级配置保存：

```json
{
  "runtime": {
    "max_turns": 8,
    "max_tool_calls_per_turn": 4,
    "history_token_budget": 16000
  },
  "capabilities": {
    "skills_enabled": true
  }
}
```

也可以通过 CLI 选择 Provider。选择命令会写入用户级配置，而不是目标 workspace，便于在多个项目间安全复用中转站的模型、地址和环境变量名：

```powershell
python scripts/run_agent.py models use openai_compatible `
  --model your-model `
  --base-url https://your-relay.example/v1 `
  --api-key-env CODEMUSE_API_KEY

python scripts/run_agent.py models use deepseek
python scripts/run_agent.py models providers
```

Web 工作台中的 “OpenAI 兼容 / 自定义中转” 也是同一套配置入口。`api_key_env` 只保存环境变量名（如 `CODEMUSE_API_KEY` 或 `DEEPSEEK_API_KEY`），绝不保存真实 API Key。

`runtime.max_turns` 控制一个任务最多可进行多少个工具回合，`runtime.max_tool_calls_per_turn` 控制模型单次响应最多执行多少个不同工具调用，默认是 4；重复的同名同参数调用会自动合并。模型仍自行决定是否调用工具。`runtime.history_token_budget` 控制每次模型调用携带的持久化对话历史，替代固定消息条数窗口。CodeMuse 从最新消息向前选择完整上下文单元，工具输出过长时截断正文但保留 tool-call/tool-result 配对；当前用户输入始终完整保留。该预算不包含 system prompt、工具 schema 和当轮注入的长期记忆。

真实 API Key 不应该写进前端文件、`.codemuse/config.json` 或 GitHub。

## 扩展能力入口

CodeMuse 还提供以下与 pp-Echo 对齐、但按本项目标准库架构实现的入口：

```powershell
python scripts/run_agent.py tui --workspace .
python scripts/run_agent.py rpc --workspace .
```

- `prompts/`：`.codemuse/prompts`、项目 `prompts` 和内置模板的分层加载。
- `learning/`：在已持久化 turn 后生成安全候选，必须审核后才进入项目记忆。
- `browser/`：受控静态网页导航、tab、snapshot 和链接 ref；不执行 JavaScript。
- `web_tools/providers.py`：受审批的 `web_search`，通过 mode 路由 Web、新闻和 GitHub 查询。
- `session/`：面向客户端的 `SessionClient` 和持久化 session 配置覆盖。
- `api/json_mode.py`、`api/rpc_mode.py`：稳定 JSON lines 和 stdio RPC。
- `subagents/worktree.py`：隔离修改、patch artifact、审批应用和 worktree 清理。

Python SDK 同时提供 Learning 审核、MCP resources/prompts、session config、rewind preview 等机器接口。完整边界见 [docs/known-limitations.md](docs/known-limitations.md)。

## 项目结构

```text
src/codemuse/
  api/           Python SDK，对 CLI 和 HTTP 复用的稳定入口。
  app/           统一装配 Runtime、工具、模型、存储和记忆。
  benchmarks/    baseline 评测、provider 对比和报告生成。
  capabilities/  能力目录，给 UI/CLI 展示当前可用能力。
  cli/           命令行入口和输出渲染。
  config/        项目配置、运行时覆盖和 schema 校验。
  diagnostics/   doctor 健康检查和发布前检查。
  domain/        ChatMessage、ToolCall、Checkpoint、RepoBlueprint 等共享模型。
  llm/           FakeLLM 和真实 provider 适配层。
  memory/        项目记忆、蓝图记忆、索引、检索和上下文注入。
  mcp/           MCP 配置、会话和工具适配边界。
  runtime/       Agent 主循环、状态、事件、取消、checkpoint 和 rewind。
  server/        HTTP API、会话管理和静态 Web UI 服务。
  storage/       会话、审批、检查点、timeline、设置等本地持久化。
  subagents/     受控子 Agent 编排。
  tools/         工具定义、注册表、安全策略和具体工具实现。
  web/           浏览器工作台静态资源。
  web_tools/     受控网络访问工具。
```

运行时数据会写入：

```text
.data/codemuse/
```

这里会保存会话、审批、记忆、检查点和 timeline。这个目录默认不会提交到仓库。

## 树形会话

每个新任务都是一棵会话树的根节点。工作台里的“创建分支”会复制当前会话已保存的消息快照，生成可独立继续对话的子节点；后续修改只影响各自分支。旧版 session JSON 没有树字段时会自动作为根节点加载，不需要迁移数据。

HTTP API 保留原有扁平 `sessions` 字段，同时增加嵌套的 `session_tree`，因此旧客户端可以继续工作：

```text
GET  /api/sessions
POST /api/sessions  {"parent_session_id": "<parent-id>"}
```

Python SDK 对应提供 `list_session_tree(workspace)` 和 `fork_session(workspace, parent_session_id)`。父会话正在运行或仍有排队任务时，Web fork 会返回 400，避免复制到不完整的中间状态。

## 建议阅读顺序

如果你是第一次看 Agent 项目，可以按这个顺序读：

1. `src/codemuse/app/bootstrap.py`  
   看 CodeMuse 如何把模型、工具、存储、记忆和 Runtime 装配起来。

2. `src/codemuse/runtime/runtime.py`  
   看 Agent 主循环：接收用户输入、调用模型、处理工具调用、等待审批、保存会话。

3. `src/codemuse/tools/registry.py` 和 `src/codemuse/tools/base.py`  
   看工具如何声明参数、权限域和执行逻辑。

4. `src/codemuse/tools/policy.py`  
   看为什么有些工具可以直接执行，有些必须先审批。

5. `src/codemuse/memory/retrieval_hook.py` 和 `src/codemuse/memory/retrieval.py`  
   看长期记忆如何在模型调用前被召回并注入上下文。

6. `src/codemuse/server/session_manager.py` 和 `src/codemuse/server/http.py`  
   看浏览器前端如何通过 HTTP 调用 Agent。

7. `src/codemuse/web/static/`  
   看一个轻量 Agent Web UI 如何展示会话、审批、运行事件和记忆。

更完整的代码路径可以看 [docs/code-flowline.md](docs/code-flowline.md)。

## 安全设计

CodeMuse 把工具按权限域划分：

```text
read       读取本地信息
write      修改文件或本地状态
shell      执行命令
network    访问网络
external   调用外部能力
```

会改变文件、运行命令或访问网络的工具默认进入审批流程：

1. Runtime 根据 ToolSpec 判断 allow / ask / deny。
2. ask 工具生成 effect preview 和 effect digest。
3. 用户批准前不会真正执行。
4. 执行前创建 checkpoint。
5. 批准时重新校验 preview/digest，过期或被篡改会拒绝执行。

详细说明见 [docs/safety.md](docs/safety.md)。

## 这个项目适合怎么用

你可以把它当作：

- 学习 Coding Agent 架构的可运行样例。
- 拆解 Agent 工具调用、安全审批、记忆系统的参考项目。
- 给自己的 Agent 项目做功能原型的起点。
- 阅读其他 Agent 项目时的对照图谱：看到别人的 Runtime、ToolRegistry、Memory、Session，就能知道大概应该落在哪一层。

它不是唯一正确架构，而是一套强调标准库实现、显式审批和本地可审计存储的工程取舍。

## 文档

- [docs/code-flowline.md](docs/code-flowline.md)：主要代码路径和调用链。
- [docs/demo.md](docs/demo.md)：五分钟演示脚本。
- [docs/safety.md](docs/safety.md)：安全边界和审批机制。
- [docs/known-limitations.md](docs/known-limitations.md)：当前限制。
- [PROJECT_GUIDE.md](PROJECT_GUIDE.md)：开发、装配和发布检查指南。
- [evals/README.md](evals/README.md)：确定性能力评测矩阵。

## 状态说明

CodeMuse 已覆盖 pp-Echo 的核心 Coding Agent 能力面，并通过单元/集成测试、Web smoke、五步 demo 和 68-case baseline 验证。两者不是逐文件复制：CodeMuse 保留零第三方运行依赖、dataclass、JSON/JSONL 存储和更保守的浏览器/扩展执行边界；准确限制以 [docs/known-limitations.md](docs/known-limitations.md) 为准。

## 多阶段执行与恢复

CodeMuse 现在把“模型提出调用”和“真正产生副作用”拆成两个边界：

```text
LLM tool call
-> Planner：schema 校验、Policy Gate、effect preview/digest、Plan
-> Approval Queue：保存 plan_id 和精确 effect 合约
-> Executor：再次校验后执行，记录 execution_id 和结果
```

- Planner 只生成经过参数校验和策略判定的 Plan，不直接执行工具；Executor 只接受已允许的计划调用，或队列中已批准的精确调用。
- 需要审批的调用会保存参数、`effect_preview`、`effect_digest`、`plan_id` 和来源 turn head。批准时会再次校验 schema、当前 policy、digest、目标状态与分支归属；预览失效会标记为 `stale`，合约被破坏或 policy 变化会标记为 `invalid`。切到 sibling head 不会恢复或消费另一分支的待审批调用。
- 审批执行状态为 `pending -> executing -> completed/failed`。`completed` 的后续批准请求只重放已持久化结果，不再次运行工具；`executing` 或 `failed` 不自动重试，必须先处理不确定结果并生成新计划。

多 Agent 编排提供三个有界 workflow：

- `research`：并行收集 memory、仓库和接口线索。
- `debug`：补充测试与风险审查，聚焦定位故障原因。
- `code_change`：先研究和规划，再在独立 Git worktree 中生成 patch，由 reviewer 复核；只有明确输出 `REVIEW_DECISION: approved` 的 artifact 才能进入下一步，且仍需单独审批 `apply_patch_artifact` 才会改动主工作区。

`code_change` 的首次批准只允许隔离 worktree 执行，不等同于批准修改主工作区。`max_agents` 是并发上限，当前最多四个工作节点，并不是会静默跳过后续计划、patch 或 review 的总预算。

会话同时保留会话树和 turn-head DAG：可以 `resume_session` 恢复、用 `branch_session`/`fork_session` 从当前或指定 head 分支、用 `navigate_session_head` 切换已保存 head。切回旧 head 不删除同级分支；从 rewind 后的会话继续对话会自然产生新分支。

检查点保存会话状态与工作区快照，并记录 Git 元数据和快照内 commit。`preview_rewind` 会先显示影响；`rewind` 支持 `conversation_only`、`workspace_only` 或组合恢复，且要求 checkpoint 属于当前会话。会话回退会废止检查点后的当前分支审批；存在未决 `executing` 审批时拒绝回退。工作区恢复以带 SHA-256 manifest 的文件快照为准，不会对用户仓库执行 `git reset`；恢复时校验 checkpoint 身份、拒绝符号链接，并在失败时尝试还原事务备份。

上下文分为三层：最近完整消息作为短期上下文，超预算历史由 compactor 压缩为中期摘要，项目文件与项目记忆作为长期检索上下文。内置 JSON 向量索引和 BM25 不依赖第三方包；安装可选依赖后可使用本地 Chroma 持久化索引：

```powershell
pip install -e ".[chroma]"
```

Chroma 使用本地确定性 hashed embedding，不下载外部 embedding 模型；它不可用或故障时会自动回退到内置本地索引。

Skills 与 MCP 均按需激活。Skill 发现阶段只读取 `SKILL.md` 的有界元数据，命中描述或显式启用后才有界读取正文并注入当前 turn。MCP 默认 `lazy`，状态查看不会启动 stdio 进程或建立网络连接；MCP server 名必须唯一。运行时必须先通过需审批的 `mcp_activate`，其预览会绑定 server、transport、command/args、URL、timeout 和声明工具，配置变更后旧审批会失效，执行时只会激活与已校验预览一致的配置。

模型连接配置默认来自用户级配置或进程环境，workspace 的 `.codemuse/config.json` 不能覆盖 provider、endpoint 或 `api_key_env`，且 workspace `.env` 默认不会被启动脚本读取。`mcp.json` 仍可声明外部 command 或 URL，但 Runtime 必须在精确审批后才能激活非 mock server。已审查的兼容 workspace 可以分别设置 `CODEMUSE_TRUST_WORKSPACE_MODEL_CONFIG=1` 与 `CODEMUSE_TRUST_WORKSPACE_ENV=1` 允许旧配置行为。当前没有 workspace trust 提示、配置签名或每仓库密钥隔离；处理不可信仓库时仍应使用受限环境，详见 [docs/safety.md](docs/safety.md) 与 [docs/known-limitations.md](docs/known-limitations.md)。

