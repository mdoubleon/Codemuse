"""在工具真正执行前生成可展示的副作用预览。"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from codemuse.web_tools.guarded_fetch import WebFetchConfig, build_fetch_preview

MAX_DIFF_CHARS = 20000
MAX_DIFF_LINES = 160
PROTECTED_WRITE_DIRS = {".git", ".data"}


def build_tool_effect_preview(workspace: Path, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """根据工具名和参数生成执行前影响摘要；当前支持文件写入和文本编辑工具。"""
    try:
        if tool_name == "write_file":
            return build_write_file_effect_preview(workspace, arguments)
        if tool_name == "apply_patch":
            return build_apply_patch_effect_preview(workspace, arguments)
        if tool_name == "replace_text":
            return build_replace_text_effect_preview(workspace, arguments)
        if tool_name == "run_shell":
            return build_shell_effect_preview(workspace, arguments)
        if tool_name == "web_fetch":
            return build_web_fetch_effect_preview(workspace, arguments)
        return None
    except Exception as exc:  # noqa: BLE001 - 预览失败也要返回给用户看，不能悄悄吞掉
        return {
            "kind": tool_name,
            "available": False,
            "blocked": True,
            "reason": str(exc),
        }


def validate_tool_effect_preview(
    workspace: Path,
    tool_name: str,
    arguments: dict[str, Any],
    stored_preview: dict[str, Any] | None,
) -> dict[str, Any]:
    """批准前重新生成预览并比较文件状态，避免用户按旧 diff 批准新文件。"""
    if tool_name not in {"write_file", "apply_patch", "replace_text", "run_shell", "web_fetch"} or not stored_preview:
        return {"ok": True, "reason": "", "current_preview": None, "changed_fields": []}
    current_preview = build_tool_effect_preview(workspace, tool_name, arguments)
    if current_preview is None:
        return {"ok": True, "reason": "", "current_preview": None, "changed_fields": []}
    if stored_preview.get("blocked"):
        return {
            "ok": False,
            "reason": str(stored_preview.get("reason") or "Stored preview was blocked."),
            "current_preview": current_preview,
            "changed_fields": [],
        }
    if current_preview.get("blocked"):
        return {
            "ok": False,
            "reason": str(current_preview.get("reason") or "Current file state blocks this action."),
            "current_preview": current_preview,
            "changed_fields": [],
        }

    if tool_name == "apply_patch":
        changed_fields = _changed_patch_preview_fields(stored_preview, current_preview)
    elif tool_name == "run_shell":
        changed_fields = [
            field
            for field in ["command", "working_directory", "timeout_seconds", "risk_level", "blocked", "reason"]
            if stored_preview.get(field) != current_preview.get(field)
        ]
    elif tool_name == "web_fetch":
        changed_fields = [
            field
            for field in ["url", "hostname", "timeout_seconds", "max_chars", "max_bytes", "risk_level", "blocked", "reason"]
            if stored_preview.get(field) != current_preview.get(field)
        ]
    else:
        changed_fields = [
            field
            for field in ["relative_path", "exists", "before_chars", "before_sha256"]
            if stored_preview.get(field) != current_preview.get(field)
        ]
    if not changed_fields:
        return {"ok": True, "reason": "", "current_preview": current_preview, "changed_fields": []}
    return {
        "ok": False,
        "reason": "Target file changed after approval preview was created.",
        "current_preview": current_preview,
        "changed_fields": changed_fields,
    }


def build_effect_digest(tool_name: str, arguments: dict[str, Any], effect_preview: dict[str, Any] | None) -> str:
    """给审批时展示和保存的工具调用内容计算稳定摘要。"""
    payload = {
        "tool_name": tool_name,
        "arguments": arguments,
        "effect_preview": effect_preview or {},
    }
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def validate_effect_digest(tool_name: str, arguments: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    """批准前确认审批单里的参数和预览没有偏离创建审批时的摘要。"""
    stored_digest = str(details.get("effect_digest") or "")
    expected_digest = build_effect_digest(tool_name, arguments, details.get("effect_preview"))
    if stored_digest == expected_digest:
        return {"ok": True, "reason": "", "stored_digest": stored_digest, "expected_digest": expected_digest}
    if not stored_digest:
        reason = "Approval digest is missing."
    else:
        reason = "Approval digest does not match the stored tool call and preview."
    return {
        "ok": False,
        "reason": reason,
        "stored_digest": stored_digest,
        "expected_digest": expected_digest,
    }


def build_write_file_effect_preview(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """读取 write_file 参数和当前磁盘状态，生成路径、字符数和统一 diff 预览。"""
    workspace = workspace.resolve()
    path = _resolve_workspace_path(workspace, str(arguments["path"]))
    relative_path = path.relative_to(workspace).as_posix()
    if any(part in PROTECTED_WRITE_DIRS for part in path.relative_to(workspace).parts):
        raise PermissionError(f"Refusing to write managed or git-internal path: {relative_path}")

    content = str(arguments.get("content") or "")
    create_dirs = bool(arguments.get("create_dirs", False))
    overwrite = bool(arguments.get("overwrite", True))
    existed = path.exists()
    parent_exists = path.parent.exists()
    before_text = ""
    blocked_reason = ""

    if existed and path.is_dir():
        blocked_reason = "Target path is a directory."
    elif existed and not overwrite:
        blocked_reason = "Target file exists and overwrite=false."
    elif not parent_exists and not create_dirs:
        blocked_reason = "Parent directory does not exist and create_dirs=false."
    elif existed:
        before_text = path.read_text(encoding="utf-8", errors="replace")

    operation = "update" if existed else "create"
    diff_text, diff_truncated = _build_unified_diff(relative_path, before_text, content, existed=existed)
    before_chars = len(before_text) if existed and path.is_file() else 0
    before_sha256 = _sha256_text(before_text) if existed and path.is_file() else None

    return {
        "kind": "write_file",
        "available": True,
        "blocked": bool(blocked_reason),
        "reason": blocked_reason,
        "operation": operation,
        "relative_path": relative_path,
        "exists": existed,
        "parent_exists": parent_exists,
        "will_create_parent_dirs": (not parent_exists and create_dirs),
        "overwrite": overwrite,
        "create_dirs": create_dirs,
        "before_chars": before_chars,
        "after_chars": len(content),
        "delta_chars": len(content) - before_chars,
        "before_sha256": before_sha256,
        "after_sha256": _sha256_text(content),
        "diff": diff_text,
        "diff_truncated": diff_truncated,
    }


def build_apply_patch_effect_preview(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """读取 unified diff 和当前文件状态，生成多文件 patch 的审批预览。"""
    workspace = workspace.resolve()
    patch_text = str(arguments.get("patch") or "")
    create_dirs = bool(arguments.get("create_dirs", True))
    file_patches = _parse_unified_patch(patch_text)
    changes: list[dict[str, Any]] = []
    blocked_reason = ""
    for file_patch in file_patches:
        try:
            change = _preview_single_patch(workspace, file_patch, create_dirs=create_dirs)
        except Exception as exc:  # noqa: BLE001 - 单个文件失败也要进入审批预览，方便用户看到原因
            change = {
                "kind": "apply_patch_file",
                "relative_path": file_patch.get("relative_path") or "<unknown>",
                "blocked": True,
                "reason": str(exc),
            }
        if change.get("blocked") and not blocked_reason:
            blocked_reason = str(change.get("reason") or "Patch preview is blocked.")
        changes.append(change)
    if not changes:
        blocked_reason = "Patch does not contain any file changes."
    return {
        "kind": "apply_patch",
        "available": True,
        "blocked": bool(blocked_reason),
        "reason": blocked_reason,
        "files_count": len(changes),
        "create_dirs": create_dirs,
        "changes": changes,
    }


def apply_unified_patch(workspace: Path, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """在审批通过后把 unified diff 应用到 workspace 文件，并返回写入摘要。"""
    workspace = workspace.resolve()
    patch_text = str(arguments.get("patch") or "")
    create_dirs = bool(arguments.get("create_dirs", True))
    file_patches = _parse_unified_patch(patch_text)
    planned: list[tuple[Path, str, dict[str, Any]]] = []
    for file_patch in file_patches:
        path, after_text, summary = _apply_single_patch_to_text(workspace, file_patch, create_dirs=create_dirs)
        planned.append((path, after_text, summary))
    for path, after_text, _summary in planned:
        if not path.parent.exists():
            if not create_dirs:
                raise FileNotFoundError(f"Parent directory does not exist: {path.parent}")
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after_text, encoding="utf-8")
    return [summary for _path, _after_text, summary in planned]


def build_replace_text_effect_preview(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """读取 replace_text 参数和当前文件状态，生成替换前后的 diff 预览。"""
    workspace = workspace.resolve()
    path = _resolve_workspace_path(workspace, str(arguments["path"]))
    relative_path = path.relative_to(workspace).as_posix()
    if any(part in PROTECTED_WRITE_DIRS for part in path.relative_to(workspace).parts):
        raise PermissionError(f"Refusing to edit managed or git-internal path: {relative_path}")

    old_text = str(arguments.get("old_text") or "")
    new_text = str(arguments.get("new_text") or "")
    replace_all = bool(arguments.get("replace_all", False))
    expected_replacements = _optional_int(arguments.get("expected_replacements"))
    existed = path.exists()
    before_text = ""
    blocked_reason = ""
    match_count = 0
    replacements = 0

    if not old_text:
        blocked_reason = "old_text cannot be empty."
    elif not existed:
        blocked_reason = "Target file does not exist."
    elif path.is_dir():
        blocked_reason = "Target path is a directory."
    else:
        before_text = path.read_text(encoding="utf-8", errors="replace")
        match_count = before_text.count(old_text)
        if match_count == 0:
            blocked_reason = "old_text was not found in target file."
        elif not replace_all and match_count > 1:
            blocked_reason = "old_text appears multiple times; set replace_all=true to replace every occurrence."
        else:
            replacements = match_count if replace_all else 1
            if expected_replacements is not None and expected_replacements != replacements:
                blocked_reason = (
                    f"Expected {expected_replacements} replacement(s), "
                    f"but planned {replacements}."
                )

    after_text = before_text
    if not blocked_reason and replacements:
        after_text = before_text.replace(old_text, new_text, replacements)
    diff_text, diff_truncated = _build_unified_diff(relative_path, before_text, after_text, existed=existed)
    before_chars = len(before_text) if existed and path.is_file() else 0
    return {
        "kind": "replace_text",
        "available": True,
        "blocked": bool(blocked_reason),
        "reason": blocked_reason,
        "operation": "update",
        "relative_path": relative_path,
        "exists": existed,
        "replace_all": replace_all,
        "expected_replacements": expected_replacements,
        "match_count": match_count,
        "replacements": replacements,
        "old_text_chars": len(old_text),
        "new_text_chars": len(new_text),
        "before_chars": before_chars,
        "after_chars": len(after_text),
        "delta_chars": len(after_text) - before_chars,
        "before_sha256": _sha256_text(before_text) if existed and path.is_file() else None,
        "after_sha256": _sha256_text(after_text),
        "diff": diff_text,
        "diff_truncated": diff_truncated,
    }


def replace_text_in_file(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """审批通过后在 workspace 文件中执行文本替换，并返回写入摘要。"""
    preview = build_replace_text_effect_preview(workspace, arguments)
    if preview.get("blocked"):
        raise ValueError(str(preview.get("reason") or "replace_text preview is blocked."))
    path = _resolve_workspace_path(workspace.resolve(), str(arguments["path"]))
    old_text = str(arguments.get("old_text") or "")
    new_text = str(arguments.get("new_text") or "")
    replacements = int(preview.get("replacements") or 0)
    before_text = path.read_text(encoding="utf-8", errors="replace")
    after_text = before_text.replace(old_text, new_text, replacements)
    path.write_text(after_text, encoding="utf-8")
    return {
        "relative_path": preview["relative_path"],
        "path": str(path),
        "operation": "update",
        "replacements": replacements,
        "before_chars": len(before_text),
        "after_chars": len(after_text),
        "before_sha256": _sha256_text(before_text),
        "after_sha256": _sha256_text(after_text),
    }


def build_shell_effect_preview(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """读取 shell 命令参数，生成审批前风险摘要，不执行命令。"""
    workspace = workspace.resolve()
    command = str(arguments.get("command") or "").strip()
    timeout_seconds = _bounded_int(arguments.get("timeout_seconds"), default=30, minimum=1, maximum=60)
    max_output_chars = _bounded_int(arguments.get("max_output_chars"), default=8000, minimum=1000, maximum=20000)
    classification = classify_shell_command(command)
    return {
        "kind": "run_shell",
        "available": True,
        "blocked": classification["blocked"],
        "reason": classification["reason"],
        "command": command,
        "working_directory": str(workspace),
        "timeout_seconds": timeout_seconds,
        "max_output_chars": max_output_chars,
        "risk_level": classification["risk_level"],
        "risk_reasons": classification["risk_reasons"],
        "shell": "powershell" if _is_windows_shell() else "sh",
    }


def build_web_fetch_effect_preview(workspace: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """读取 web_fetch 参数，生成审批前网络访问摘要，不访问目标页面。"""
    config = WebFetchConfig(
        timeout_seconds=_bounded_int(arguments.get("timeout_seconds"), default=10, minimum=1, maximum=30),
        max_chars=_bounded_int(arguments.get("max_chars"), default=4000, minimum=500, maximum=20000),
        max_bytes=_bounded_int(arguments.get("max_bytes"), default=128_000, minimum=4096, maximum=1_000_000),
        max_redirects=_bounded_int(arguments.get("max_redirects"), default=5, minimum=0, maximum=10),
        allow_private_network=bool(arguments.get("allow_private_network", False)),
    )
    return build_fetch_preview(str(arguments.get("url") or ""), config)


def classify_shell_command(command: str) -> dict[str, Any]:
    """用保守规则识别 shell 命令风险；这是审批提示，不是完整系统沙箱。"""
    normalized = _normalize_command_for_risk(command)
    risk_reasons: list[str] = []
    blocked_reasons: list[str] = []
    if not normalized:
        blocked_reasons.append("Command cannot be empty.")
    destructive_patterns = [
        "rm -rf",
        "rm -fr",
        "remove-item",
        "del ",
        "erase ",
        "rmdir ",
        "rd /",
        "format ",
        "diskpart",
        "shutdown",
        "restart-computer",
        "stop-computer",
        "git reset --hard",
        "git clean",
        "mkfs",
        "reg delete",
        "set-executionpolicy",
        "invoke-expression",
        "iex ",
        "curl |",
        "irm ",
        "iwr ",
    ]
    for pattern in destructive_patterns:
        if pattern in normalized:
            blocked_reasons.append(f"Destructive or unsafe command pattern detected: {pattern.strip()}")
            break
    network_patterns = ["curl ", "wget ", "invoke-webrequest", "invoke-restmethod", "git clone", "pip install", "npm install"]
    for pattern in network_patterns:
        if pattern in normalized:
            risk_reasons.append(f"May access network or install external code: {pattern.strip()}")
            break
    write_patterns = [">", ">>", "set-content", "add-content", "new-item", "copy-item", "move-item", "mkdir ", "touch "]
    for pattern in write_patterns:
        if pattern in normalized:
            risk_reasons.append("May write or move files in the workspace.")
            break
    if any(item in normalized for item in ["python -c", "python -m", "pytest", "unittest", "compileall", "npm test"]):
        risk_reasons.append("May execute project code.")
    if blocked_reasons:
        return {
            "blocked": True,
            "reason": "; ".join(blocked_reasons),
            "risk_level": "blocked",
            "risk_reasons": blocked_reasons + risk_reasons,
        }
    risk_level = "high" if risk_reasons else "medium"
    if normalized in {"pwd", "ls", "dir", "echo", "python --version", "node --version"}:
        risk_level = "low"
    return {
        "blocked": False,
        "reason": "",
        "risk_level": risk_level,
        "risk_reasons": risk_reasons or ["Command will execute in the workspace after approval."],
    }


def _build_unified_diff(relative_path: str, before_text: str, after_text: str, *, existed: bool) -> tuple[str, bool]:
    """把写入前后的文本转成 unified diff，并限制最大展示长度。"""
    before_for_diff = before_text[:MAX_DIFF_CHARS]
    after_for_diff = after_text[:MAX_DIFF_CHARS]
    char_truncated = len(before_text) > MAX_DIFF_CHARS or len(after_text) > MAX_DIFF_CHARS
    fromfile = f"a/{relative_path}" if existed else "/dev/null"
    tofile = f"b/{relative_path}"
    diff_lines = list(
        difflib.unified_diff(
            before_for_diff.splitlines(),
            after_for_diff.splitlines(),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    line_truncated = len(diff_lines) > MAX_DIFF_LINES
    if line_truncated:
        diff_lines = diff_lines[:MAX_DIFF_LINES]
        diff_lines.append("... diff truncated ...")
    return "\n".join(diff_lines), char_truncated or line_truncated


def _resolve_workspace_path(workspace: Path, raw_path: str) -> Path:
    """把预览参数中的路径限制在 workspace 内，避免预览阶段读取外部文件。"""
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if workspace not in resolved.parents and resolved != workspace:
        raise PermissionError(f"Path is outside workspace: {raw_path}")
    return resolved


def _sha256_text(text: str) -> str:
    """给预览时看到的文本内容计算稳定哈希，用于 approve 前防过期校验。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _optional_int(value: Any) -> int | None:
    """把可选整数参数规范成 int，空值表示调用方不做数量断言。"""
    if value is None or value == "":
        return None
    return int(value)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    """把整数参数限制在安全范围内，避免命令超时或输出无限膨胀。"""
    if value is None or value == "":
        parsed = default
    else:
        parsed = int(value)
    return max(minimum, min(maximum, parsed))


