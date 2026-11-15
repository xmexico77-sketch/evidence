"""登录失败限速：防止把演示账号当靶子刷。

为什么要做：提交材料里公开了评审账号密码，任何人都能拿到。
原先 /api/login 没有任何失败计数，可以无限次尝试——一旦有人拿常见密码表
刷这台 2G 小机器，既可能撞开后台（改坏文献库、影响评审看到的内容），
也会拖慢正常访问。这不是理论风险：这台机器 11-14 已经因为应用层 RCE
被打穿过一次。

策略（两条独立的闸门，满足任一即拒绝）：

* **账号维度**：同一 (IP, 用户名) 在窗口内失败 max 次 → 封禁 block 秒；
* **来源维度**：同一 IP 在窗口内失败 max_ip 次 → 封禁 block 秒。

成功后立即清零，避免正常用户被历史失败拖累。

阈值可用环境变量覆盖：
  EVIDENCE_LOGIN_MAX=5        账号维度窗口内最大失败次数
  EVIDENCE_LOGIN_MAX_IP=20    来源维度窗口内最大失败次数
  EVIDENCE_LOGIN_WINDOW=600   窗口长度（秒）
  EVIDENCE_LOGIN_BLOCK=900    封禁时长（秒）
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque

MAX_FAILS = int(os.environ.get("EVIDENCE_LOGIN_MAX", "5"))
MAX_FAILS_IP = int(os.environ.get("EVIDENCE_LOGIN_MAX_IP", "20"))
WINDOW = int(os.environ.get("EVIDENCE_LOGIN_WINDOW", "600"))
BLOCK = int(os.environ.get("EVIDENCE_LOGIN_BLOCK", "900"))

_lock = threading.Lock()
# key -> (失败时间戳队列, 封禁截止时间)
_fails: dict[str, deque[float]] = {}
_blocked_until: dict[str, float] = {}


def _prune(key: str, now: float) -> None:
    q = _fails.get(key)
    if q is None:
        return
    while q and now - q[0] > WINDOW:
        q.popleft()
    if not q:
        _fails.pop(key, None)


def check(ip: str, username: str) -> tuple[bool, int]:
    """返回 (是否允许, 剩余封禁秒数)。

    封禁判定优先于失败计数：被封期间无论密码对不对都直接拒绝，
    否则攻击者可以从响应时间上探测密码是否正确。
    """
    now = time.monotonic()
    user_key = f"u:{ip}|{username.lower()}"
    ip_key = f"i:{ip}"
    with _lock:
        for key in (user_key, ip_key):
            until = _blocked_until.get(key)
            if until and until > now:
                return False, int(until - now) + 1
            if until and until <= now:
                _blocked_until.pop(key, None)
        _prune(user_key, now)
        _prune(ip_key, now)
        return True, 0


def fail(ip: str, username: str) -> int:
    """记录一次失败。返回剩余封禁秒数（0 表示还没触发封禁）。"""
    now = time.monotonic()
    user_key = f"u:{ip}|{username.lower()}"
    ip_key = f"i:{ip}"
    triggered = 0
    with _lock:
        for key, limit in ((user_key, MAX_FAILS), (ip_key, MAX_FAILS_IP)):
            q = _fails.setdefault(key, deque())
            q.append(now)
            _prune(key, now)
            if len(q) >= limit:
                _blocked_until[key] = now + BLOCK
                q.clear()
                triggered = max(triggered, BLOCK)
    return triggered


def succeed(ip: str, username: str) -> None:
    """登录成功：清空该 (IP, 用户名) 的失败记录。

    注意不清 IP 维度的记录——一个 IP 里成功登录一次不代表它没在刷别的账号。
    """
    with _lock:
        _fails.pop(f"u:{ip}|{username.lower()}", None)
        _blocked_until.pop(f"u:{ip}|{username.lower()}", None)


def reset_all() -> None:
    """测试用：清空所有状态。"""
    with _lock:
        _fails.clear()
        _blocked_until.clear()


def stats() -> dict[str, int]:
    with _lock:
        return {"tracked_keys": len(_fails), "blocked_keys": len(_blocked_until)}
