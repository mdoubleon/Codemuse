"""实现可预期的本地假模型，用规则模拟文本回复和工具调用。"""
from __future__ import annotations

import re
import uuid

from codemuse.domain.messages import ChatMessage
from codemuse.domain.tools import ToolCall, ToolSpec
from codemuse.llm.models import LLMResponse
from codemuse.llm.provider.base import LLMProviderInfo
from codemuse.memory.retrieval_hook import MEMORY_RECALL_METADATA_KEY


class FakeLLM:
    """用规则模拟 LLM 的本地 provider，使测试和教学不依赖网络。"""

    def __init__(self, *, model: str = "fake-local") -> None:
        """初始化这个对象后续运行需要的具体依赖和缓存状态。"""
        self._info = LLMProviderInfo(provider="fake", model=model, supports_tools=True)

    @property
    def info(self) -> LLMProviderInfo:
        """返回 provider 或工具的基础元信息。"""
        return self._info

    def complete(self, messages: list[ChatMessage], tools: list[ToolSpec]) -> LLMResponse:
        """根据 messages 和 tools 生成模型回复或工具调用。"""
        last = messages[-1]
        if last.role == "tool":
            return LLMResponse(text=self._answer_from_tool(last))
        text = last.text_content().strip()
        lowered = text.lower()
        # 用户明确要求应用补丁时优先选择 apply_patch，避免补丁正文里的关键词误触发记忆工具。
        if self._asks_to_apply_patch(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "apply_patch",
                        {"patch": self._extract_patch_text(text), "create_dirs": True},
                    )
                ]
            )
        if self._asks_to_run_shell(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "run_shell",
                        {
                            "command": self._extract_shell_command(text),
                            "timeout_seconds": self._extract_timeout_seconds(text),
                            "max_output_chars": 8000,
                        },
                    )
                ]
            )
        if self._asks_to_fetch_web(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "web_fetch",
                        {
                            "url": self._extract_url(text),
                            "max_chars": self._extract_max_chars(text),
                            "timeout_seconds": 10,
                        },
                    )
                ]
            )
        if self._asks_to_import_repository(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "import_repository",
                        {
                            "source": self._extract_repo_source(text),
                            "destination": self._extract_destination(text),
                            "allow_network": "allow_network=true" in lowered or "allow network" in lowered,
                            "overwrite": "overwrite=true" in lowered or "overwrite" in lowered,
                        },
                    )
                ]
            )
        if self._asks_for_repo_status(lowered):
            return LLMResponse(tool_calls=[self._tool_call("repo_git_status", {"path": ".", "include_diff": "diff" in lowered})])
        if self._asks_for_repo_cache(lowered):
            return LLMResponse(tool_calls=[self._tool_call("list_repo_cache", {})])
        if self._asks_for_repo_import(lowered):
            return LLMResponse(tool_calls=[self._tool_call("prepare_repo_import", {"source": self._extract_repo_source(text)})])
        if self._asks_for_project_plan(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "build_project_plan",
                        {"path": ".", "goal": self._extract_plan_goal(text), "max_depth": 4},
                    )
                ]
            )
        if self._asks_for_blueprint_search(lowered):
            return LLMResponse(tool_calls=[self._tool_call("search_blueprint_memory", {"query": self._extract_search_query(text), "limit": 5})])
        if self._asks_for_dynamic_extension_tool(lowered):
            extension_tool = next((tool for tool in tools if tool.name.startswith("extension__")), None)
            if extension_tool is not None:
                return LLMResponse(tool_calls=[self._tool_call(extension_tool.name, {"input": text})])
        if self._asks_for_subagent_plan(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "run_subagent_plan",
                        {"agent": "repo-researcher", "tasks": ["list files", "search ToolRegistry"], "max_turns": 2},
                    )
                ]
            )
        if self._asks_for_subagent(lowered):
            return LLMResponse(tool_calls=[self._tool_call("spawn_subagent", {"agent": "repo-researcher", "task": self._subagent_task(text), "max_turns": 2})])
        if self._asks_for_project_memory_search(lowered):
            return LLMResponse(tool_calls=[self._tool_call("search_project_memory", {"query": self._extract_search_query(text), "limit": 5})])
        if self._asks_to_save_project_memory(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "save_project_memory",
                        {
                            "title": self._memory_title(text),
                            "content": text,
                            "category": "learning",
                            "tags": ["manual", "learning"],
                        },
                    )
                ]
            )
        if self._asks_to_save_blueprint(lowered):
            return LLMResponse(tool_calls=[self._tool_call("save_blueprint_memory", {"path": ".", "max_depth": 4})])
        if self._asks_for_blueprint_analysis(lowered):
            return LLMResponse(tool_calls=[self._tool_call("analyze_repo_blueprint", {"path": ".", "max_depth": 4})])
        if self._asks_for_repo_index(lowered):
            return LLMResponse(tool_calls=[self._tool_call("index_repo_structure", {"path": ".", "max_depth": 4})])
        if self._asks_for_file_list(lowered):
            return LLMResponse(tool_calls=[self._tool_call("list_files", {"path": ".", "max_depth": 2})])
        if self._asks_to_replace_text(lowered):
            path = self._extract_path(text) or "README.md"
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "replace_text",
                        {
                            "path": path,
                            "old_text": self._extract_replace_old_text(text),
                            "new_text": self._extract_replace_new_text(text),
                            "replace_all": self._extract_replace_all(text),
                        },
                    )
                ]
            )
        if self._asks_to_write_file(lowered):
            path = self._extract_path(text) or "codemuse-note.txt"
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "write_file",
                        {
                            "path": path,
                            "content": self._extract_write_content(text),
                            "create_dirs": True,
                            "overwrite": True,
                        },
                    )
                ]
            )
        if self._asks_to_read_file(lowered):
            path = self._extract_path(text) or "README.md"
            return LLMResponse(tool_calls=[self._tool_call("read_file", {"path": path})])
        if lowered.startswith("search ") or "搜索" in lowered:
            query = text.split(" ", 1)[1] if lowered.startswith("search ") and " " in text else text.replace("搜索", "").strip()
            return LLMResponse(tool_calls=[self._tool_call("search_text", {"query": query or text})])
        if self._asks_for_mcp_tool(lowered) and "status" in lowered:
            return LLMResponse(tool_calls=[self._tool_call("mcp_status", {})])
        if self._asks_for_mcp_tool(lowered):
            mcp_tool = next((tool for tool in tools if tool.name.startswith("mcp__")), None)
            if mcp_tool is not None:
                # FakeLLM 只是教学用：真实 LLM 会根据工具 schema 决定参数。
                return LLMResponse(tool_calls=[self._tool_call(mcp_tool.name, {"text": text, "query": text})])
        if self._asks_for_subagent_plan(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "run_subagent_plan",
                        {"agent": "repo-researcher", "tasks": ["list files", "search ToolRegistry"], "max_turns": 2},
                    )
                ]
            )
        if self._asks_to_run_skill(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "run_skill",
                        {"name": self._extract_named_target(text, default="experiment-report"), "task": text},
                    )
                ]
            )
        if self._asks_to_run_extension(lowered):
            return LLMResponse(
                tool_calls=[
                    self._tool_call(
                        "run_extension",
                        {
                            "name": self._extract_named_target(text, default="project-extension"),
                            "action": "default",
                            "input": text,
                        },
                    )
                ]
            )
        memory_context = self._memory_context(messages)
        if memory_context:
            return LLMResponse(text=f"I found relevant memory for this request:\n\n{memory_context}")
        return LLMResponse(text="I can help inspect files, search text, and later analyze repositories into blueprints.")

    @staticmethod
    def _tool_call(name: str, arguments: dict) -> ToolCall:
        """为 FakeLLM 构造带随机 id 的工具调用对象。"""
        return ToolCall(id=str(uuid.uuid4()), name=name, arguments=arguments)

    @staticmethod
    def _asks_for_repo_import(lowered: str) -> bool:
        """判断用户输入是否在请求生成仓库导入计划。"""
        return any(
            item in lowered
            for item in [
                "repo import",
                "import repo",
                "github import",
                "prepare repo import",
                "import github",
            ]
        )

    @staticmethod
    def _asks_to_import_repository(lowered: str) -> bool:
        """判断用户输入是否在请求执行已批准的仓库导入。"""
        return any(item in lowered for item in ["import repository", "approved import", "clone repository", "导入仓库"])

    @staticmethod
    def _asks_for_repo_status(lowered: str) -> bool:
        """判断用户输入是否在请求查看仓库 Git 状态或 diff。"""
        return any(item in lowered for item in ["repo status", "git status", "repo diff", "git diff"])

    @staticmethod
    def _asks_for_repo_cache(lowered: str) -> bool:
        """判断用户输入是否在请求查看仓库导入缓存。"""
        return any(item in lowered for item in ["repo cache", "list repo cache", "import cache"])

    @staticmethod
    def _asks_for_project_plan(lowered: str) -> bool:
        """判断用户是否请求for项目计划?"""
        return any(
            item in lowered
            for item in [
                "project plan",
                "task breakdown",
                "blueprint plan",
                "build project plan",
                "implementation plan",
            ]
        )

    @staticmethod
    def _asks_for_repo_index(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(item in lowered for item in ["index repo", "索引仓库", "索引项目"])

    @staticmethod
    def _asks_for_blueprint_analysis(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(
            item in lowered
            for item in [
                "repo blueprint",
                "blueprint",
                "minimal architecture",
                "analyze repo",
                "analyze project",
                "架构蓝图",
                "最小架构",
                "分析仓库",
                "拆解仓库",
                "分析项目",
                "拆解项目",
            ]
        )

    @staticmethod
    def _asks_to_save_blueprint(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(
            item in lowered
            for item in [
                "save blueprint",
                "learn repo",
                "learn project",
                "save memory",
                "学习仓库",
                "学习项目",
                "保存记忆",
                "作为记忆",
                "沉淀",
            ]
        )

    @staticmethod
    def _asks_for_blueprint_search(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(
            item in lowered
            for item in [
                "search blueprint",
                "search memory",
                "recall blueprint",
                "搜索蓝图",
                "搜索记忆",
                "召回蓝图",
                "召回记忆",
            ]
        )

    @staticmethod
    def _asks_to_save_project_memory(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(item in lowered for item in ["save project memory", "remember this", "记住这个", "保存项目记忆", "保存学习记忆"])

    @staticmethod
    def _asks_for_project_memory_search(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(item in lowered for item in ["search project memory", "recall project memory", "搜索项目记忆", "召回项目记忆", "搜索学习记忆"])

    @staticmethod
    def _asks_for_file_list(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(item in lowered for item in ["list files", "show files", "项目结构", "文件结构", "列出文件"])

    @staticmethod
    def _asks_to_write_file(lowered: str) -> bool:
        """判断用户是否希望 Agent 写入或创建 workspace 文件。"""
        return any(item in lowered for item in ["write file", "create file", "写文件", "创建文件", "新增文件"])

    @staticmethod
    def _asks_to_replace_text(lowered: str) -> bool:
        """判断用户是否希望 Agent 在已有文件中替换一段文本。"""
        return any(item in lowered for item in ["replace text", "replace_text", "替换文本", "替换文件文本"])

    @staticmethod
    def _asks_to_apply_patch(lowered: str) -> bool:
        """判断用户是否希望 Agent 应用 unified diff patch。"""
        return any(item in lowered for item in ["apply patch", "patch file", "应用补丁", "应用patch"])

    @staticmethod
    def _asks_to_run_shell(lowered: str) -> bool:
        """判断用户是否希望 Agent 执行 shell 命令。"""
        return any(item in lowered for item in ["run shell", "run command", "shell command", "执行命令", "运行命令"])

    @staticmethod
    def _asks_to_fetch_web(lowered: str) -> bool:
        """判断用户是否希望 Agent 静态获取网页内容。"""
        return any(item in lowered for item in ["web fetch", "fetch url", "fetch web", "抓取网页", "获取网页"])

    @staticmethod
    def _asks_for_mcp_tool(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(item in lowered for item in ["mcp", "外部工具", "external tool"])

    @staticmethod
    def _asks_to_run_skill(lowered: str) -> bool:
        """判断用户是否希望运行 workspace skill。"""
        return any(item in lowered for item in ["run skill", "use skill", "执行技能", "使用技能"])

    @staticmethod
    def _asks_to_run_extension(lowered: str) -> bool:
        """判断用户是否希望运行 workspace extension。"""
        return any(item in lowered for item in ["run extension", "use extension", "执行扩展", "使用扩展"])

    @staticmethod
    def _asks_for_subagent(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(item in lowered for item in ["subagent", "子agent", "子代理", "派生一个", "让子任务"])

    @staticmethod
    def _asks_for_subagent_plan(lowered: str) -> bool:
        """判断用户是否请求for子 Agent计划?"""
        return any(item in lowered for item in ["subagent plan", "multi subagent", "run subagent plan"])

    @staticmethod
    def _asks_for_dynamic_extension_tool(lowered: str) -> bool:
        """判断用户是否请求for动态扩展工具?"""
        return any(item in lowered for item in ["extension tool", "dynamic extension tool"])

    @staticmethod
    def _asks_to_read_file(lowered: str) -> bool:
        """判断用户输入是否表达了某类工具调用意图。"""
        return any(item in lowered for item in ["read ", "读取", "看一下", "打开"])

    @staticmethod
    def _extract_path(text: str) -> str | None:
        """从用户输入或文本中提取后续处理需要的字段。"""
        match = re.search(r"([\w./\\-]+\.(?:md|py|txt|json|toml|yaml|yml|js|ts|tsx|jsx|rs|go|java))", text)
        if match:
            return match.group(1).replace("\\", "/")
        return None

    @staticmethod
    def _extract_search_query(text: str) -> str:
        """从用户输入中提取记忆或仓库搜索查询。"""
        cleaned = text
        for marker in [
            "search blueprint",
            "search memory",
            "recall blueprint",
            "search project memory",
            "recall project memory",
            "搜索蓝图",
            "搜索记忆",
            "召回蓝图",
            "召回记忆",
            "搜索项目记忆",
            "召回项目记忆",
            "搜索学习记忆",
        ]:
            cleaned = re.sub(re.escape(marker), "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" ：:") or text

    @staticmethod
    def _extract_write_content(text: str) -> str:
        """从教学 prompt 中提取 write_file 要写入的内容。"""
        match = re.search(r"(?:content|内容)\s*[:：]\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip() + "\n"
        return "Generated by CodeMuse.\n"

    @staticmethod
    def _extract_replace_old_text(text: str) -> str:
        """从教学 prompt 中提取 replace_text 要查找的旧文本。"""
        match = re.search(
            r"(?:old_text|old|from|原文|旧文本)\s*[:：]\s*(.+?)(?=\s*(?:new_text|new|to|新文|新文本)\s*[:：])",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip()
        return "Generated by CodeMuse."

    @staticmethod
    def _extract_replace_new_text(text: str) -> str:
        """从教学 prompt 中提取 replace_text 要写入的新文本。"""
        match = re.search(r"(?:new_text|new|to|新文|新文本)\s*[:：]\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return "Updated by CodeMuse."

    @staticmethod
    def _extract_replace_all(text: str) -> bool:
        """从教学 prompt 中识别是否希望替换所有匹配项。"""
        if re.search(r"replace_all\s*[:=：]\s*(?:false|no|0|否)", text, flags=re.IGNORECASE):
            return False
        if re.search(r"replace_all\s*[:=：]\s*(?:true|yes|1|是)", text, flags=re.IGNORECASE):
            return True
        lowered = text.lower()
        return any(item in lowered for item in ["replace all", "替换全部", "全部替换", "全局替换"])

    @staticmethod
    def _extract_patch_text(text: str) -> str:
        """从教学 prompt 中提取 apply_patch 要应用的 unified diff。"""
        match = re.search(r"(?:patch|补丁)\s*[:：]\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def _extract_shell_command(text: str) -> str:
        """从教学 prompt 中提取 shell 命令正文。"""
        match = re.search(
            r"(?:run shell|run command|shell command|command|执行命令|运行命令)\s*[:：]\s*(.*)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            command = match.group(1).strip()
            command = re.sub(r"\s+timeout\s*[:=：]\s*\d+\s*$", "", command, flags=re.IGNORECASE)
            return command.strip()
        return text

    @staticmethod
    def _extract_timeout_seconds(text: str) -> int:
        """从教学 prompt 中提取 shell 超时时间，默认 30 秒。"""
        match = re.search(r"timeout\s*[:=：]\s*(\d+)", text, flags=re.IGNORECASE)
        if not match:
            return 30
        return max(1, min(60, int(match.group(1))))

    @staticmethod
    def _extract_repo_source(text: str) -> str:
        """提取仓库源码。"""
        url = re.search(r"https?://[^\s\"']+", text)
        if url:
            return url.group(0).rstrip("),.;")
        ssh = re.search(r"git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", text)
        if ssh:
            return ssh.group(0)
        shorthand = re.search(r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?\b", text)
        if shorthand:
            return shorthand.group(0)
        cleaned = text
        for marker in [
            "import repository",
            "clone repository",
            "prepare repo import",
            "github import",
            "repo import",
            "import github",
            "import repo",
            "approved import",
        ]:
            cleaned = re.sub(re.escape(marker), "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" :") or "."

    @staticmethod
    def _extract_destination(text: str) -> str:
        """提取目标路径。"""
        match = re.search(r"(?:destination|dest):\s*([^\s]+)", text, re.IGNORECASE)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_plan_goal(text: str) -> str:
        """提取计划目标。"""
        cleaned = text
        for marker in ["build project plan", "project plan", "task breakdown", "blueprint plan", "implementation plan"]:
            cleaned = re.sub(re.escape(marker), "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*(goal|for)\s*[:=]\s*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" :") or "Understand and evolve this repository safely."

    @staticmethod
    def _extract_url(text: str) -> str:
        """从教学 prompt 中提取 URL。"""
        match = re.search(r"https?://[^\s\"']+", text)
        if match:
            return match.group(0).rstrip("，,。)")
        return text.strip()

    @staticmethod
    def _extract_named_target(text: str, *, default: str) -> str:
        """Extract a named skill/extension target from teaching prompts."""
        match = re.search(r"(?:name|skill|extension)\s*[:：]\s*([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        for token in re.findall(r"[A-Za-z0-9_.-]+", text):
            if "-" in token and token.lower() not in {"run-skill", "run-extension"}:
                return token
        return default

    @staticmethod
    def _extract_max_chars(text: str) -> int:
        """从教学 prompt 中提取网页文本截断长度。"""
        match = re.search(r"max_chars\s*[:=：]\s*(\d+)", text, flags=re.IGNORECASE)
        if not match:
            return 4000
        return max(500, min(20000, int(match.group(1))))

    @staticmethod
    def _memory_title(text: str) -> str:
        """根据用户输入生成项目记忆的简短标题。"""
        cleaned = re.sub(r"(?i)save project memory|remember this", "", text)
        cleaned = cleaned.replace("记住这个", "").replace("保存项目记忆", "").replace("保存学习记忆", "")
        cleaned = cleaned.strip(" ：:")
        return cleaned[:60] or "Project memory"

    @staticmethod
    def _subagent_task(text: str) -> str:
        """从用户输入中提取要交给子 Agent 的任务文本。"""
        cleaned = re.sub(r"(?i)use subagent|spawn subagent|subagent", "", text)
        cleaned = cleaned.replace("子agent", "").replace("子代理", "").replace("派生一个", "").replace("让子任务", "")
        cleaned = cleaned.strip(" ：:")
        return cleaned or "list files"

    @staticmethod
    def _answer_from_tool(message: ChatMessage) -> str:
        """把工具 observation 转换成 FakeLLM 的最终文本回复。"""
        tool_name = message.tool_name or "tool"
        content = message.text_content().strip()
        preview = content[:1200]
        if len(content) > len(preview):
            preview += "\n..."
        if tool_name == "save_blueprint_memory":
            return f"Saved repository blueprint memory:\n\n{preview}"
        if tool_name == "search_blueprint_memory":
            return f"Blueprint memory search results:\n\n{preview}"
        if tool_name == "save_project_memory":
            return f"Saved project memory:\n\n{preview}"
        if tool_name == "search_project_memory":
            return f"Project memory search results:\n\n{preview}"
        if tool_name == "spawn_subagent":
            return f"Subagent result:\n\n{preview}"
        if tool_name == "run_subagent_plan":
            return f"Subagent plan result:\n\n{preview}"
        if tool_name == "mcp_status":
            return f"MCP status:\n\n{preview}"
        if tool_name == "prepare_repo_import":
            return f"Repository import plan:\n\n{preview}"
        if tool_name == "import_repository":
            return f"Imported repository:\n\n{preview}"
        if tool_name == "repo_git_status":
            return f"Repository git status:\n\n{preview}"
        if tool_name == "list_repo_cache":
            return f"Repository cache:\n\n{preview}"
        if tool_name == "build_project_plan":
            return f"Project plan:\n\n{preview}"
        if tool_name == "analyze_repo_blueprint":
            return f"Repository blueprint analysis:\n\n{preview}"
        if tool_name == "run_skill":
            return f"Skill runtime result:\n\n{preview}"
        if tool_name == "run_extension":
            return f"Extension runtime result:\n\n{preview}"
        return f"Tool `{tool_name}` returned:\n\n{preview}"

    @staticmethod
    def _memory_context(messages: list[ChatMessage]) -> str:
        """从系统消息中提取已注入的记忆召回上下文。"""
        for message in messages:
            if message.role != "system":
                continue
            if MEMORY_RECALL_METADATA_KEY not in message.metadata:
                continue
            content = message.text_content().strip()
            return content[:1200] + ("\n..." if len(content) > 1200 else "")
        return ""