def _normalize_command_for_risk(command: str) -> str:
    """把命令压成便于规则匹配的小写单行文本。"""
    return " ".join(command.strip().lower().split())


def _is_windows_shell() -> bool:
    """判断当前执行环境是否应该使用 PowerShell。"""
    return Path.cwd().drive != ""


def _parse_unified_patch(patch_text: str) -> list[dict[str, Any]]:
    """把 unified diff 文本拆成每个目标文件的 hunks。"""
    lines = patch_text.splitlines()
    patches: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise ValueError("Patch header must contain --- and +++ lines.")
        old_path = _normalize_patch_path(lines[index][4:])
        new_path = _normalize_patch_path(lines[index + 1][4:])
        target_path = new_path if new_path != "/dev/null" else old_path
        hunks: list[dict[str, Any]] = []
        index += 2
        while index < len(lines) and not lines[index].startswith("--- "):
            if not lines[index].startswith("@@"):
                index += 1
                continue
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[index])
            if not match:
                raise ValueError(f"Invalid patch hunk header: {lines[index]}")
            hunk_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("@@") and not lines[index].startswith("--- "):
                if lines[index].startswith("\\"):
                    index += 1
                    continue
                if not lines[index] or lines[index][0] not in {" ", "+", "-"}:
                    raise ValueError(f"Invalid patch hunk line: {lines[index]}")
                hunk_lines.append(lines[index])
                index += 1
            hunks.append(
                {
                    "old_start": int(match.group(1)),
                    "old_count": int(match.group(2) or "1"),
                    "new_start": int(match.group(3)),
                    "new_count": int(match.group(4) or "1"),
                    "lines": hunk_lines,
                }
            )
        if target_path == "/dev/null":
            raise ValueError("Deleting files with apply_patch is not supported in this MVP.")
        patches.append({"old_path": old_path, "new_path": new_path, "relative_path": target_path, "hunks": hunks})
    if not patches:
        raise ValueError("No unified diff file headers found.")
    return patches


