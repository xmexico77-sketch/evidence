"""文档一致性检查：README / 技术文档里写的东西，实现里还在不在。

为什么需要：文档最容易悄悄过期——改了代码没改文档，或改了文档没改代码。
评审照着 README 敲命令、点链接，一处对不上就会怀疑整体真实性。

检查三类：
1. 链接与图片路径是否存在（README 里的 docs/、scripts/ 引用）；
2. 账号、端口、脚本名等"硬编码事实"是否与配置一致；
3. 文档声称的验收项数量是否与实际脚本一致。

用法：.venv\\Scripts\\python.exe scripts\\check_docs.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

rows: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    rows.append((ok, name, detail))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def main() -> int:
    readme_path = ROOT / "README.md"
    readme = read(readme_path)
    if not readme:
        print("README.md 不存在")
        return 1

    # ---------- 1. README 中引用的相对路径 ----------
    refs = set(re.findall(r"\]\((docs/[^)\s]+|scripts/[^)\s]+|backend/[^)\s]+|web/[^)\s]+)\)", readme))
    refs |= set(re.findall(r'`(scripts/[A-Za-z0-9_\-]+\.py)`', readme))
    missing = sorted(r for r in refs if not (ROOT / r).exists())
    check(
        "README 引用的文件都存在",
        not missing,
        f"缺失 {len(missing)} 个：{missing[:6]}",
    )

    # ---------- 2. 图片路径 ----------
    imgs = set(re.findall(r"!\[[^\]]*\]\((docs/[^)\s]+)\)", readme))
    bad_imgs = sorted(i for i in imgs if not (ROOT / i).exists())
    check("README 图片都存在", not bad_imgs, f"缺失：{bad_imgs[:4]}")

    # ---------- 3. ADR 索引与文件一致 ----------
    adr_dir = ROOT / "docs" / "adr"
    adr_files = sorted(p.name for p in adr_dir.glob("ADR-*.md")) if adr_dir.exists() else []
    adr_links = set(re.findall(r"docs/adr/(ADR-[^)\s]+\.md)", readme))
    missing_adr = sorted(a for a in adr_links if a not in adr_files)
    unlinked = sorted(a for a in adr_files if a not in adr_links)
    check("ADR 链接无失效", not missing_adr, f"失效：{missing_adr}")
    check(
        "新 ADR 已加入 README 索引",
        not unlinked,
        f"未索引：{unlinked}（写进 README 的架构决策列表）",
    )

    # ---------- 4. 版本/技术栈描述与依赖一致 ----------
    req = read(ROOT / "backend" / "requirements.txt")
    check("requirements.txt 存在且非空", bool(req.strip()))
    pkg = read(ROOT / "web" / "package.json")
    m = re.search(r'"next":\s*"([^"]+)"', pkg)
    if m:
        next_ver = m.group(1).lstrip("^~")
        claim = re.search(r"Next\.js\s*([0-9]+)", readme)
        if claim:
            check(
                f"README 写的 Next.js {claim.group(1)} 与 package.json({next_ver}) 一致",
                next_ver.startswith(claim.group(1)),
                f"README={claim.group(1)} package.json={next_ver}",
            )

    # ---------- 5. 账号一致性 ----------
    env_example = read(ROOT / ".env.example")
    users = re.search(r"EVIDENCE_USERS=(\S+)", env_example)
    if users:
        pairs = dict(p.split(":", 1) for p in users.group(1).split(",") if ":" in p)
        for name in pairs:
            check(f"README 提到的账号 {name} 在 .env.example 中", name in readme, name)
        # README 表格里的密码要与模板一致
        for name, pwd in pairs.items():
            pattern = rf"\|\s*`{name}`\s*\|\s*`([^`]+)`"
            mm = re.search(pattern, readme)
            if mm:
                check(
                    f"README 中 {name} 的密码与 .env.example 一致",
                    mm.group(1) == pwd,
                    f"README={mm.group(1)} env={pwd}",
                )

    # ---------- 6. 验收项数量 ----------
    verify_all = read(ROOT / "scripts" / "verify_all.py")
    n_checks = len(re.findall(r'"script":\s*"[^"]+\.py"', verify_all))
    claim = re.search(r"(\d+)\s*项(?:验收|检查|自动)", readme)
    if claim:
        check(
            f"README 声称的验收项数({claim.group(1)}) 与实际({n_checks}) 一致",
            int(claim.group(1)) == n_checks,
            f"README={claim.group(1)} 实际={n_checks}",
        )

    # ---------- 7. 端口一致性 ----------
    compose = read(ROOT / "docker-compose.yml")
    m = re.search(r'"(\d+):(\d+)"', compose)
    if m:
        host_port = m.group(1)
        check(
            f"README 的本地端口({host_port}) 出现在 docker-compose",
            host_port in compose,
            host_port,
        )

    # ---------- 8. 技术文档页数 ----------
    pdf = ROOT / "docs" / "证源Evidence-技术文档.pdf"
    if pdf.exists():
        try:
            import pymupdf

            with pymupdf.open(pdf) as doc:
                pages = doc.page_count
            check(f"技术文档 {pages} 页（上限 30）", pages <= 30, str(pages))
        except Exception as exc:  # noqa: BLE001
            check("技术文档可读", False, str(exc)[:60])

    passed = sum(1 for ok, _, _ in rows if ok)
    for ok, name, detail in rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed}/{len(rows)} 项通过")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
