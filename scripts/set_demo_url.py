"""统一更新提交材料里的演示地址。

背景：演示地址变过好几次（Cloudflare 快速隧道每次重启都换域名），
手动改 docs/提交清单.md 与 docs/交接说明.md 容易漏、也容易改错格式。
这个脚本把"换地址"变成一条命令。

用法：
  .venv\\Scripts\\python.exe scripts/set_demo_url.py --url http://1.12.228.44:3000 --dry-run
  .venv\\Scripts\\python.exe scripts/set_demo_url.py --url http://1.12.228.44:3000 --commit
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    ROOT / "docs" / "提交清单.md",
    ROOT / "docs" / "交接说明.md",
    ROOT / "docs" / "部署手册.md",
]

# 匹配曾经用过的地址形态，替换成新地址
PATTERNS = [
    re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com"),
    re.compile(r"http://\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}"),
]

# 账号密码行：reviewer / 密码
PWD_PATTERN = re.compile(r"(`reviewer`[^\n]{0,40}?)(`[0-9a-f]{8,}`)")
ROOT_PASS = re.compile(r"(评审密码[^\n]{0,20}?)([0-9a-f]{12})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="新的演示地址，例如 http://1.12.228.44:3000")
    ap.add_argument("--password", help="评审密码（可选，一并更新）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit", action="store_true", help="改完自动提交")
    args = ap.parse_args()

    url = args.url.rstrip("/")
    total_files = 0
    total_repl = 0

    for path in TARGETS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new = text
        count = 0
        for pat in PATTERNS:
            new, n = pat.subn(url, new)
            count += n
        if args.password:
            new, n1 = PWD_PATTERN.subn(lambda m: m.group(1) + f"`{args.password}`", new)
            new, n2 = ROOT_PASS.subn(lambda m: m.group(1) + args.password, new)
            count += n1 + n2

        if new != text:
            total_files += 1
            total_repl += count
            print(f"{path.name}: 替换 {count} 处")
            if not args.dry_run:
                path.write_text(new, encoding="utf-8")
        else:
            print(f"{path.name}: 无需改动")

    print(f"\n合计 {total_files} 个文件、{total_repl} 处")
    if args.dry_run:
        print("（dry-run，未写入）")
        return 0
    if total_repl == 0:
        print("没有匹配到旧地址，检查是否已被替换过")
        return 0

    if args.commit:
        git = "git"
        for c in ("git", r"D:\\deepseek\\tools\\git\\cmd\\git.exe"):
            try:
                subprocess.run([c, "--version"], capture_output=True, check=True, timeout=10)
                git = c
                break
            except Exception:  # noqa: BLE001
                continue
        msg = f"docs: 演示地址更新为 {url}"
        if args.password:
            msg += "（含评审密码）"
        subprocess.run([git, "-C", str(ROOT), "add", "-A"], check=False)
        subprocess.run([git, "-C", str(ROOT), "commit", "-m", msg], check=False)
        print("已提交（推送用 git push）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
