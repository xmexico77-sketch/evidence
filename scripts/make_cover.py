"""生成演示视频的封面卡（纯代码绘制，不依赖外部素材）。

为什么单独做：视频开头那 15–20 秒需要一个干净的标题画面，
用系统字体渲染比截图更可控，也不用找设计素材。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "video-shots" / "00-cover.png"

W, H = 1600, 1000
BG = (11, 14, 20)
ACCENT = (96, 165, 250)
FG = (230, 236, 245)
DIM = (150, 162, 180)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
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

    # 左侧一条强调色竖线，呼应界面里的导航高亮
    d.rectangle([120, 300, 126, 620], fill=ACCENT)

    f_title = load_font(96)
    f_sub = load_font(38)
    f_meta = load_font(26)

    d.text((170, 330), "证源 Evidence", font=f_title, fill=FG)
    d.text((174, 460), "带段落级锚点溯源的科研助手 Agent", font=f_sub, fill=ACCENT)

    lines = [
        "每个结论都能点回原文的某一页、某一段",
        "答不出就拒答，不编造引用",
    ]
    y = 560
    for line in lines:
        d.text((176, y), line, font=f_meta, fill=DIM)
        y += 44

    d.text((176, 830), "第九届传智杯 · AI 大模型创新应用挑战赛", font=f_meta, fill=(110, 120, 136))

    img.save(OUT)
    print(f"已生成 {OUT}  {OUT.stat().st_size / 1024:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
