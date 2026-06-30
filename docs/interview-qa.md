# CodeMuse 大厂 AI 应用开发面试 Q&A

这份文档用来准备项目面试。回答时不要只背结论，建议按这个结构讲：

```text
我为什么这样设计 -> 我放弃了什么方案 -> 这个方案的失败场景 -> 上线后怎么补
```

## 1. 你用一句话解释 CodeMuse 的核心价值。它和普通 ChatGPT 加 shell/file 工具 demo 有什么本质区别？

**回答：**

CodeMuse 不是一个聊天壳，而是一个可运行、可审计、可回放、可扩展的本地 Coding Agent 骨架。它把 Coding Agent 的核心边界拆成了 `AgentRuntime`、`ToolRegistry`、`ToolPolicyEvaluator`、approval、checkpoint、memory、timeline、CLI/SDK/Web API，并且这些入口共用同一条 runtime 链路。

普通 demo 往往是：

```text
用户输入 -> 模型 -> 直接调用函数 -> 返回结果
```

CodeMuse 的链路更接近真实 Agent 产品：

```text
用户输入
-> AgentRuntime
-> LLMProvider
-> ToolRegistry
-> ToolPolicyEvaluator
-> effect preview / approval
-> checkpoint
-> tool execution
-> tool observation 写回 messages
-> session / timeline 持久化
-> memory recall
-> CLI / Web / SDK 复用
```

我想证明的不是“模型能不能调用工具”，而是一个 Coding Agent 如何把工具、安全、记忆、会话和可验证性组织在一起。

**可指代码：**

- `src/codemuse/runtime/runtime.py`
- `src/codemuse/tools/registry.py`
- `src/codemuse/tools/policy.py`
- `src/codemuse/tools/effects.py`
- `src/codemuse/app/bootstrap.py`
- `docs/source-map.md`

**边界：**

它目前还是本地 deterministic MVP，不是完整云端 SaaS。真实 provider、多租户隔离、强沙箱和生产级观测还需要继续补。

## 2. `AgentRuntime._run_loop()` 同时负责模型调用、工具调度、审批、checkpoint、事件发布、session 持久化，是不是职责过重？

**回答：**

是的，从纯工程拆分角度看，`AgentRuntime` 目前偏厚。但在这个阶段我有意让它承担主编排职责，因为它是 Agent 状态机的唯一可信边界：每一轮模型输出、工具调用、审批暂停、checkpoint、tool observation、session save、timeline event 都必须按严格顺序发生。

如果过早把这些流程拆散，很容易出现状态不一致，比如工具执行了但 session 没保存、approval 已批准但 checkpoint 没创建、tool error 没写回模型上下文。

当前设计里，Runtime 负责“顺序和状态一致性”，具体能力下沉到独立模块：

```text
模型调用：LLMProvider
工具执行：ToolRegistry / BaseTool
安全策略：ToolPolicyEvaluator
副作用预览：tools.effects
审批存储：PendingApprovalStore
检查点：CheckpointStore / WorkspaceSnapshotManager
记忆注入：MemoryContextProvider
事件持久化：TimelineStore
会话持久化：SessionStore
```

如果后续要拆，我会优先拆成：

```text
TurnRunner：负责单轮模型与工具循环
ApprovalCoordinator：负责 stage/approve/reject/digest 校验
CheckpointCoordinator：负责副作用执行前快照
EventBus：负责 timeline 和订阅
ContextBuilder：负责消息裁剪、摘要、memory recall
```

但我不会把“状态推进顺序”完全交给各模块自由处理。Runtime 仍然应该保留状态机入口，否则 Agent 行为会变得难审计。

**失败场景：**

现在 Runtime 变厚后，新增能力时容易把逻辑继续塞进主循环，测试也会越来越依赖集成测试。后续应该补更明确的状态机测试和 coordinator 级单测。

## 3. `_messages_for_model()` 只取最后 20 条消息。如果一次任务涉及 100 轮工具调用，模型丢了早期约束怎么办？

**回答：**

这是当前 MVP 的一个明确技术债。`messages[-20:]` 的优点是简单、确定、方便测试，但它不是生产级上下文管理方案。

风险是：

- 早期用户约束被截断，比如“不要修改测试文件”。
- 长任务中的关键 tool observation 被丢失。
- 多轮审批、失败重试后，模型看不到最初目标。
- token 使用不可控，无法按模型上下文窗口精细裁剪。

