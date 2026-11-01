"""「记住我」凭证的签名与校验。

用途：登录成功后写一个 cookie，让浏览器刷新/关标签页后仍保持登录。
Streamlit 的 session_state 只能活在单个 WebSocket 会话里，刷新即丢，
所以身份必须落到 cookie（跨会话），且必须签名，防止用户自己改。

token 结构：
    base64url("用户名|过期时间戳") . base64url(HMAC-SHA256(secret, 前者))
只签名不加密 —— token 里没有密码，只有用户名和过期时间，可公开。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make(username: str, secret: str, ttl_days: int = 7, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + ttl_days * 86400)
    payload = f"{username}|{expires}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def verify(token: str, secret: str, now: float | None = None) -> str | None:
    """校验通过返回用户名，否则返回 None（签名错、被改过、过期、格式坏都算）。"""
    try:
        payload_b64, sig_b64 = (token or "").split(".", 1)
        payload = _unb64(payload_b64)
        sig = _unb64(sig_b64)
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        username, expires = payload.decode("utf-8").rsplit("|", 1)
        if int(expires) < int(now if now is not None else time.time()):
            return None
        return username or None
    except Exception:
        return None
