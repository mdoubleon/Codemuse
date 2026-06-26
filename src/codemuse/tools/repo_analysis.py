"""根据仓库索引和 README 推断最小架构蓝图。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from codemuse.domain.blueprint import BlueprintMemoryItem, ModuleSummary, RepoBlueprint, RepoIndex
from codemuse.tools.repo_index import index_local_repo

MODULE_ROLE_HINTS = {
    "api": "External API and SDK boundary.",
    "app": "Application assembly and runtime bootstrap.",
    "agent": "Agent orchestration and reasoning flow.",
    "blueprint": "Repository learning, structure analysis, and reusable architecture summaries.",
    "cli": "Command-line user interface.",
    "config": "Configuration schema and runtime overrides.",
    "domain": "Shared domain data models.",
    "docs": "Human-facing design notes and learning material.",
    "llm": "Model adapter and provider boundary.",
    "memory": "Long-term memory, retrieval, indexing, and recall.",
    "prompts": "Prompt templates and system instructions.",
    "runtime": "Core turn loop, state, events, and tool execution flow.",
    "scripts": "Developer entrypoints and smoke-run helpers.",
    "server": "HTTP backend and session-facing server layer.",
    "storage": "Local persistence for sessions, checkpoints, memory, and settings.",
    "subagents": "Bounded child-agent orchestration.",
    "tests": "Regression and architecture verification.",
    "tools": "Agent-callable tools and their safety boundary.",
    "tui": "Terminal UI layer.",
    "web": "Browser UI layer.",
    "web_tools": "Web fetch/search capability boundary.",
}


def build_repo_blueprint(
    root: Path,
    *,
    repo_id: str | None = None,
    max_files: int = 1200,
    max_depth: int = 4,
) -> RepoBlueprint:
    """先建立 RepoIndex，再基于索引推断仓库蓝图。"""
    index = index_local_repo(root, repo_id=repo_id, max_files=max_files, max_depth=max_depth)
    return analyze_repo_index(index)


def analyze_repo_index(index: RepoIndex) -> RepoBlueprint:
    """把 RepoIndex 中的文件线索整理成 RepoBlueprint。"""
    root = Path(index.root_path)
    title = _infer_title(root, index.repo_id)
    problem_statement = _infer_problem_statement(root, index)
    modules = _infer_modules(root, index)
    tech_stack = _infer_tech_stack(root, index)
    minimal_architecture = _infer_minimal_architecture(index, modules)
    data_flow = _infer_data_flow(index, modules)
    reusable_patterns = _infer_reusable_patterns(index, modules)
    learning_notes = _infer_learning_notes(index, modules)
    key_files = _unique(index.entrypoints + index.package_files + index.config_files + index.agent_related_files + index.important_files)[:40]
    blueprint_id = _stable_id(index.repo_id, title, ",".join(key_files), str(index.file_count))

    return RepoBlueprint(
        blueprint_id=blueprint_id,
        repo_id=index.repo_id,
        source_root=index.root_path,
        title=title,
        problem_statement=problem_statement,
        tech_stack=tech_stack,
        minimal_architecture=minimal_architecture,
        modules=modules,
        data_flow=data_flow,
        reusable_patterns=reusable_patterns,
        learning_notes=learning_notes,
        key_files=key_files,
    )


def blueprint_to_memory_items(blueprint: RepoBlueprint) -> list[BlueprintMemoryItem]:
    """把一份 RepoBlueprint 拆成多条可检索的蓝图记忆。"""
    chunks = [
        (
            "architecture",
            "Minimal architecture",
            "\n".join(blueprint.minimal_architecture),
            ["architecture", "minimal", blueprint.repo_id],
            blueprint.key_files,
        ),
        (
            "module_map",
            "Module responsibility map",
            "\n".join(f"- {module.path}: {module.role}" for module in blueprint.modules),
            ["modules", "responsibility", blueprint.repo_id],
            [module.path for module in blueprint.modules],
        ),
        (
            "tech_stack",
            "Tech stack clues",
            ", ".join(blueprint.tech_stack) or "No strong tech-stack signals found.",
            ["tech_stack", blueprint.repo_id],
            blueprint.key_files,
        ),
        (
            "data_flow",
            "Control/data flow",
            "\n".join(blueprint.data_flow),
            ["flow", "runtime", blueprint.repo_id],
            blueprint.key_files,
        ),
        (
            "reusable_patterns",
            "Reusable project ideas",
            "\n".join(blueprint.reusable_patterns + blueprint.learning_notes),
            ["reuse", "learning", blueprint.repo_id],
            blueprint.key_files,
        ),
    ]
    items: list[BlueprintMemoryItem] = []
    for category, title, content, tags, source_paths in chunks:
        memory_id = _stable_id(blueprint.blueprint_id, category, content)
        items.append(
            BlueprintMemoryItem(
                memory_id=memory_id,
                blueprint_id=blueprint.blueprint_id,
                repo_id=blueprint.repo_id,
                category=category,
                title=f"{blueprint.title}: {title}",
                content=content,
                tags=tags,
                source_paths=source_paths[:20],
            )
        )
    return items


def format_blueprint_report(blueprint: RepoBlueprint) -> str:
    """把 RepoBlueprint 转成分段的架构学习报告。"""
    lines = [
        f"# Repo Blueprint: {blueprint.title}",
        "",
        f"- blueprint_id: {blueprint.blueprint_id}",
        f"- repo_id: {blueprint.repo_id}",
        f"- source_root: {blueprint.source_root}",
        "",
        "## Problem Statement",
        blueprint.problem_statement or "No README-style problem statement found.",
        "",
        "## Tech Stack",
        _bullet_list(blueprint.tech_stack),
        "",
        "## Minimal Architecture",
        _bullet_list(blueprint.minimal_architecture),
        "",
        "## Module Map",
    ]
    if blueprint.modules:
        for module in blueprint.modules:
            signal_text = f" Signals: {', '.join(module.signals[:4])}." if module.signals else ""
            lines.append(f"- `{module.path}`: {module.role}{signal_text}")
    else:
        lines.append("- No clear module boundaries detected.")
    lines.extend(
        [
            "",
            "## Data Flow",
            _bullet_list(blueprint.data_flow),
            "",
            "## Reusable Patterns",
            _bullet_list(blueprint.reusable_patterns),
            "",
            "## Learning Notes",
            _bullet_list(blueprint.learning_notes),
            "",
            "## Key Files",
            _bullet_list(blueprint.key_files),
        ]
    )
    return "\n".join(lines)


def _infer_title(root: Path, fallback: str) -> str:
    """根据仓库索引和文件线索推断架构信息。"""
    readme = _read_readme(root)
    if readme:
        for line in readme.splitlines():
            cleaned = line.strip().lstrip("\ufeff")
            if cleaned.startswith("#"):
                return cleaned.lstrip("#").strip() or fallback
    return fallback


def _infer_problem_statement(root: Path, index: RepoIndex) -> str:
    """根据仓库索引和文件线索推断架构信息。"""
    readme = _read_readme(root)
    if readme:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", readme) if item.strip()]
        for paragraph in paragraphs:
            paragraph = paragraph.lstrip("\ufeff")
            if paragraph.startswith("#") or paragraph.startswith("```") or paragraph.startswith("<"):
                continue
            return _compact(paragraph, max_chars=480)
    primary_language = next(iter(index.languages), "code")
    return f"A {primary_language} project with {index.file_count} indexed files and modules organized for {index.repo_id}."


def _infer_tech_stack(root: Path, index: RepoIndex) -> list[str]:
    """根据仓库索引和文件线索推断架构信息。"""
    stack: list[str] = []
    stack.extend(f"{language} files: {count}" for language, count in index.languages.items())
    stack.extend(_package_stack_clues(root, index.package_files))
    for config in index.config_files:
        name = Path(config).name.lower()
        if "vite" in name:
            stack.append("Vite frontend build")
        elif "tsconfig" in name:
            stack.append("TypeScript configuration")
        elif "docker" in name:
            stack.append("Docker deployment config")
        elif name.endswith((".yaml", ".yml")):
            stack.append(f"YAML config: {config}")
    return _unique(stack)[:18]


def _infer_modules(root: Path, index: RepoIndex) -> list[ModuleSummary]:
    """根据仓库索引和文件线索推断架构信息。"""
    module_names = _module_names_from_files(index)
    modules: list[ModuleSummary] = []
    for name in module_names:
        role = MODULE_ROLE_HINTS.get(_module_key(name), "Project module or package boundary.")
        signals = _module_signals(name, index)
        modules.append(ModuleSummary(path=name, role=role, signals=signals[:8]))
    return modules[:20]


def _infer_minimal_architecture(index: RepoIndex, modules: list[ModuleSummary]) -> list[str]:
    """根据仓库索引和文件线索推断架构信息。"""
    names = {_module_key(module.path) for module in modules}
    architecture: list[str] = []
    if names & {"cli", "server", "web", "tui", "scripts", "api"}:
        architecture.append("Interface layer: CLI/server/web/scripts receive user intent and expose runtime operations.")
    if names & {"app", "config"}:
        architecture.append("Application layer: bootstrap/config code wires model adapters, tools, storage, and runtime.")
    if names & {"runtime", "agent"}:
        architecture.append("Agent runtime layer: a turn loop keeps messages, asks the model for tool calls, executes tools, and persists observations.")
    if names & {"tools", "web_tools", "browser", "mcp"}:
        architecture.append("Tool boundary: tool specs make file/repo/web operations callable while keeping permissions explicit.")
    if names & {"blueprint", "memory", "learning"} or index.agent_related_files:
        architecture.append("Learning layer: repo indexes become reusable blueprint summaries and memory chunks for later project design.")
    if names & {"storage", "domain"}:
        architecture.append("Persistence/model layer: domain records and storage modules keep sessions, blueprints, and local state durable.")
    if not architecture:
        architecture.append("Source layer: package/config files define the project shape and entrypoints.")
        architecture.append("Behavior layer: important source files hold the main control flow.")
        architecture.append("Verification layer: tests/docs explain intended usage and regression coverage.")
    return architecture


def _infer_data_flow(index: RepoIndex, modules: list[ModuleSummary]) -> list[str]:
    """根据仓库索引和文件线索推断架构信息。"""
    names = {_module_key(module.path) for module in modules}
    flow = ["Repository files -> RepoIndex facts -> RepoBlueprint summary -> BlueprintMemoryItem chunks."]
    if names & {"cli", "server", "web", "tui", "scripts"}:
        flow.append("User input enters through an interface layer before reaching application bootstrap.")
    if names & {"runtime", "tools"}:
        flow.append("AgentRuntime builds context, receives tool calls, dispatches ToolRegistry, then stores tool observations.")
    if names & {"memory", "blueprint", "learning"}:
        flow.append("Learning artifacts are saved locally and later recalled by keyword search.")
    if index.test_files:
        flow.append("Tests exercise the same boundaries as regression checks.")
    return flow


def _infer_reusable_patterns(index: RepoIndex, modules: list[ModuleSummary]) -> list[str]:
    """根据仓库索引和文件线索推断架构信息。"""
    names = {_module_key(module.path) for module in modules}
    patterns: list[str] = []
    if names & {"runtime", "tools"}:
        patterns.append("Separate the agent loop from tool implementations so new abilities can be registered without rewriting the runtime.")
    if names & {"blueprint", "memory"}:
        patterns.append("Turn repository understanding into small memory chunks instead of one large report.")
    if names & {"storage"}:
        patterns.append("Use local JSON/session storage first; it keeps the MVP inspectable before adding databases.")
    if index.package_files:
        patterns.append("Treat package/config files as architecture evidence before reading deep implementation files.")
    if index.test_files:
        patterns.append("Mirror major modules in tests so architecture changes have visible regression points.")
    if not patterns:
        patterns.append("Start from file tree, entrypoints, package files, and README before deep code reading.")
    return patterns


def _infer_learning_notes(index: RepoIndex, modules: list[ModuleSummary]) -> list[str]:
    """根据仓库索引和文件线索推断架构信息。"""
    notes = [
        "When studying this repo, first identify entrypoints, then follow calls into the core module, then inspect storage/tests.",
        "Keep the minimal architecture short enough to reuse when designing a new project.",
    ]
    if index.agent_related_files:
        notes.append("Agent-related filenames are strong reading anchors: " + ", ".join(index.agent_related_files[:8]))
    if modules:
        notes.append("Main module boundaries detected: " + ", ".join(module.path for module in modules[:10]))
    return notes


def _module_names_from_files(index: RepoIndex) -> list[str]:
    """为该流程的公共逻辑提供局部辅助处理。"""
    candidates: list[str] = []
    all_paths = _unique(
        index.important_files
        + index.entrypoints
        + index.package_files
        + index.config_files
        + index.route_files
        + index.test_files
        + index.agent_related_files
    )
    for rel in all_paths:
        parts = rel.split("/")
        if parts[0] == "src":
            if len(parts) >= 4:
                candidates.append("/".join(parts[:3]))
            continue
        elif len(parts) >= 2 and parts[0] in {"tests", "docs", "scripts"}:
            candidates.append(parts[0])
        elif parts and "." not in parts[0]:
            candidates.append(parts[0])
    return _unique(candidates)


def _module_signals(name: str, index: RepoIndex) -> list[str]:
    """为该流程的公共逻辑提供局部辅助处理。"""
    prefix = name.rstrip("/") + "/"
    values = []
    for rel in _unique(index.important_files + index.entrypoints + index.agent_related_files + index.route_files + index.test_files):
        if rel == name or rel.startswith(prefix):
            values.append(rel)
    return values


def _module_key(path: str) -> str:
    """为该流程的公共逻辑提供局部辅助处理。"""
    return path.rstrip("/").split("/")[-1].lower()


def _package_stack_clues(root: Path, package_files: list[str]) -> list[str]:
    """为该流程的公共逻辑提供局部辅助处理。"""
    clues: list[str] = []
    for rel in package_files:
        path = root / rel
        name = path.name.lower()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if name == "package.json":
            clues.extend(_package_json_clues(text))
        elif name == "pyproject.toml":
            clues.append("Python package/project metadata")
            clues.extend(_keyword_clues(text, ["fastapi", "uvicorn", "pytest", "pydantic", "typer", "rich"]))
        elif name == "requirements.txt":
            clues.append("Python requirements file")
            clues.extend(_keyword_clues(text, ["fastapi", "uvicorn", "pytest", "pydantic", "typer", "rich"]))
        elif name == "cargo.toml":
            clues.append("Rust Cargo project")
        elif name == "go.mod":
            clues.append("Go module")
    return clues


def _package_json_clues(text: str) -> list[str]:
    """为该流程的公共逻辑提供局部辅助处理。"""
    clues = ["Node package metadata"]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {}
    dependencies = {}
    for key in ("dependencies", "devDependencies"):
        dependencies.update(payload.get(key) or {})
    for package, label in {
        "react": "React UI",
        "vite": "Vite frontend build",
        "next": "Next.js app",
        "typescript": "TypeScript",
        "express": "Express server",
    }.items():
        if package in dependencies:
            clues.append(label)
    return clues


def _keyword_clues(text: str, keywords: list[str]) -> list[str]:
    """为该流程的公共逻辑提供局部辅助处理。"""
    lowered = text.lower()
    return [f"{keyword} dependency/config" for keyword in keywords if keyword in lowered]


def _read_readme(root: Path) -> str:
    """读取内部数据并转换为当前模块需要的结构。"""
    for path in sorted(root.glob("README*")):
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
    return ""


def _bullet_list(values: list[str]) -> str:
    """为该流程的公共逻辑提供局部辅助处理。"""
    if not values:
        return "- None detected."
    return "\n".join(f"- {value}" for value in values)


def _compact(text: str, *, max_chars: int) -> str:
    """为该流程的公共逻辑提供局部辅助处理。"""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _unique(values: list[str]) -> list[str]:
    """为该流程的公共逻辑提供局部辅助处理。"""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _stable_id(*parts: str) -> str:
    """为该流程的公共逻辑提供局部辅助处理。"""
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
