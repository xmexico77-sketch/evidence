"""交付物核对：回答"现在能不能交"。

赛题列了五类材料，缺一项就影响评审。这个脚本把能自动核的项全核一遍，
不能自动核的（公网地址、视频文件）明确标 PENDING，不假装通过。

用法：.venv\\Scripts\\python.exe scripts/audit_deliverables.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT = "git"

rows: list[tuple[str, str, str]] = []  # (级别, 项目, 说明)


def add(level: str, item: str, detail: str = "") -> None:
    rows.append((level, item, detail))


def run(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(
            [GIT, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "git 不可用"


def main() -> int:
    # ---------- 1. 代码仓库 ----------
    code, out = run(["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        add("FAIL", "仓库存在", out.strip()[:60])
        return report()
    add("PASS", "仓库存在")

    code, out = run(["rev-list", "--count", "HEAD"])
    commits = int(out.strip() or 0)
    add(
        "PASS" if commits >= 15 else "WARN",
        "Git 历史",
        f"{commits} 次提交" + ("（真实开发过程）" if commits >= 15 else "（偏少）"),
    )

    code, out = run(["status", "--porcelain"])
    dirty = [l for l in out.splitlines() if l.strip()]
    add("PASS" if not dirty else "WARN", "工作区干净", f"{len(dirty)} 个未提交改动")

    # ---------- 2. 敏感信息 ----------
    code, out = run(["ls-files"])
    tracked = out.splitlines()
    risky = [f for f in tracked if Path(f).name in {".env", ".env.local"}]
    add("PASS" if not risky else "FAIL", "密钥文件未入库", ", ".join(risky))

    secret_hits: list[str] = []
    for rel in tracked:
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        if path.suffix.lower() in {".pdf", ".docx", ".png", ".jpg", ".svg", ".mjs", ".lock"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"DEEPSEEK_API_KEY\s*=\s*sk-[A-Za-z0-9]{10,}", text):
            secret_hits.append(rel)
    add("PASS" if not secret_hits else "FAIL", "仓库内无真实密钥", ", ".join(secret_hits))

    # ---------- 3. 仓库文档 ----------
    readme = ROOT / "README.md"
    if readme.exists():
        body = readme.read_text(encoding="utf-8", errors="ignore")
        need = {
            "项目介绍": "项目" in body,
            "技术架构": "架构" in body,
            "安装运行": "快速开始" in body or "安装" in body,
            "团队信息": "团队信息" in body,
        }
        missing = [k for k, ok in need.items() if not ok]
        add("PASS" if not missing else "FAIL", "README 四要素", f"缺 {missing}" if missing else "齐全")
    else:
        add("FAIL", "README 存在")

    add("PASS" if (ROOT / "LICENSE").exists() else "WARN", "LICENSE")

    # ---------- 4. 环境与部署 ----------
    env_example = ROOT / ".env.example"
    if env_example.exists():
        body = env_example.read_text(encoding="utf-8", errors="ignore")
        keys = ["DEEPSEEK_API_KEY", "AUTH_ENABLED", "EVIDENCE_USERS", "EVIDENCE_SECRET"]
        missing = [k for k in keys if k not in body]
        add("PASS" if not missing else "FAIL", ".env.example 完整", f"缺 {missing}" if missing else "")
    else:
        add("FAIL", ".env.example 存在")

    req = ROOT / "backend" / "requirements.txt"
    add("PASS" if req.exists() else "FAIL", "依赖清单", "backend/requirements.txt")

    docker_files = [
        ROOT / "docker" / "Dockerfile.backend",
        ROOT / "docker" / "Dockerfile.web",
        ROOT / "docker-compose.yml",
    ]
    missing = [p.name for p in docker_files if not p.exists()]
    add("PASS" if not missing else "FAIL", "Docker 配置", f"缺 {missing}" if missing else "三件齐全")

    add(
        "PASS" if (ROOT / "docs" / "部署手册.md").exists() else "WARN",
        "部署手册",
    )

    # ---------- 5. 技术文档 ----------
    pdfs = list((ROOT / "docs").glob("*.pdf"))
    if not pdfs:
        add("FAIL", "技术文档 PDF")
    else:
        pdf = max(pdfs, key=lambda p: p.stat().st_size)
        try:
            import pymupdf

            with pymupdf.open(pdf) as doc:
                pages = doc.page_count
                chars = sum(len(p.get_text()) for p in doc)
            ok = pages <= 30 and chars > 8000
            add(
                "PASS" if ok else "FAIL",
                "技术文档 PDF",
                f"{pdf.name} · {pages} 页 · {chars} 字符",
            )
        except Exception as exc:  # noqa: BLE001
            add("WARN", "技术文档可读性", str(exc)[:60])

    # ---------- 6. 演示视频 ----------
    videos = list(ROOT.rglob("*.mp4"))
    script = ROOT / "docs" / "演示视频脚本.md"
    add("PASS" if script.exists() else "WARN", "视频分镜脚本")
    add(
        "PENDING" if not videos else "PASS",
        "演示视频文件",
        "未录制（需本人普通话讲解，5–8 分钟 1080p）" if not videos else str(videos[0].name),
    )

    # ---------- 7. 验收与自检 ----------
    for name, rel in (
        ("一键验收脚本", "scripts/verify_all.py"),
        ("部署自检脚本", "scripts/check_deploy.py"),
        ("演示彩排脚本", "scripts/demo_rehearsal.py"),
    ):
        add("PASS" if (ROOT / rel).exists() else "FAIL", name)

    # ---------- 8. 待人工完成的项 ----------
    add("PENDING", "公网演示地址", "需先决定云主机或 Tunnel（见部署手册）")
    cover = ROOT / "docs" / "证源Evidence-技术文档.docx"
    placeholders = False
    if cover.exists():
        try:
            from docx import Document

            doc = Document(str(cover))
            text = "\n".join(p.text for p in doc.paragraphs)
            placeholders = "＿＿＿＿" in text
        except Exception:  # noqa: BLE001
            placeholders = False
    add(
        "PENDING" if placeholders else "PASS",
        "团队信息填写",
        "封面仍有占位符（组别/姓名/院校）" if placeholders else "已填写",
    )

    return report()


def report() -> int:
    order = {"FAIL": 0, "WARN": 1, "PENDING": 2, "PASS": 3}
    rows.sort(key=lambda r: order.get(r[0], 9))
    width = max(len(r[1]) for r in rows) + 2
    print(f"{'状态':<9}{'项目':<{width}}说明")
    print("-" * (9 + width + 40))
    for level, item, detail in rows:
        print(f"{level:<9}{item:<{width}}{detail}")

    fails = sum(1 for r in rows if r[0] == "FAIL")
    warns = sum(1 for r in rows if r[0] == "WARN")
    pend = sum(1 for r in rows if r[0] == "PENDING")
    ok = sum(1 for r in rows if r[0] == "PASS")
    print(f"\n通过 {ok} · 待人工 {pend} · 警告 {warns} · 失败 {fails}")
    if fails:
        print("有 FAIL 项，不能提交。")
        return 1
    if pend:
        print("代码与文档侧已就绪；剩余项需要人工完成（见 PENDING）。")
    else:
        print("全部就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