上线版本我会改成基于 token budget 的上下文构建：

```text
system prompt
+ durable constraints
+ current user goal
+ pending approval / pending plan
+ 最近对话
+ 关键 tool observations
+ 压缩后的历史摘要
+ memory recall
```

具体做法：

- 把用户硬约束抽取成 `session.constraints`，永远注入。
- 对 tool result 做结构化压缩，长输出只保留摘要和引用。
- 给消息和事件打 importance 分数，而不是简单按时间截断。
- 定期生成 conversation summary。
- memory recall 和历史摘要分开，避免把短期工作流污染到长期记忆。

**可指代码：**

- `AgentRuntime._messages_for_model()`
- `MemoryContextProvider.transform_context(...)`

## 4. 为什么工具失败了仍然写回 `role="tool"`，而不是直接抛异常结束？

**回答：**

因为对 ReAct Agent 来说，工具失败本身也是 observation。模型需要知道失败原因，才能决定下一步是换路径、修正参数、请求用户确认，还是停止。

如果工具失败就直接抛异常结束，Agent 会失去自我修复能力。例如：

```text
read_file -> 文件不存在
```

这个失败应该变成 tool message，让模型下一轮可以尝试 `list_files` 或询问用户，而不是直接崩掉。

CodeMuse 里 `_append_tool_error()` 会把错误写成：

```text
role="tool"
metadata={"success": False, "is_error": True}
```

这样 session、timeline、前端和模型上下文都能看到同一份失败记录。

**边界：**

这不代表所有异常都应该吞掉。系统级错误、存储损坏、安全校验失败等应该显式标记并中断或进入安全状态。工具业务失败可以作为 observation，平台不一致则不能伪装成普通工具结果。

## 5. `run_shell("dir")` 和 `run_shell("Remove-Item -Recurse C:\\")` 在 spec 层都是 shell。你怎么做参数级风险判断？

**回答：**

`ToolSpec` 解决的是工具级权限边界，不能解决参数级风险。所以 CodeMuse 在 `tools.effects.build_shell_effect_preview()` 里增加了参数级预览和风险分类。

`run_shell` 的 spec 声明：

```text
permission_domain="shell"
requires_confirmation=True
sensitive=True
side_effect=True
```

这保证所有 shell 命令默认进入审批。但审批前还会调用 `classify_shell_command(command)`，根据命令文本做保守分类：

- 空命令直接 blocked
- `remove-item`、`rm -rf`、`git reset --hard`、`git clean` 等 destructive pattern blocked
- `curl`、`wget`、`git clone`、`pip install`、`npm install` 标记网络或安装外部代码风险
- `>`、`set-content`、`move-item` 等标记写文件风险
- `pytest`、`unittest`、`python -m` 标记执行项目代码风险
- `dir`、`pwd`、`python --version` 等低风险命令标记 low

审批单里会展示：

```text
command
working_directory
timeout_seconds
max_output_chars
risk_level
risk_reasons
blocked
reason
```

**关键点：**

这只是参数级风险提示和基础拦截，不是完整沙箱。真正上线必须加系统级沙箱，例如容器、低权限用户、只读挂载、网络隔离、命令 allowlist、资源限制和审计。

## 6. `effect_preview` 和 `effect_digest` 解决了什么？没有解决什么？请讲一个 TOCTOU 场景。

**回答：**

`effect_preview` 解决的是“用户批准前到底会发生什么”的可见性问题。比如写文件、替换文本、应用 patch、shell、web fetch，在执行前都生成影响预览：

```text
目标路径
是否存在
写入前 hash
字符变化
unified diff
命令风险
URL/hostname/timeout/byte limit
```

`effect_digest` 解决的是审批单被篡改的问题。它把：

```text
tool_name + arguments + effect_preview
```

做稳定 JSON 序列化并计算 sha256。批准时重新计算，如果不一致，就标记 approval invalid，不执行工具。

TOCTOU 场景：

1. 模型准备 `replace_text` 修改 `app.js`。
2. 系统生成 diff 预览，用户看到旧版本 diff。
3. 用户还没批准时，另一个进程或用户修改了 `app.js`。
4. 如果直接执行，旧 diff 会作用到新文件，可能误改。
5. CodeMuse 在 approve 时重新生成 preview，比较 `before_sha256 / before_chars / relative_path` 等字段。
6. 如果目标文件已变，approval 标记 stale，不执行。

**没有解决的问题：**

