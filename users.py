"""本地账号库：用户名 + 密码，不发验证邮件、不依赖第三方登录。

安全说明（重要）：
- 密码用 PBKDF2-HMAC-SHA256（20 万次迭代）+ 每个账号独立 salt 存储，
  不是明文；校验用 hmac.compare_digest 防时序攻击。
- 但这是**演示级**方案：账号库是单个 JSON 文件，Streamlit Cloud 重启会还原，
  也没有找回密码、登录限速、二次验证。生产环境请换成 OIDC 或邮箱验证码。

存储格式（.users.json）：
    {"alice": {"name": "Alice", "hash": "pbkdf2_sha256$200000$<salt>$<hex>"}}
键统一小写，避免 Alice / alice 重复注册。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path

ITERATIONS = 200_000
ALGO = "pbkdf2_sha256"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,20}$")
MIN_PASSWORD = 6


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), ITERATIONS
    )
    return f"{ALGO}${ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = str(stored).split("$")
        if algo != ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", (password or "").encode("utf-8"), salt.encode("utf-8"), int(iters)
        )
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def load(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save(path, users: dict) -> bool:
    try:
        Path(path).write_text(
            json.dumps(users, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def display_name(path, username: str) -> str:
    rec = load(path).get((username or "").strip().lower())
    return rec.get("name", username) if isinstance(rec, dict) else username


def register(path, username: str, password: str) -> tuple[bool, str]:
    """注册。返回 (成功, 提示语或显示名)。"""
    name = (username or "").strip()
    if not USERNAME_RE.match(name):
        return False, "用户名 3–20 位，只能字母、数字、下划线或中文"
    if len(password or "") < MIN_PASSWORD:
        return False, f"密码至少 {MIN_PASSWORD} 位"
    users = load(path)
    key = name.lower()
    if key in users:
        return False, "这个用户名已经被注册了"
    users[key] = {"name": name, "hash": hash_password(password)}
    if not save(path, users):
        return False, "账号库写入失败，暂时无法注册"
    return True, name


def authenticate(path, username: str, password: str) -> tuple[bool, str]:
    """登录。返回 (成功, 提示语或显示名)。失败信息不区分“用户不存在”和“密码错”。"""
    key = (username or "").strip().lower()
    rec = load(path).get(key)
    if not isinstance(rec, dict) or not verify_password(password or "", rec.get("hash", "")):
        return False, "用户名或密码不正确"
    return True, rec.get("name", username)
