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

**为什么来源维度要跳过本机地址**：这台机器上前端 Next.js 通过 Route Handler
把 /api/* 转发给后端，所有外部请求到达后端时源地址都是 127.0.0.1。
如果把本机地址也计入"来源维度"，一个人刷 20 次就会把**所有评审**一起封掉——
本实现第一版就踩了这个坑（自己测试时把全体锁了 15 分钟）。因此：
本机地址只参与账号维度，不参与来源维度。

**取舍**：没有可信代理转发真实客户端 IP 时，来源维度实际失效，防线退化为
"按账号封禁"。这也意味着有人可以故意刷错密码把评审账号锁住——所以
账号维度的阈值放宽到 10 次、封禁缩短到 5 分钟，把可用性损失控制在可接受范围。
真要做到按 IP 防护，需要反代透传 X-Forwarded-For 并在受信网络上部署。

阈值可用环境变量覆盖：
  EVIDENCE_LOGIN_MAX=10       账号维度窗口内最大失败次数
  EVIDENCE_LOGIN_MAX_IP=20    来源维度窗口内最大失败次数
  EVIDENCE_LOGIN_WINDOW=600   窗口长度（秒）
  EVIDENCE_LOGIN_BLOCK=300    账号维度封禁时长（秒）
  EVIDENCE_LOGIN_BLOCK_IP=900 来源维度封禁时长（秒）
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque

MAX_FAILS = int(os.environ.get("EVIDENCE_LOGIN_MAX", "10"))
MAX_FAILS_IP = int(os.environ.get("EVIDENCE_LOGIN_MAX_IP", "20"))
WINDOW = int(os.environ.get("EVIDENCE_LOGIN_WINDOW", "600"))
BLOCK = int(os.environ.get("EVIDENCE_LOGIN_BLOCK", "300"))
BLOCK_IP = int(os.environ.get("EVIDENCE_LOGIN_BLOCK_IP", "900"))

# 这些地址说明请求来自本机代理，不是真实客户端；来源维度对它们无意义
SHARED_PROXY_HOSTS = {"127.0.0.1", "::1", "localhost", "", "unknown"}

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


def _keys(ip: str, username: str) -> list[tuple[str, int, int]]:
    """返回需要检查的 (键, 失败阈值, 封禁秒数)。本机地址不参与来源维度。"""
    keys = [(f"u:{ip}|{username.lower()}", MAX_FAILS, BLOCK)]
    if ip not in SHARED_PROXY_HOSTS:
        keys.append((f"i:{ip}", MAX_FAILS_IP, BLOCK_IP))
    return keys


def check(ip: str, username: str) -> tuple[bool, int]:
    """返回 (是否允许, 剩余封禁秒数)。

    封禁判定优先于失败计数：被封期间无论密码对不对都直接拒绝，
    否则攻击者可以从响应时间上探测密码是否正确。
    """
    now = time.monotonic()
    with _lock:
        for key, _limit, _block in _keys(ip, username):
            until = _blocked_until.get(key)
            if until and until > now:
                return False, int(until - now) + 1
            if until and until <= now:
                _blocked_until.pop(key, None)
        for key, _limit, _block in _keys(ip, username):
            _prune(key, now)
        return True, 0


def fail(ip: str, username: str) -> int:
    """记录一次失败。返回封禁秒数（0 表示还没触发封禁）。"""
    now = time.monotonic()
    triggered = 0
    with _lock:
        for key, limit, block in _keys(ip, username):
            q = _fails.setdefault(key, deque())
            q.append(now)
            _prune(key, now)
            if len(q) >= limit:
                _blocked_until[key] = now + block
                q.clear()
                triggered = max(triggered, block)
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