- shell 命令的真实副作用无法完全预览。
- 外部世界副作用无法靠 workspace checkpoint 回滚。
- 本地恶意用户如果同时能改代码和存储，仍然需要更强的权限隔离。
- preview 到 execute 之间仍然可能有极短竞态，生产环境需要文件锁或事务式写入。
- 对网络请求只能预览 URL 和 SSRF 策略，不能预知远端响应副作用。

## 7. 副作用工具执行前创建 checkpoint。如果 shell 修改 workspace 外部文件、启动进程、发网络请求、改数据库，checkpoint 能回滚吗？

**回答：**

不能。当前 checkpoint 的边界是 workspace 文件快照和会话状态，不是操作系统或外部世界事务。

它能回滚：

- workspace 内文件改动
- session messages
- 部分 CodeMuse 本地状态

它不能回滚：

- workspace 外部文件
- 已发出的网络请求
- 数据库写入
- 启动的后台进程
- 包安装对全局环境的污染
- shell 命令产生的外部副作用

所以 checkpoint 是“开发体验和误操作恢复机制”，不是安全沙箱。真正安全要靠执行前的审批、路径限制、命令风险拦截，以及未来的容器/沙箱/权限隔离。

面试里要诚实讲：我没有把 checkpoint 包装成万能回滚，它只是副作用工具的一道恢复层。

## 8. `approve()` 用户批准后直接执行原始工具调用，不再重复进入审批门。为什么这样安全？如果审批单被篡改，靠什么发现？

**回答：**

批准后不重复进入审批门，是为了避免同一个 pending approval 无限循环。安全性靠两层校验：

1. `validate_effect_digest(...)`

确认审批单中的 `tool_name + arguments + effect_preview` 和创建审批时保存的 digest 一致。如果有人改了参数、工具名或预览，digest 对不上，审批变 invalid。

2. `validate_tool_effect_preview(...)`

批准时重新生成当前 preview，确认目标文件状态、命令参数、URL 参数等没有偏离用户当时看到的内容。如果目标文件变了，审批变 stale。

通过这两层校验后，Runtime 才执行原始工具调用，并在执行前创建 checkpoint。

**边界：**

本地文件存储不是防恶意管理员的强安全边界。如果攻击者能任意改程序代码、审批存储和运行环境，digest 也不能提供完整防护。生产级需要不可篡改审计日志、签名、权限隔离和服务端存储。

## 9. project memory、blueprint memory、file memory/retrieval 的边界是什么？什么应该进入 memory，什么不应该进入？

**回答：**

我把记忆分成三类：

```text
project memory：
  当前项目长期事实、偏好、约束、架构决策、工作流。

blueprint memory：
  从仓库结构中提取出的可复用架构经验，比如模块职责、数据流、可复用模式。

file memory / retrieval：
  对工作区文件建立索引，用来在当前任务中检索相关代码片段或文档。
```

应该进入 memory 的内容：

- 用户明确要求“记住”的偏好
- 稳定项目事实
- 架构决策
- 常用命令和工作流
- 重要模块职责
- 可复用设计模式

不应该进入 memory 的内容：

- API key、token、密码、cookie
- 临时 debug 输出
- 大段原始源码
- 不确定的推测
- 用户一次性的短期指令
- 未经确认的隐私信息

上线后我会加 memory 写入策略：敏感信息检测、置信度、来源路径、过期时间、用户可编辑、可删除、可审计。

## 10. Repo Blueprint Memory 比简单 `rg + summarize README` 强在哪里？如果仓库很大、语言混杂、文档过期，如何保证 blueprint 不误导 agent？

**回答：**

简单 `rg + summarize README` 主要依赖文本搜索和 README 质量。README 一旦过期，summary 就会偏。

Repo Blueprint Memory 的不同点是它先构建结构化 `RepoIndex`，再从多种证据推断仓库蓝图：

```text
文件树
entrypoints
package/config files
important files
agent_related_files
route files
test files
README
语言分布
模块路径
```

然后生成：

```text
problem_statement
tech_stack
minimal_architecture
module responsibility map
data_flow
reusable_patterns
learning_notes
key_files
```

最后再拆成 `BlueprintMemoryItem`，按 architecture、module_map、tech_stack、data_flow、reusable_patterns 等类别保存和检索。

这比一段 summary 更适合复用，因为它保留了结构、来源路径和类别。

**如何避免误导：**

当前版本还不能完全保证。它是 heuristic blueprint，不是形式化证明。我会从几方面补：

