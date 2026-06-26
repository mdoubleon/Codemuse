# CodeMuse

CodeMuse 是一个个人 Coding Agent 学习项目。

最初做这个项目的目的很简单：帮助刚开始学习 Agent 工程的人，能更快看懂一个本地 Coding Agent 是怎么组织起来的，也能参考其他 Agent 项目的常见设计思路，把“模型、工具、记忆、审批、会话、前端”这些概念真正串起来。

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

- 本地浏览器工作台：对话、历史会话、运行详情、审批、记忆检索、模型配置。
- CLI 和 Python SDK：支持单次任务、审批、checkpoint/rewind、doctor、benchmark、memory 等命令。
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

如果要使用 OpenAI-compatible 的真实模型，复制 `.env.example` 为 `.env`：

```env
CODEMUSE_API_KEY=your_api_key_here
CODEMUSE_BASE_URL=https://api.openai.com/v1
CODEMUSE_MODEL=gpt-4o-mini
```

项目配置文件可以放在：

```text
.codemuse/config.json
```

只保存非密钥字段，例如：

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

真实 API Key 不应该写进前端文件，也不应该提交到 GitHub。

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

更完整的代码路径可以看 [docs/source-map.md](docs/source-map.md)。

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

它不是最终答案，也不是唯一正确架构。它更像一份可以运行的学习笔记：边写边理解，边拆边补齐。

## 文档

- [docs/source-map.md](docs/source-map.md)：主要代码路径和调用链。
- [docs/demo.md](docs/demo.md)：五分钟演示脚本。
- [docs/safety.md](docs/safety.md)：安全边界和审批机制。
- [docs/known-limitations.md](docs/known-limitations.md)：当前限制。
- [docs/interview-narrative.md](docs/interview-narrative.md)：项目讲解稿。

## 状态说明

CodeMuse 仍然是个人学习项目，很多地方还可以继续完善，例如更完整的前端交互、真实 provider 的流式输出、更细的权限策略、更强的记忆去重和更完整的多 Agent 编排。

我会持续把学习过程中觉得有价值的 Agent 工程能力整理进来，并尽量保持代码结构清楚、文档可读、功能可运行。

