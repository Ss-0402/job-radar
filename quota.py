"""按用户计的每日免费额度。纯函数 + 单文件存储，方便单独测试。

存储格式（.ai_quota.json）：
    {"date": "2026-10-31", "users": {"a@b.com": 2}, "total": 7}

- date 不是今天就整体清零（按天重置）
- users 记录每个登录账号今天用了几次
- total 是全站当天总次数，用来兜底防刷

注意：Streamlit Cloud 的容器文件系统不持久，重启/重新部署后这个文件会还原，
额度也就跟着重置。对演示项目够用；要真正持久得换外部存储（Supabase / Redis 等）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _today(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d")


def _load(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _state(path, now: datetime | None = None) -> dict:
    """读出来并按需迁移/重置，返回 {date, users, total}。"""
    data = _load(path)
    today = _today(now)

    if data.get("date") != today:
        return {"date": today, "users": {}, "total": 0}

    users = data.get("users")
    if not isinstance(users, dict):
        users = {}

    total = data.get("total")
    if total is None:
        # 兼容 v3.7 的老格式：{"date": ..., "count": N}
        total = data.get("count", 0)
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0

    clean = {}
    for k, v in users.items():
        try:
            clean[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return {"date": today, "users": clean, "total": max(total, 0)}


def used_today(path, user: str, now: datetime | None = None) -> int:
    return int(_state(path, now)["users"].get(user, 0))


def remaining(path, user: str, per_day: int, now: datetime | None = None) -> int:
    return max(int(per_day) - used_today(path, user, now), 0)


def total_used_today(path, now: datetime | None = None) -> int:
    return int(_state(path, now)["total"])


def try_take(
    path,
    user: str,
    per_day: int,
    global_cap: int | None = None,
    now: datetime | None = None,
) -> bool:
    """占用一次额度，成功返回 True。

    写盘失败也返回 True —— 宁可多花几分钱，也不能让页面因为文件权限报错。
    并发下可能少记一两次，对演示项目可以接受。
    """
    data = _state(path, now)
    uid = str(user or "anonymous")

    if int(data["users"].get(uid, 0)) >= int(per_day):
        return False
    if global_cap is not None and data["total"] >= int(global_cap):
        return False

    data["users"][uid] = int(data["users"].get(uid, 0)) + 1
    data["total"] += 1
    try:
        Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return True