- 每条 blueprint memory 附带 source_paths。
- 区分“从文件结构推断”和“从 README 文本读取”。
- 给每条结论加 confidence。
- 对大型仓库分层索引：先模块级，再入口级，再热点文件级。
- 语言混杂时按 package boundary 分组，而不是全局混成一份 summary。
- 文档和代码冲突时优先 package/config/entrypoint/test 证据。
- 定期重新索引，并用文件 hash 判断 blueprint 是否过期。

面试表达可以这样收束：

> Blueprint 不是为了替代代码阅读，而是给 Agent 一个可检索的架构地图。它必须带来源、置信度和过期判断，否则会变成更危险的幻觉来源。

## 11. 如果真实 provider 接入后，模型 hallucinate 一个不存在工具名，系统怎么表现？

**回答：**

这属于 runtime contract 问题，不应该简单归咎于模型。模型可能幻觉，但 Runtime 必须把工具调用边界守住。

期望行为是：

```text
ToolRegistry.get_spec(tool_name)
-> 找不到工具
-> 写入 tool_error observation
-> timeline 记录错误
-> 模型下一轮可以纠正
```

如果当前实现某处直接抛异常导致整轮崩掉，那就是 runtime 鲁棒性不足。生产版本应该把未知工具转成结构化错误，并把可用工具列表或相近工具名反馈给模型。

## 12. 如果模型陷入“搜索-读取-搜索-读取”循环，现在靠 `max_turns` 截断。上线怎么检测和打断低价值循环？

**回答：**

`max_turns` 是最后保险，不是质量控制。上线我会加 loop detector：

- 最近 N 次工具调用签名重复
- 相同 query 或 path 反复读取
- 工具结果没有新增信息
- 目标进度没有变化
- token 成本持续上升但没有产出

打断方式：

- 提醒模型总结已有信息并进入回答
- 降低继续搜索的预算
- 要求模型给出 next action justification
- 对重复工具调用直接返回 cached observation
- 让用户确认是否继续深挖

## 13. Web UI 多个浏览器同时操作同一个 session，approval A 和 approval B 交错会发生什么？

**回答：**

这是当前从本地 MVP 到多人产品必须补的并发问题。

现在每个 approval 绑定：

```text
session_id
tool_call_id
tool_name
arguments
status
effect_digest
effect_preview
```

这能防止批准错 session，也能防止参数被改。但多个客户端并发操作同一 session 时，还需要：

- session 级互斥锁
- approval 状态 CAS 更新
- turn_id / version 校验
- pending approval 队列顺序
- 前端实时同步 approval 状态
- 已处理 approval 的幂等响应

否则可能出现一个客户端 reject，另一个客户端 approve，或者旧页面批准已经 stale 的工具调用。

## 14. MCP、skills、extensions、subagents 都注册成工具。统一抽象很优雅，但如何防止它们绕过 approval/policy？

**回答：**

统一注册成工具的好处是：所有外部能力都必须先变成 `ToolSpec`，再经过 `ToolPolicyEvaluator`。关键是不能允许 extension/MCP 直接拿到 Runtime 内部能力或裸文件系统操作。

需要保证：

- 每个动态工具必须声明 permission domain。
- 默认 external/network/write 都 requires confirmation。
- extension 不能直接执行 Python 任意入口，除非进入单独沙箱。
- MCP tool call 也必须走 ToolRegistry。
- subagent 只能拿 allowlist registry，不继承父 agent 全部工具。
- capability catalog 只展示能力，不等于自动授予能力。

生产版本还需要对动态工具做 manifest 签名、来源校验、权限声明审核和运行时沙箱。

## 15. deterministic baseline eval 能证明什么？不能证明什么？100-case Agent 评测集怎么设计？

**回答：**

deterministic baseline 能证明核心工程链路没有退化，比如：

- CLI/SDK 能跑通
- 工具能注册和执行
- approval 能创建和批准
- checkpoint/rewind 工作
- memory recall 工作
- server API 基本可用
- repo blueprint 能生成

它不能证明：

- 真实模型推理质量
- 长任务规划能力
- 复杂代码修改正确性
- 安全策略覆盖所有攻击
- 多用户并发稳定性
- UI 体验完整性

100-case taxonomy 我会这样设计：

