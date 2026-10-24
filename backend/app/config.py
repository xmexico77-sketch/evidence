"""全局配置：所有可写目录一律落在项目内，不依赖用户主目录。

原因见 PLAN.md D 节：本机受限令牌无法在用户目录创建/修改文件，
因此 HF_HOME / FASTEMBED_CACHE_PATH / MPLCONFIGDIR / TMP 必须重定向。
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
PDF_DIR = DATA_DIR / "pdf"
PARSED_DIR = DATA_DIR / "parsed"
INDEX_DIR = DATA_DIR / "index"
CACHE_DIR = PROJECT_ROOT / ".cache"


def bootstrap_env() -> None:
    """在 import 任何模型库之前调用，把各类缓存钉在工作区内。"""
    settings = {
        "HF_HOME": CACHE_DIR / "hf",
        "HUGGINGFACE_HUB_CACHE": CACHE_DIR / "hf" / "hub",
        "HF_XET_CACHE": CACHE_DIR / "hf" / "xet",
        "FASTEMBED_CACHE_PATH": CACHE_DIR / "fastembed",
        "MPLCONFIGDIR": CACHE_DIR / "mpl",
        "TMP": CACHE_DIR / "tmp",
        "TEMP": CACHE_DIR / "tmp",
    }
    for key, path in settings.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault(key, str(path))

    for directory in (PDF_DIR, PARSED_DIR, INDEX_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def load_env_files() -> None:
    """按约定加载 .env.local / .env（不覆盖已有环境变量）。

    密钥只经环境变量进入进程；仓库里只有 .env.example，绝不落库。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    for name in (".env.local", ".env"):
        path = PROJECT_ROOT / name
        if path.exists():
            load_dotenv(path, override=False)


bootstrap_env()
load_env_files()
