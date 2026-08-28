"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import base64
import re
from urllib.parse import urlparse, urlunparse

import ipaddress

import requests

from ..common.log import get_logger

# 预编译正则：解析 HTML body 中 href='...' 形式的下载链接
# 避免每次调用 resolve_download_url 时重复编译
HREF_URL_RE = re.compile(r"href='(https?://[^']+)'")


def is_safe_download_url(url: str) -> bool:
    """判断下载重定向是否为 HTTPS 公网地址。"""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"}:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def b64_decode(data: str) -> str:
    """安全解码 base64，兼容标准 base64 和 URL-safe base64。"""
    if not data:
        return ""
    # 先尝试标准 base64，失败则尝试 URL-safe base64
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return decoder(data).decode("utf-8")
        except Exception:
            continue
    return data


def b64_encode(data: str) -> str:
    """URL-safe base64 编码。"""
    return base64.urlsafe_b64encode(data.encode("utf-8")).decode()


def _qs_to_dict(query: str) -> dict:
    """将 query 字符串解析为 dict（跳过无 '=' 的片段）。"""
    return dict(
        (k, v)
        for k, v in (p.split("=", 1) for p in query.split("&") if "=" in p)
    )


def _dict_to_qs(params: dict) -> str:
    """将 dict 序列化为 query 字符串。"""
    return "&".join(f"{k}={v}" for k, v in params.items())


def rewrite_download_url(url: str) -> str:
    """重写下载 URL，模拟 123pan_unlock.js 的绕过逻辑。

    将下载请求重定向到 web-pro2 代理，并添加 auto_redirect=0 参数，
    绕过官方 PC 端的下载流量限制。
    """
    try:
        parsed = urlparse(url)
        if "web-pro" in parsed.netloc:
            # 已经是 web-pro 域名，解码 params -> 添加 auto_redirect -> 重新编码
            qs = _qs_to_dict(parsed.query)
            params_b64 = qs.get("params", "")
            if params_b64:
                decoded = b64_decode(params_b64)
                if not decoded:
                    decoded = params_b64
                inner_parsed = urlparse(decoded)
                inner_qs = _qs_to_dict(inner_parsed.query)
                inner_qs["auto_redirect"] = "0"
                new_inner = urlunparse(
                    inner_parsed._replace(query=_dict_to_qs(inner_qs))
                )
                qs["params"] = b64_encode(new_inner)
                return urlunparse(parsed._replace(query=_dict_to_qs(qs)))
            return url
        # 非 web-pro 域名，重写为 web-pro2 代理
        orig_parsed = urlparse(url)
        orig_qs = _qs_to_dict(orig_parsed.query)
        orig_qs["auto_redirect"] = "0"
        rewritten_orig = urlunparse(
            orig_parsed._replace(query=_dict_to_qs(orig_qs))
        )
        proxy_url = urlunparse((
            "https",
            "web-pro2.123952.com",
            "/download-v2/",
            "",
            "params=" + b64_encode(rewritten_orig) + "&is_s3=0",
            "",
        ))
        return proxy_url
    except Exception as e:
        get_logger(__name__).warning("下载 URL 重写失败，使用原始 URL: %s", e)
        return url


def resolve_download_url(transfer_session: requests.Session, url: str) -> str:
    """解析重定向获取真实下载链接。

    优先级：
    1. HTTP 3xx 重定向的 Location 头
    2. HTML body 中的 href='...' 链接
    3. download-v2 URL 中 base64 编码的 params 直接解码

    对应 Flutter 中用 dart:io HttpClient 手动跟随重定向的逻辑。
    """
    logger = get_logger(__name__)

    try:
        resp = transfer_session.get(url, timeout=10, allow_redirects=False)

        # 1. 优先检查 HTTP 重定向 Location 头
        location = resp.headers.get("Location", "")
        if location and resp.status_code in (301, 302, 303, 307, 308):
            if not is_safe_download_url(location):
                logger.warning("拒绝非可信下载重定向: %s", location[:120])
                return url
            logger.debug(
                "下载 URL 已通过 Location 头解析 (status=%s): %s ...",
                resp.status_code,
                location[:80],
            )
            return location

        # 2. 检查 HTML body 中的 href 链接
        text = resp.text[:500]
        match = HREF_URL_RE.search(text)
        if match:
            resolved = match.group(1)
            if not is_safe_download_url(resolved):
                logger.warning("拒绝非可信 HTML 下载链接: %s", resolved[:120])
                return url
            logger.debug("下载 URL 已通过 href 解析: %s ...", resolved[:80])
            return resolved

        logger.debug(
            "下载 URL 未找到重定向，返回原始 URL: status=%s, body=%.100s",
            resp.status_code,
            text,
        )
    except requests.RequestException as e:
        logger.warning("解析下载 URL HTTP 请求失败: %s", e)

    # 3. 兜底：如果是 download-v2 URL，直接解码 base64 params
    decoded = decode_download_v2_params(url)
    if decoded and is_safe_download_url(decoded):
        logger.debug("下载 URL 已通过 base64 params 解码: %s ...", decoded[:80])
        return decoded

    return url


def decode_download_v2_params(url: str) -> str:
    """从 download-v2 URL 中解码 base64 编码的下载链接。

    格式: https://web-pro2.123952.com/download-v2/?params=<base64>&is_s3=0
    返回解码后的 URL，若非 download-v2 格式或解码失败则返回空字符串。
    """
    try:
        parsed = urlparse(url)
        if "/download-v2/" not in parsed.path:
            return ""
        qs = _qs_to_dict(parsed.query)
        params_b64 = qs.get("params", "")
        if not params_b64:
            return ""
        decoded = b64_decode(params_b64)
        if decoded.startswith("http"):
            return decoded
    except Exception:
        pass
    return ""