```text
基础工具：读、写、搜索、patch、shell
审批安全：危险命令、stale approval、digest tamper、路径逃逸
记忆：写入、召回、去重、敏感信息拒存
仓库理解：小仓库、大仓库、多语言、过期 README
代码修改：单文件、多文件、测试驱动、失败修复
长任务：多轮工具、循环检测、上下文压缩
Web/API：session、events、approval、cancel
MCP/extension/subagent：权限和错误隔离
恢复能力：checkpoint、rewind、失败重试
真实 provider：工具选择、幻觉工具、流式输出、token 成本
```

每个 case 都应该有输入、期望事件序列、文件 diff 断言、工具调用断言和最终回答质量标准。

## 16. 项目里最大的架构级技术债是什么？

**回答：**

最大的技术债是上下文管理和 Runtime 状态机还不够产品级。

具体包括：

- `_messages_for_model()` 还只是最近 20 条。
- 工具结果没有统一压缩策略。
- memory 写入缺少敏感信息过滤和置信度。
- Runtime 偏厚，coordinator 边界还可以更清晰。
- approval / session 并发控制还不够强。

这些不是“功能没做完”，而是从本地 MVP 到真实多人 Agent 产品必须补的基础设施。

## 17. 如果把 CodeMuse 变成多人云端产品，第一件要重构什么？

**回答：**

第一件是执行隔离和状态存储。

本地 MVP 默认 workspace 在本机，数据在 `.data/codemuse`。云端产品必须先解决：

- tenant 隔离
- workspace 隔离
- sandbox 执行
- API key 和 secret 管理
- session/approval/checkpoint 的数据库化
- 审计日志不可篡改
- 后台任务队列

否则功能越多，风险越大。尤其 Coding Agent 有 shell、文件、网络和 extension 能力，不能先做多人共享 UI 再补安全。

## 18. 你会怎么做审计日志？哪些事件必须不可篡改？哪些数据需要脱敏？

**回答：**

审计日志应该记录所有会影响状态和外部世界的事件：

- user prompt metadata
- model selected tool call
- approval created / approved / rejected / invalid / stale
- effect preview digest
- tool execution start/end
- file write summary
- shell command summary
- web fetch target host
- checkpoint created / rewind
- config changed
- extension/MCP/subagent invoked

必须不可篡改：

- approval 决策
- effect digest
- tool arguments 摘要
- 文件 diff hash
- shell command hash
- 操作人、时间、session、workspace

需要脱敏：

- API key
- env
- cookie/header
- 文件内容中的 secret
- shell 输出里的 token
- 用户隐私文本

做法是事件日志 append-only，敏感字段只存 hash 或 redacted preview，完整内容按权限单独存储。

## 19. 前端模型配置页面怎么防止密钥泄漏给浏览器？

**回答：**

原则是：浏览器永远不拿真实 API key。

配置文件只保存：

```json
{
  "api_key_env": "CODEMUSE_API_KEY",
  "base_url": "...",
  "model": "...",
  "provider": "openai_compatible"
}
```

前端可以展示：

```text
provider
base_url
model
api_key_env
key 是否已配置
key 后四位 hash 或 masked 状态
```

但不能返回真实 key。保存 key 时也应该走服务端 secret store 或环境变量注入，而不是写进静态文件、前端 localStorage 或可下载配置。

此外，HTTP API 的 config response 要做字段级 redaction，测试里要断言不会泄漏 `api_key`。

## 20. 面试官说“这个项目像把很多概念堆了一遍，每个都不深”，你怎么反驳？

**回答：**

我会承认它不是生产级完整 Agent，但反驳“只是概念堆砌”。

因为这些模块不是孤立名词，而是跑在同一条主链路上：

```text
CLI / SDK / Web
-> build_agent
-> AgentRuntime
-> LLMProvider
-> ToolRegistry
-> ToolPolicyEvaluator
-> effect preview / approval
-> checkpoint
-> tool execution
-> role=tool observation
-> SessionStore / TimelineStore
-> MemoryContextProvider
```

可以现场演示：

- `python scripts/run_agent.py "list files"`
- `python scripts/run_agent.py "read README.md"`
- 写文件触发 approval
- approve 后执行并生成 checkpoint
- rewind 回退
- memory save/search
- repo blueprint 生成
- doctor / baseline eval
- Web API 读取 session events

我的重点不是每个方向都做到工业顶配，而是把 Coding Agent 的关键工程边界用可运行代码串起来，并且每个边界有测试和文档。这个项目更像 Agent 工程学习骨架，而不是一个只为 demo 拼起来的聊天 UI。

