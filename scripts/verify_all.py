"""一键验收：把六模块的可复现断言跑成一份报告。

这是交付材料里「输出成果可验证 / 系统运行闭环」的落地物——
评审不必相信演示视频，跑这个脚本就能自己复核。

用法：
  .venv\\Scripts\\python.exe scripts\\verify_all.py            # 全部
  .venv\\Scripts\\python.exe scripts\\verify_all.py --quick    # 跳过需下载模型的项
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
SCRIPTS = ROOT / "scripts"

CHECKS = [
    {
        "name": "解析质量（双栏/标题树/参考文献/锚点）",
        "script": "verify_parse.py",
        "heavy": False,
        "covers": "模块一",
    },
    {
        "name": "跨语言检索（中文问英文论文细粒度事实）",
        "script": "verify_retrieval.py",
        "heavy": True,
        "covers": "模块二",
    },
    {
        "name": "抗幻觉 Guardrails（编号校验/相关性闸门/拒答）",
        "script": "test_antihallucination.py",
        "heavy": False,
        "covers": "模块二",
    },
    {
        "name": "服务层接口（健康/检索/问答/SSE/拒答）",
        "script": "test_api.py",
        "heavy": True,
        "covers": "闭环",
    },
    {
        "name": "引用图谱（版本合并/基石榜/关键边/社区）",
        "script": "verify_graph.py",
        "heavy": False,
        "covers": "模块五",
    },
    {
        "name": "Idea 考古与自动综述（时间约束/保守判定）",
        "script": "verify_futurework.py",
        "heavy": True,
        "covers": "模块五",
    },
    {
        "name": "数据可视化（选型/分轴/图注/可复现脚本）",
        "script": "verify_charts.py",
        "heavy": False,
        "covers": "模块六",
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过需要加载向量模型的检查")
    args = ap.parse_args()

    rows: list[tuple[str, str, str, float]] = []
    for check in CHECKS:
        if args.quick and check["heavy"]:
            rows.append((check["covers"], check["name"], "SKIP", 0.0))
            continue
        started = time.time()
        proc = subprocess.run(
            [str(PY), str(SCRIPTS / check["script"])],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
        )
        elapsed = time.time() - started
        status = "PASS" if proc.returncode == 0 else "FAIL"
        rows.append((check["covers"], check["name"], status, elapsed))
        if status == "FAIL":
            tail = (proc.stdout or "")[-800:] + (proc.stderr or "")[-400:]
            print(f"--- {check['script']} 失败输出 ---\n{tail}\n")

    print("\n" + "=" * 74)
    print(f"{'模块':<8}{'检查项':<36}{'结果':<8}{'耗时':>8}")
    print("-" * 74)
    for covers, name, status, elapsed in rows:
        mark = {"PASS": "通过", "FAIL": "失败", "SKIP": "跳过"}[status]
        print(f"{covers:<8}{name:<36}{mark:<8}{elapsed:>7.1f}s")
    print("=" * 74)

    failed = [r for r in rows if r[2] == "FAIL"]
    skipped = [r for r in rows if r[2] == "SKIP"]
    print(f"通过 {len(rows) - len(failed) - len(skipped)} / 失败 {len(failed)} / 跳过 {len(skipped)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