def _changed_patch_preview_fields(stored_preview: dict[str, Any], current_preview: dict[str, Any]) -> list[str]:
    """比较 patch 审批预览里每个目标文件的写入前状态。"""
    changed_fields: list[str] = []
    stored_changes = stored_preview.get("changes") or []
    current_changes = current_preview.get("changes") or []
    if len(stored_changes) != len(current_changes):
        return ["changes_count"]
    for index, (stored_change, current_change) in enumerate(zip(stored_changes, current_changes, strict=True)):
        for field in ["relative_path", "exists", "before_chars", "before_sha256"]:
            if stored_change.get(field) != current_change.get(field):
                changed_fields.append(f"changes[{index}].{field}")
    return changed_fields


def _preview_single_patch(workspace: Path, file_patch: dict[str, Any], *, create_dirs: bool) -> dict[str, Any]:
    """对单个文件 patch 生成审批预览，不写入磁盘。"""
    path, after_text, summary = _apply_single_patch_to_text(workspace, file_patch, create_dirs=create_dirs)
    before_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() and path.is_file() else ""
    diff_text, diff_truncated = _build_unified_diff(summary["relative_path"], before_text, after_text, existed=summary["exists"])
    return {
        "kind": "apply_patch_file",
        "blocked": False,
        "reason": "",
        **summary,
        "after_chars": len(after_text),
        "delta_chars": len(after_text) - summary["before_chars"],
        "after_sha256": _sha256_text(after_text),
        "diff": diff_text,
        "diff_truncated": diff_truncated,
    }