## 你应该能讲清楚的 6 件事

这一节是面试前的速记版。前面的 Q&A 更适合展开回答，这里更适合在面试官让你“讲一下项目”的时候作为主线。

### 1. Agent Runtime 如何跑一轮对话

**回答：**

一轮对话不是简单地把用户输入发给模型，而是一个状态机流程：

```text
用户输入
-> 追加 user message
-> AgentRuntime 进入 planning
-> 构造模型上下文
-> LLMProvider.complete(messages, tools)
-> 如果模型返回文本，写入 assistant message
-> 如果模型返回 tool_calls，逐个进入工具调度
-> 根据 ToolPolicyEvaluator 判断 allow / ask / deny
-> allow：checkpoint 后执行工具
-> ask：生成 effect preview，创建 pending approval，暂停
-> deny：写入 tool error observation
-> 工具结果统一写成 role=tool message
-> 保存 SessionStore
-> 写 TimelineStore
-> 如果还有工具结果，继续下一轮模型调用
-> 没有工具调用则结束
```

核心点是：Runtime 不是只负责“调用模型”，而是负责维护 Agent 的状态推进顺序。模型只提出计划，Runtime 决定能不能执行、什么时候暂停、怎么记录结果。

**可指代码：**

- `src/codemuse/runtime/runtime.py`
- `AgentRuntime.prompt(...)`
- `AgentRuntime._run_loop(...)`
- `AgentRuntime._messages_for_model(...)`

### 2. ToolRegistry 如何注册和执行工具

**回答：**

`ToolRegistry` 是模型能力和真实代码能力之间的边界。每个工具不是随便暴露一个 Python 函数，而是通过 `ToolSpec` 声明：

```text
name
description
parameters schema
permission_domain
requires_confirmation
sensitive
side_effect
model_callable
```

启动时，`app/bootstrap.py` 根据 workspace 和 config 注册工具：

```text
register_coding_tools
register_shell_tools
register_repo_tools
register_web_tools
register_file_memory_tools
register_skill_tools
register_extension_tools
register_mcp_tools
register_subagent_tools
```

模型看到的是工具 specs，真正执行时 Runtime 会通过 `ToolRegistry.get_spec(...)` 找到工具声明，再通过 `ToolRegistry.execute(...)` 调用工具。

这里的关键设计是：工具注册和工具执行是统一入口。这样本地工具、MCP 工具、skill、extension、subagent 都可以被放进同一个安全策略和审计流程里。

**可指代码：**

- `src/codemuse/app/bootstrap.py`
- `src/codemuse/tools/registry.py`
- `src/codemuse/tools/base.py`

### 3. Approval Gate 为什么必要

**回答：**

Coding Agent 和普通聊天机器人最大的区别是它会改变真实工作区：写文件、打 patch、跑 shell、访问网络、调用外部能力。模型可能理解错需求，也可能生成危险参数，所以不能让模型输出 tool call 后直接执行。

Approval Gate 的作用是把“模型想做什么”变成“用户看得懂、可批准、可拒绝、可审计”的动作：

```text
模型提出工具调用
-> Runtime 查 ToolSpec
-> Policy 判断 ask
-> effect preview 展示影响
-> effect digest 防止审批单被篡改
-> 用户 approve / reject
-> approve 前重新校验 preview 是否 stale
-> 通过后才执行
```

它不是为了增加交互步骤，而是为了建立责任边界：模型可以建议，用户批准副作用，Runtime 负责强制执行这个规则。

**典型需要 approval 的操作：**

- 写文件
- 替换文本
- 应用 patch
- shell 命令
- web fetch
- extension / MCP 外部能力

### 4. Session / Checkpoint / Rewind 如何帮助 Coding Agent 安全修改代码

**回答：**

Session、Checkpoint、Rewind 分别解决三个问题：

```text
Session：
  保存对话消息、tool observation 和系统提示，让 Agent 有连续上下文。

Checkpoint：
  在副作用工具执行前保存当前会话和 workspace 快照。

Rewind：
  当修改结果不符合预期时，把会话和 workspace 恢复到某个 checkpoint。
```

它们一起提供的是“可恢复性”。Coding Agent 不可能保证每次修改都正确，所以系统必须允许用户回退。

举例：

```text
用户让 Agent 修改 app.js
-> 模型调用 replace_text
-> approval 通过
-> Runtime 在执行前创建 checkpoint
-> 工具修改 app.js
-> 用户发现改错
-> rewind 到 checkpoint
-> app.js 和会话状态恢复
```

