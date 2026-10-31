"""生成演示视频的收尾卡（纯代码绘制）。

与封面呼应，最后 20-30 秒停留在这个画面上，配旁白的收尾句。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "video-shots" / "09-closing.png"

W, H = 1600, 1000
BG = (11, 14, 20)
ACCENT = (96, 165, 250)
FG = (230, 236, 245)
DIM = (150, 162, 180)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # 与封面同一视觉语言：左侧强调色竖线
    d.rectangle([120, 330, 126, 620], fill=ACCENT)

    d.text((170, 350), "证源 Evidence", font=load_font(84), fill=FG)
    d.text((174, 470), "让每一个结论，都能回到原文", font=load_font(42), fill=ACCENT)

    f_small = load_font(24)
    d.text((176, 560), "代码 · 技术文档 · 验收脚本 均已开源", font=f_small, fill=DIM)
    d.text((176, 600), "16 项自动验收，一条命令可复现", font=f_small, fill=DIM)

    d.text((176, 840), "第九届传智杯 · AI 大模型创新应用挑战赛 · B 组", font=f_small, fill=(110, 120, 136))

    img.save(OUT)
    print(f"已生成 {OUT}  {OUT.stat().st_size / 1024:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
