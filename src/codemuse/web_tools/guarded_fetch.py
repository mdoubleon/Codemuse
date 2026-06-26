"""受保护的静态网页获取能力，不执行 JavaScript。"""
from __future__ import annotations

import html
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}


@dataclass(frozen=True)
class WebFetchConfig:
    """保存一次 web_fetch 的安全限制。"""

    timeout_seconds: int = 10
    max_chars: int = 4000
    max_bytes: int = 128_000
    max_redirects: int = 5
    allow_private_network: bool = False


@dataclass
class WebFetchResponse:
    """保存网页获取后的结构化结果。"""

    url: str
    status_code: int
    text: str
    content_type: str = ""
    redirects: list[str] = field(default_factory=list)
    truncated: bool = False
    executed_javascript: bool = False


class GuardedFetchError(RuntimeError):
    """网页获取被安全策略或 HTTP 错误阻止。"""


class GuardedFetcher:
    """只允许 http/https，并阻止 SSRF 常见私有地址的静态 GET 客户端。"""

    def __init__(self, config: WebFetchConfig | None = None, opener: Any | None = None) -> None:
        """保存 fetch 配置和可替换 opener，测试时可注入 fake opener。"""
        self.config = config or WebFetchConfig()
        self.opener = opener or build_opener(_NoRedirectHandler)

    def fetch(self, url: str) -> WebFetchResponse:
        """获取 URL 并返回可读文本；重定向会逐跳校验 URL。"""
        current_url = validate_url(url, allow_private_network=self.config.allow_private_network)
        redirects: list[str] = []
        headers = {"User-Agent": "CodeMuse web_fetch"}
        for _index in range(self.config.max_redirects + 1):
            request = Request(current_url, headers=headers, method="GET")
            try:
                response = self.opener.open(request, timeout=self.config.timeout_seconds)
            except HTTPError as exc:
                if exc.code not in {301, 302, 303, 307, 308}:
                    raise GuardedFetchError(f"HTTP {exc.code} while fetching {current_url}") from exc
                location = str(exc.headers.get("location") or "").strip()
                if not location:
                    raise GuardedFetchError(f"Redirect response did not include Location: {current_url}") from exc
                next_url = validate_url(
                    urljoin(current_url, location),
                    allow_private_network=self.config.allow_private_network,
                )
                if _origin(current_url) != _origin(next_url):
                    headers = {key: value for key, value in headers.items() if key.lower() not in SENSITIVE_HEADERS}
                redirects.append(next_url)
                current_url = next_url
                continue
            except URLError as exc:
                raise GuardedFetchError(str(exc.reason)) from exc

            status_code = int(getattr(response, "status", getattr(response, "code", 200)))
            content_type = str(response.headers.get("content-type", ""))
            raw = response.read(self.config.max_bytes + 1)
            truncated_bytes = len(raw) > self.config.max_bytes
            if truncated_bytes:
                raw = raw[: self.config.max_bytes]
            charset = _charset_from_content_type(content_type)
            decoded = raw.decode(charset, errors="replace")
            readable = readable_text(decoded) if _looks_like_html(content_type, decoded) else decoded
            truncated_chars = len(readable) > self.config.max_chars
            if truncated_chars:
                readable = readable[: self.config.max_chars]
            return WebFetchResponse(
                url=current_url,
                status_code=status_code,
                text=readable.strip(),
                content_type=content_type,
                redirects=redirects,
                truncated=truncated_bytes or truncated_chars,
                executed_javascript=False,
            )
        raise GuardedFetchError(f"Too many redirects while fetching {url!r}; max_redirects={self.config.max_redirects}")


def validate_url(url: str, *, allow_private_network: bool = False) -> str:
    """校验 URL 协议、主机和私有网络地址。"""
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise GuardedFetchError("Only http and https URLs are allowed.")
    hostname = (parsed.hostname or "").strip()
    if not hostname:
        raise GuardedFetchError("URL must include a hostname.")
    if not allow_private_network:
        for address in resolve_addresses(hostname):
            if is_private_or_internal(address):
                raise GuardedFetchError(f"Blocked private/internal network address: {address}")
    return value


def build_fetch_preview(url: str, config: WebFetchConfig) -> dict[str, Any]:
    """生成 web_fetch 审批预览，不访问目标页面。"""
    parsed = urlparse(str(url or "").strip())
    hostname = (parsed.hostname or "").strip()
    try:
        normalized_url = validate_url(url, allow_private_network=config.allow_private_network)
        blocked = False
        reason = ""
    except GuardedFetchError as exc:
        normalized_url = str(url or "").strip()
        blocked = True
        reason = str(exc)
    return {
        "kind": "web_fetch",
        "available": True,
        "blocked": blocked,
        "reason": reason,
        "url": normalized_url,
        "scheme": parsed.scheme,
        "hostname": hostname,
        "timeout_seconds": config.timeout_seconds,
        "max_chars": config.max_chars,
        "max_bytes": config.max_bytes,
        "max_redirects": config.max_redirects,
        "allow_private_network": config.allow_private_network,
        "risk_level": "blocked" if blocked else "medium",
        "risk_reasons": (
            [reason]
            if blocked
            else [
                "Fetches external network content.",
                "Does not execute JavaScript or use browser profile state.",
            ]
        ),
        "executed_javascript": False,
    }


def resolve_addresses(hostname: str) -> list[str]:
    """解析主机地址；解析失败时对域名放行，由真正请求返回网络错误。"""
    try:
        return sorted({item[4][0] for item in socket.getaddrinfo(hostname, None)})
    except socket.gaierror:
        try:
            ipaddress.ip_address(hostname)
            return [hostname]
        except ValueError:
            return []


def is_private_or_internal(value: str) -> bool:
    """判断地址是否属于私有、回环、链路本地或元数据地址。"""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or str(address) == "169.254.169.254"
    )


def readable_text(raw: str) -> str:
    """把 HTML 粗略转换成可读纯文本。"""
    value = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _looks_like_html(content_type: str, text: str) -> bool:
    """判断响应是否应该进行 HTML 文本抽取。"""
    lowered = content_type.lower()
    return "html" in lowered or "<html" in text[:500].lower()


def _charset_from_content_type(content_type: str) -> str:
    """从 Content-Type 中提取 charset，默认 utf-8。"""
    match = re.search(r"charset=([\w.-]+)", content_type, flags=re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _origin(url: str) -> tuple[str, str, int | None]:
    """计算 URL origin，用于跨站跳转时清理敏感头。"""
    parsed = urlparse(url)
    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)


class _NoRedirectHandler(HTTPRedirectHandler):
    """禁用 urllib 自动重定向，让每一跳都经过 URL 校验。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None