边界也要讲清楚：checkpoint 主要保护 workspace 文件和会话状态，不能回滚网络请求、数据库写入、全局环境污染或 workspace 外部文件修改。

**可指代码：**

- `src/codemuse/storage/sessions.py`
- `src/codemuse/storage/checkpoints.py`
- `src/codemuse/runtime/git_checkpoint.py`
- `src/codemuse/runtime/safe_rewind.py`

### 5. Memory 如何检索并进入上下文

**回答：**

Memory 不是把所有历史原样塞回 prompt，而是先检索，再构造成可控的 recall snippet，最后作为 system/context message 注入模型上下文。

流程是：

```text
最新用户请求
-> MemoryContextProvider.transform_context(...)
-> 搜索 project memory / blueprint memory / file memory
-> 对命中结果排序和截断
-> build_memory_recall_text(...)
-> 构造 memory recall snippet
-> 插入 messages
-> LLMProvider.complete(...)
```

这样做有几个原因：

- 控制 token，避免把大量历史塞进上下文。
- 给模型明确提示：这是检索到的项目记忆，不是当前用户新指令。
- 保留来源和类别，方便模型判断可信度。
- 避免 memory 污染主对话，把短期消息和长期知识分开。
- 可以在 recall 阶段做脱敏、去重、排序和摘要。

面试里可以强调：Memory 的关键不是“存进去”，而是“以可控格式召回并进入上下文”。

**可指代码：**

- `src/codemuse/memory/retrieval_hook.py`
- `src/codemuse/memory/recall_builder.py`
- `src/codemuse/memory/retrieval.py`
- `src/codemuse/memory/blueprint_memory.py`

### 6. MCP / SubAgent 如何扩展 Agent 能力边界

**回答：**

MCP 和 SubAgent 都是扩展能力边界，但扩展方式不同。

MCP 解决的是“接入外部工具生态”：

```text
mcp config
-> MCPManager
-> discover tools
-> MCPToolAdapter
-> register into ToolRegistry
-> Runtime 像普通工具一样调度
```

SubAgent 解决的是“把复杂任务拆给受控子 Agent”：

```text
父 Agent 调用 spawn_subagent
-> SubAgentManager 创建 child runtime
-> child runtime 只拿 allowlist 工具
-> child session 独立记录
-> 子任务结果作为 tool result 回到父 Agent
```

关键是：扩展能力不等于绕过安全边界。MCP 工具和 SubAgent 都必须继续走 ToolRegistry、ToolSpec、Policy、approval 和审计。SubAgent 还必须有工具白名单和产物边界，否则它就会变成一个绕过主 Agent 安全策略的后门。

**可指代码：**

- `src/codemuse/mcp/manager.py`
- `src/codemuse/mcp/adapter.py`
- `src/codemuse/subagents/manager.py`
- `src/codemuse/tools/subagent_tool.py`

## 自测追问和参考答案

### 1. 能不能不用源码，画出 `CLI/TUI -> SessionHost -> AgentRuntime -> ToolRegistry -> Storage` 主链路？

**回答：**

可以画成这样：

```text
CLI / TUI / Web / SDK
        |
        v
SessionHost / SessionManager
        |
        v
AgentRuntime
        |
        +--> LLMProvider
        |
        +--> ToolRegistry
        |        |
        |        +--> File tools
        |        +--> Shell tools
        |        +--> Repo tools
        |        +--> Memory tools
        |        +--> MCP tools
        |        +--> SubAgent tools
        |
        +--> ToolPolicyEvaluator
        |
        +--> ApprovalStore
        +--> CheckpointStore
        +--> SessionStore
        +--> TimelineStore
        +--> MemoryStore
```

如果按一次请求讲：

```text
入口层接收用户请求
-> SessionHost 找到或创建 session
-> AgentRuntime 接管一轮 turn
-> Runtime 把工具 specs 给模型
-> 模型返回文本或 tool calls
-> Runtime 通过 ToolRegistry 找工具
-> Policy 决定 allow / ask / deny
-> 工具结果写回 messages
-> Storage 持久化 session、timeline、approval、checkpoint
```

CodeMuse 里没有把所有入口都写成同一个类名 `SessionHost`，但这个抽象对应的是 CLI/SDK/Web session 管理到 Runtime 的连接层，比如 SDK 的 `build_agent(...)` 和 Web 的 `WebSessionManager`。