def _apply_single_patch_to_text(
    workspace: Path,
    file_patch: dict[str, Any],
    *,
    create_dirs: bool,
) -> tuple[Path, str, dict[str, Any]]:
    """把单个文件 patch 应用于内存文本，返回目标路径、结果文本和摘要。"""
    relative_path = str(file_patch["relative_path"])
    path = _resolve_workspace_path(workspace, relative_path)
    normalized_relative = path.relative_to(workspace).as_posix()
    if any(part in PROTECTED_WRITE_DIRS for part in path.relative_to(workspace).parts):
        raise PermissionError(f"Refusing to patch managed or git-internal path: {normalized_relative}")
    if file_patch["new_path"] == "/dev/null":
        raise ValueError("Deleting files with apply_patch is not supported in this MVP.")
    existed = path.exists()
    if existed and path.is_dir():
        raise IsADirectoryError(str(path))
    if not path.parent.exists() and not create_dirs:
        raise FileNotFoundError(f"Parent directory does not exist: {path.parent}")
    if file_patch["old_path"] == "/dev/null":
        before_text = ""
    else:
        if not existed:
            raise FileNotFoundError(f"Cannot patch missing file: {normalized_relative}")
        before_text = path.read_text(encoding="utf-8", errors="replace")
    after_lines = _apply_hunks(before_text.splitlines(), file_patch["hunks"])
    after_text = "\n".join(after_lines) + ("\n" if after_lines else "")
    summary = {
        "relative_path": normalized_relative,
        "operation": "create" if file_patch["old_path"] == "/dev/null" else "update",
        "exists": existed,
        "before_chars": len(before_text),
        "before_sha256": _sha256_text(before_text) if existed else None,
        "hunks": len(file_patch["hunks"]),
    }
    return path, after_text, summary


