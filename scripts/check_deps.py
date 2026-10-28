"""依赖完整性检查：代码 import 的第三方包，是否都写进了 requirements.txt。

为什么这项重要：镜像里只 `pip install -r requirements.txt`，开发机上却可能
因为系统里早有某个包而"看起来能跑"。漏写一个，换台机器或进容器就 ImportError，
而且往往发生在演示前最不方便的时刻。

用法：.venv\\Scripts\\python.exe scripts\\check_deps.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "backend" / "requirements.txt"

# import 名 → PyPI 包名（只在两者不一致时列出）
IMPORT_TO_PYPI = {
    "fitz": "pymupdf",
    "pymupdf4llm": "pymupdf4llm",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "docx": "python-docx",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "jieba": "jieba",
    "rank_bm25": "rank-bm25",
    "rapidocr_onnxruntime": "rapidocr-onnxruntime",
    "sse_starlette": "sse-starlette",
    "dotenv": "python-dotenv",
    "multipart": "python-multipart",
    "onnxruntime": "onnxruntime",
    "fastembed": "fastembed",
    "networkx": "networkx",
    "matplotlib": "matplotlib",
    "pandas": "pandas",
    "numpy": "numpy",
    "scipy": "scipy",
    "httpx": "httpx",
    "pydantic": "pydantic",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "orjson": "orjson",
    "aiosqlite": "aiosqlite",
    "tenacity": "tenacity",
    "psutil": "psutil",
    "pymupdf": "pymupdf",
}

STDLIB = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "concurrent",
    "contextlib", "copy", "csv", "dataclasses", "datetime", "decimal", "difflib",
    "enum", "functools", "glob", "hashlib", "heapq", "hmac", "html", "http",
    "importlib", "inspect", "io", "itertools", "json", "logging", "math",
    "mimetypes", "os", "pathlib", "pickle", "platform", "pprint", "queue",
    "random", "re", "secrets", "shutil", "signal", "socket", "sqlite3",
    "statistics", "string", "subprocess", "sys", "tempfile", "textwrap",
    "threading", "time", "traceback", "types", "typing", "unicodedata",
    "urllib", "uuid", "warnings", "weakref", "xml", "zipfile", "zoneinfo",
}


def declared_from(path: Path) -> set[str]:
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        re.split(r"[=<>!~]", line.strip(), maxsplit=1)[0].lower().replace("_", "-")
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def top_level_imports(path: Path) -> set[str]:
    """取一个 .py 文件里所有顶层 import 的包名。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # 相对导入（level>0）与本地包不算第三方依赖
            if node.level or not node.module:
                continue
            names.add(node.module.split(".")[0])
    return names


def main() -> int:
    if not REQ.exists():
        print("backend/requirements.txt 不存在")
        return 1

    # 后端运行时依赖 与 脚本侧依赖分开声明：
    # 镜像里只装前者，所以后端 import 必须在前者里；
    # 脚本（文档生成、截图、压测）允许用后者。
    backend_declared = declared_from(REQ)
    script_declared = declared_from(ROOT / "requirements-scripts.txt")
    all_declared = backend_declared | script_declared

    # 本地包名，不算外部依赖
    local = {"app", "scripts", "tests"}

    backend_uses: dict[str, set[str]] = {}
    script_uses: dict[str, set[str]] = {}
    for py in (ROOT / "backend").rglob("*.py"):
        for name in top_level_imports(py):
            if name in STDLIB or name in local or name.startswith("_"):
                continue
            backend_uses.setdefault(name, set()).add(str(py.relative_to(ROOT)))
    for py in (ROOT / "scripts").rglob("*.py"):
        for name in top_level_imports(py):
            if name in STDLIB or name in local or name.startswith("_"):
                continue
            script_uses.setdefault(name, set()).add(str(py.relative_to(ROOT)))

    def pypi(name: str) -> str:
        return IMPORT_TO_PYPI.get(name, name).lower().replace("_", "-")

    backend_missing = {n: f for n, f in backend_uses.items() if pypi(n) not in backend_declared}
    script_missing = {n: f for n, f in script_uses.items() if pypi(n) not in all_declared}

    print(
        f"后端 import {len(backend_uses)} 个（已声明 {len(backend_declared)}）  "
        f"脚本 import {len(script_uses)} 个（另有脚本依赖 {len(script_declared)} 条）\n"
    )
    if backend_missing:
        print("后端运行时缺少声明（镜像里会 ImportError）：")
        for name, files in sorted(backend_missing.items()):
            print(f"  - {name:<18} {sorted(files)[:2]}")
    if script_missing:
        print("脚本缺少声明（requirements.txt 或 requirements-scripts.txt 都没写）：")
        for name, files in sorted(script_missing.items()):
            print(f"  - {name:<18} {sorted(files)[:2]}")
    if backend_missing or script_missing:
        return 1

    print("全部已声明：后端依赖在 backend/requirements.txt，脚本依赖在其中或 requirements-scripts.txt。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
