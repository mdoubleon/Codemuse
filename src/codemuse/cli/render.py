"""把 SDK 返回的事件和 JSON 结果格式化为 CLI 输出。"""
from __future__ import annotations

import json
from typing import Any


def print_events(events: list[dict[str, Any]]) -> None:
    """把 AgentEvent 列表按 CLI 可读格式打印出来。"""
    for event in events:
        label = str(event["type"])
        if event.get("tool_name"):
            label += f"[{event['tool_name']}]"
        text = str(event.get("message") or "")
        if text:
            print(f"{label}: {text}")
        else:
            print(label)
        preview = (event.get("details") or {}).get("effect_preview")
        if isinstance(preview, dict):
            _print_effect_preview(preview)
        if event["type"] == "approval_stale":
            _print_stale_details(event.get("details") or {})
        if event["type"] == "approval_invalid":
            _print_invalid_details(event.get("details") or {})


def print_json(payload: Any) -> None:
    """把 SDK 返回的结构化数据以缩进 JSON 打印。"""
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_json_value(raw: str) -> Any:
    """尝试把 CLI 字符串解析成 JSON 值，失败时保留原字符串。"""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # CLI 输入不是合法 JSON 时，当成普通字符串；这样 `config set x hello` 也能用。
        return raw


def _print_effect_preview(preview: dict[str, Any]) -> None:
    """把审批事件里的工具影响预览打印成人能快速判断风险的格式。"""
    if preview.get("kind") == "apply_patch":
        _print_patch_effect_preview(preview)
        return
    if preview.get("kind") == "run_shell":
        _print_shell_effect_preview(preview)
        return
    if preview.get("kind") == "web_fetch":
        _print_web_fetch_effect_preview(preview)
        return
    if preview.get("kind") not in {"write_file", "replace_text"}:
        return
    path = preview.get("relative_path") or "<unknown>"
    operation = preview.get("operation") or "change"
    before_chars = preview.get("before_chars", 0)
    after_chars = preview.get("after_chars", 0)
    if preview.get("kind") == "replace_text":
        replacements = preview.get("replacements", 0)
        matches = preview.get("match_count", 0)
        print(f"  effect: replace_text {path} ({before_chars} -> {after_chars} chars, {replacements}/{matches} matches)")
    else:
        print(f"  effect: {operation} {path} ({before_chars} -> {after_chars} chars)")
    if preview.get("blocked"):
        print(f"  blocked: {preview.get('reason') or 'preview marked this action as blocked'}")
    diff = str(preview.get("diff") or "").strip()
    if diff:
        print("  diff:")
        for line in diff.splitlines():
            print(f"    {line}")


def _print_patch_effect_preview(preview: dict[str, Any]) -> None:
    """把 apply_patch 的多文件影响预览打印出来。"""
    print(f"  effect: apply_patch files={preview.get('files_count', 0)}")
    if preview.get("blocked"):
        print(f"  blocked: {preview.get('reason') or 'preview marked this action as blocked'}")
    for change in preview.get("changes") or []:
        path = change.get("relative_path") or "<unknown>"
        operation = change.get("operation") or "change"
        before_chars = change.get("before_chars", 0)
        after_chars = change.get("after_chars", 0)
        print(f"  file: {operation} {path} ({before_chars} -> {after_chars} chars)")
        if change.get("blocked"):
            print(f"    blocked: {change.get('reason') or 'file preview is blocked'}")
        diff = str(change.get("diff") or "").strip()
        if diff:
            print("    diff:")
            for line in diff.splitlines():
                print(f"      {line}")


def _print_shell_effect_preview(preview: dict[str, Any]) -> None:
    """把 run_shell 的命令风险预览打印出来。"""
    command = str(preview.get("command") or "").strip()
    risk = preview.get("risk_level") or "unknown"
    timeout = preview.get("timeout_seconds", 0)
    print(f"  effect: run_shell risk={risk} timeout={timeout}s")
    print(f"  command: {command}")
    if preview.get("blocked"):
        print(f"  blocked: {preview.get('reason') or 'preview marked this command as blocked'}")
    reasons = preview.get("risk_reasons") or []
    for reason in reasons:
        print(f"  risk: {reason}")


def _print_web_fetch_effect_preview(preview: dict[str, Any]) -> None:
    """把 web_fetch 的网络访问预览打印出来。"""
    url = str(preview.get("url") or "").strip()
    risk = preview.get("risk_level") or "unknown"
    timeout = preview.get("timeout_seconds", 0)
    max_chars = preview.get("max_chars", 0)
    print(f"  effect: web_fetch risk={risk} timeout={timeout}s max_chars={max_chars}")
    print(f"  url: {url}")
    if preview.get("blocked"):
        print(f"  blocked: {preview.get('reason') or 'preview marked this URL as blocked'}")
    for reason in preview.get("risk_reasons") or []:
        print(f"  risk: {reason}")


def _print_stale_details(details: dict[str, Any]) -> None:
    """把过期审批的原因打印出来，提醒用户重新生成 diff 后再批准。"""
    reason = str(details.get("reason") or "").strip()
    changed_fields = details.get("changed_fields") or []
    if reason:
        print(f"  reason: {reason}")
    if changed_fields:
        print(f"  changed: {', '.join(str(item) for item in changed_fields)}")


def _print_invalid_details(details: dict[str, Any]) -> None:
    """把摘要不匹配的原因打印出来，提示审批单内容已经不可信。"""
    reason = str(details.get("invalid_reason") or details.get("reason") or "").strip()
    if reason:
        print(f"  reason: {reason}")