def _apply_hunks(before_lines: list[str], hunks: list[dict[str, Any]]) -> list[str]:
    """按 unified diff hunk 把原始行列表转换成修改后的行列表。"""
    result: list[str] = []
    cursor = 0
    for hunk in hunks:
        hunk_start = max(int(hunk["old_start"]) - 1, 0)
        if hunk_start < cursor:
            raise ValueError("Patch hunks overlap or are out of order.")
        result.extend(before_lines[cursor:hunk_start])
        source_index = hunk_start
        for raw_line in hunk["lines"]:
            marker = raw_line[0]
            value = raw_line[1:]
            if marker == " ":
                _expect_source_line(before_lines, source_index, value)
                result.append(value)
                source_index += 1
            elif marker == "-":
                _expect_source_line(before_lines, source_index, value)
                source_index += 1
            elif marker == "+":
                result.append(value)
            else:
                raise ValueError(f"Unsupported patch line marker: {marker}")
        cursor = source_index
    result.extend(before_lines[cursor:])
    return result


def _expect_source_line(lines: list[str], index: int, expected: str) -> None:
    """确认 patch 里的上下文/删除行和当前文件内容一致。"""
    if index >= len(lines):
        raise ValueError(f"Patch context is past end of file; expected: {expected!r}")
    actual = lines[index]
    if actual != expected:
        raise ValueError(f"Patch context mismatch; expected {expected!r}, found {actual!r}")


def _normalize_patch_path(raw: str) -> str:
    """把 diff header 里的 a/path、b/path 规范成 workspace 相对路径。"""
    value = raw.strip().split("\t", 1)[0].strip()
    if value == "/dev/null":
        return value
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    if not value:
        raise ValueError("Patch path cannot be empty.")
    return value.replace("\\", "/")