### 2. 能不能说明“工具能被模型调用”和“工具这次允许执行”不是一回事？

**回答：**

这两件事必须分开。

“工具能被模型调用”指的是工具进入了模型可见的 tool specs：

```text
model_callable=True
工具已注册
schema 可被模型看到
模型可以生成这个 tool call
```

“工具这次允许执行”指的是 Runtime 在拿到具体 tool call 和参数之后，经过策略判断：

```text
ToolSpec
+ permission_domain
+ requires_confirmation
+ side_effect
+ sensitive
+ 当前参数的 effect preview
+ approval 状态
```

之后才决定 allow、ask 或 deny。

举例：

```text
write_file 是 model-callable。
模型可以请求 write_file("README.md", "...")。
但因为它有 side_effect / write domain，这次执行必须先 approval。
```

所以模型可见不等于模型有权直接执行。这个区分是 Agent 安全的核心。

### 3. 能不能举一个需要 approval gate 的文件修改例子？

**回答：**

例子：用户让 Agent 修改 `src/codemuse/web/static/app.js`，把某个按钮文案或 API 调用逻辑改掉。

流程是：

```text
模型生成 replace_text 或 apply_patch
-> Runtime 查 ToolSpec，发现是 write side effect
-> Policy 返回 ask
-> tools.effects 读取当前 app.js
-> 生成 unified diff、before_sha256、after_sha256、字符变化
-> ApprovalStore 创建 pending approval
-> 前端或 CLI 展示 diff
-> 用户 approve
-> approve 时重新计算 preview，确认 app.js 没被别人改过
-> 创建 checkpoint
-> 执行 replace_text / apply_patch
-> tool result 写回 messages
```

如果用户批准前 `app.js` 已经被手动改过，`before_sha256` 不匹配，approval 会变成 stale，不会执行旧 diff。

这个例子能说明 approval gate 不只是“点确认”，而是“可见 diff + 防篡改 + 防过期 + 可回退”的组合。

### 4. 能不能说明 memory 检索结果为什么要先构造成 recall snippet，再进入上下文？

**回答：**

因为检索结果不能原样塞给模型。原始 memory 可能太长、重复、来源混杂，甚至包含不应该进入当前任务的信息。

构造成 recall snippet 有几个目的：

```text
压缩：
  只保留和当前请求相关的片段，控制 token。

分区：
  明确告诉模型这是 recalled memory，不是用户新指令。

排序：
  把最相关、最新、置信度更高的内容放前面。

来源：
  保留 source path、category、memory id，方便模型引用和判断。

安全：
  可以在进入上下文前做敏感信息过滤和去重。
```

如果不做 snippet，而是把记忆原文全部塞进去，模型可能把旧偏好当成当前命令，也可能被低质量记忆误导。

### 5. 能不能讲清楚 SubAgent 为什么仍然需要工具白名单和产物边界？

**回答：**

需要。SubAgent 虽然是子 Agent，但它仍然是模型驱动的执行体。只要它能调用工具，就有误操作和越权风险。

如果父 Agent 可以 spawn 一个不受限制的 SubAgent，而 SubAgent 又能访问所有工具，那安全策略就被绕开了：

```text
父 Agent 不直接调用危险工具
-> 让 SubAgent 调用危险工具
-> 等于绕过主 Runtime 的权限设计
```

所以 SubAgent 必须受两个边界限制：

```text
工具白名单：
  子 Agent 只能拿到任务需要的工具，比如 read/search，不能默认拿 write/shell/network。

产物边界：
  子 Agent 的输出必须是结构化结果、报告、计划或受控文件路径，不能直接无限制修改父 workspace。
```

在 CodeMuse 里，SubAgent 通过 `spawn_subagent` 作为工具进入主 Runtime，子 Agent 由 `SubAgentManager` 创建，并使用受限 registry。这样它是扩展任务能力，而不是逃逸安全边界。

## 面试时的收束表达

可以用这段作为最后总结：

> CodeMuse 当前最有价值的地方，是它把 Coding Agent 的主链路拆清楚了：Runtime 负责状态推进，ToolRegistry 负责能力边界，Policy/Approval 负责副作用控制，Checkpoint 负责误操作恢复，Memory 负责长期上下文，Timeline 负责可审计过程。它还不是生产级云端 Agent，但已经具备从本地 MVP 演进到产品的骨架。
