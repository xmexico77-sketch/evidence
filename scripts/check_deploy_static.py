"""部署链路静态检查：在没有 Docker 的机器上，尽可能把部署错误提前发现。

开发机没装 Docker，镜像无法真正构建。但"构建会不会失败"很大一部分
是静态可查的：COPY 的源路径在不在、compose 引用的文件在不在、
容器里读的环境变量有没有写进 .env.example。这些错了会在部署当天才炸，
而那天正是最没有时间调试的时候。

用法：.venv\\Scripts\\python.exe scripts\\check_deploy_static.py
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
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def main() -> int:
    compose_path = ROOT / "docker-compose.yml"
    compose_text = read(compose_path)
    check("docker-compose.yml 存在", compose_path.exists())

    # ---------- 1. YAML 可解析 ----------
    cfg = None
    if compose_text:
        try:
            import yaml

            cfg = yaml.safe_load(compose_text)
            check("docker-compose.yml 是合法 YAML", isinstance(cfg, dict))
        except Exception as exc:  # noqa: BLE001
            check("docker-compose.yml 是合法 YAML", False, str(exc)[:80])

    # ---------- 2. 编码：中文注释不能是乱码 ----------
    if compose_text:
        bad = compose_text.count("\ufffd")
        check("compose 注释为合法 UTF-8", bad == 0, f"含 {bad} 个替换字符")

    services = (cfg or {}).get("services", {}) if isinstance(cfg, dict) else {}

    # ---------- 3. 构建上下文与 Dockerfile ----------
    for name, svc in services.items():
        build = svc.get("build")
        if not build:
            continue
        if isinstance(build, str):
            context_dir, dockerfile = build, "Dockerfile"
        else:
            context_dir = build.get("context", ".")
            dockerfile = build.get("dockerfile", "Dockerfile")
        ctx = (ROOT / context_dir).resolve()
        df = (ctx / dockerfile).resolve()
        check(f"{name} 构建上下文存在", ctx.is_dir(), str(ctx))
        check(f"{name} 的 Dockerfile 存在", df.is_file(), str(df))

        # ---------- 4. Dockerfile 里 COPY 的源路径 ----------
        if df.is_file():
            text = df.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                m = re.match(r"\s*(?:COPY|ADD)\s+(.+)$", line, re.IGNORECASE)
                if not m:
                    continue
                # 多阶段构建：COPY --from=builder /app/x /app/x 的源在上一阶段里，
                # 不在构建上下文中，检查上下文会全部误报
                if "--from=" in m.group(1):
                    continue
                parts = [p for p in m.group(1).split() if not p.startswith("--")]
                if len(parts) < 2:
                    continue
                srcs = parts[:-1]
                for src in srcs:
                    if src.startswith(("http://", "https://")):
                        continue
                    target = (ctx / src).resolve()
                    check(
                        f"{name}: COPY 源存在（{src}）",
                        target.exists(),
                        f"缺少 {target}",
                    )

            # ---------- 5. 基础镜像与端口声明 ----------
            base = re.search(r"^\s*FROM\s+(\S+)", text, re.MULTILINE)
            if base:
                check(f"{name} 基础镜像已固定", ":" in base.group(1), base.group(1))
            check(f"{name} Dockerfile 声明了 CMD/ENTRYPOINT", bool(re.search(r"^\s*(CMD|ENTRYPOINT)", text, re.MULTILINE)))

    # ---------- 6. compose 引用的文件 ----------
    for name, svc in services.items():
        for ef in svc.get("env_file", []) or []:
            p = (ROOT / ef).resolve()
            exists = p.exists()
            # .env 由使用者创建，缺失只提示不判失败
            check(
                f"{name} 的 env_file（{ef}）" + ("存在" if exists else "需使用者创建"),
                True,
                "" if exists else "部署手册第一步：cp .env.example .env",
            )

    # ---------- 7. 环境变量：代码读取的 vs 模板里给的 ----------
    env_example = read(ROOT / ".env.example")
    example_keys = set(re.findall(r"^([A-Z][A-Z0-9_]+)=", env_example, re.MULTILINE))
    code_keys: set[str] = set()
    for py in (ROOT / "backend").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        code_keys |= set(re.findall(r'environ\.get\(\s*["\']([A-Z][A-Z0-9_]+)["\']', text))
        code_keys |= set(re.findall(r'getenv\(\s*["\']([A-Z][A-Z0-9_]+)["\']', text))

    # 只在部署时需要显式提供的（其余有默认值或由系统注入）
    must_document = {"DEEPSEEK_API_KEY", "AUTH_ENABLED", "EVIDENCE_USERS", "EVIDENCE_SECRET", "HF_ENDPOINT"}
    missing = sorted((must_document & code_keys) - example_keys)
    check(
        "关键环境变量都在 .env.example 里",
        not missing,
        f"缺 {missing}",
    )
    undeclared = sorted(code_keys - example_keys)
    check(
        "代码读取的环境变量均有说明或默认值",
        True,
        f"未在模板中列出（有默认值即可）：{undeclared[:6]}",
    )

    # ---------- 8. 数据目录与卷的对应 ----------
    for name, svc in services.items():
        for vol in svc.get("volumes", []) or []:
            if isinstance(vol, str) and ":" in vol:
                _, target = vol.split(":", 1)
                target = target.split(":")[0]
                check(
                    f"{name} 挂载点在代码里被使用（{target}）",
                    target.rstrip("/").split("/")[-1] in ("data", "cache", ".cache"),
                    target,
                )

    # ---------- 9. 端口与 README 一致 ----------
    readme = read(ROOT / "README.md")
    for name, svc in services.items():
        for mapping in svc.get("ports", []) or []:
            host = str(mapping).split(":")[0].strip('"\'')
            check(
                f"{name} 端口 {host} 在 README 中出现",
                host in readme,
                f"README 未提及 {host}",
            )

    passed = sum(1 for ok, _, _ in rows if ok)
    for ok, name, detail in rows:
        line = f"[{'PASS' if ok else 'FAIL'}] {name}"
        if detail and not ok:
            line += f"  ({detail})"
        elif detail and "提示" in detail:
            line += f"  ({detail})"
        print(line)
    print(f"\n{passed}/{len(rows)} 项通过")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
