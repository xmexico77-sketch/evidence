"""前端冒烟测试：页面可达、导航一致、关键文案存在。

没有浏览器也能验证的东西先验证掉：路由是否 200、SSR 输出里是否有统一导航、
各页是否还残留旧的"← 返回工作台"。

用法：.venv\\Scripts\\python.exe scripts\\test_web.py
"""
from __future__ import annotations

import sys
import urllib.request

WEB = "http://127.0.0.1:3001"

PAGES = {
    # 只放「不依赖客户端数据」的文案：依赖 payload 的区块在 SSR 阶段不存在，
    # 拿它做断言会得到假失败（例如 /graph 的"基石论文"要等 fetch 完成才渲染）。
    "/": ["证源", "科研问答"],
    "/discover": ["论文发现", "排序依据"],
    "/graph": ["局域引用图谱"],
    "/write": ["论文框架生成", "生成规则"],
    "/paper/1706.03762v1": ["标题树", "就本篇提问"],
    "/login": ["登录"],
}

NAV_LABELS = ["工作台", "论文发现", "引用图谱", "论文框架"]

results: list[tuple[bool, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((cond, name, detail))


def fetch(path: str, timeout: float = 30) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{WEB}{path}", timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def main() -> int:
    bodies: dict[str, str] = {}
    for path, needles in PAGES.items():
        code, body = fetch(path)
        check(f"{path} 返回 200", code == 200, f"{code}")
        bodies[path] = body
        for needle in needles:
            check(f"{path} 含「{needle}」", needle in body)

    # 统一导航：除登录页外，每个页面都应出现四个模块入口
    for path in bodies:
        if path == "/login":
            continue
        missing = [l for l in NAV_LABELS if l not in bodies[path]]
        check(f"{path} 导航完整", not missing, f"缺少 {missing}")

    # 旧版散装返回链接应已清理
    stale = [p for p, b in bodies.items() if "← 返回工作台" in b]
    check("无残留的旧返回链接", not stale, str(stale))

    passed = sum(1 for ok, _, _ in results if ok)
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
