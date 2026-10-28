"""演示视频合成：把界面截图与配音合成为 1080p MP4。

设计前提：
- 讲解音频由作者本人录制（赛题要求普通话讲解），本脚本只做合成；
- 画面由 scripts/ui_shot.py 抓取的截图构成，按镜头脚本排序；
- 不依赖剪映/Premiere，一条命令产出可提交的 mp4。

用法：
  # 1) 先看有哪些镜头（不改文件）
  .venv\\Scripts\\python.exe scripts/build_video.py --audio 讲解.m4a --dry-run

  # 2) 正式合成
  .venv\\Scripts\\python.exe scripts/build_video.py --audio 讲解.m4a --out docs/演示视频.mp4

  # 3) 没有音频时先验证管线（生成静音占位，仅供自测）
  .venv\\Scripts\\python.exe scripts/build_video.py --silent 8:00 --out docs/pipeline-test.mp4

时间分配：默认按脚本里的权重把音频总时长分给各镜头；
也可以用 --timing 指定每个镜头的秒数。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOT_DIR = ROOT / "docs" / "preview"
FIGS = ROOT / "docs" / "figures-ui"

# 镜头顺序与权重，对应 docs/演示视频脚本.md 的九段分镜
SHOTS: list[dict] = [
    {"name": "01-ask", "file": FIGS / "01-ask.png", "weight": 2.0,
     "caption": "① 带锚点的问答：每句结论可回到原文某页某段"},
    {"name": "02-reader", "file": FIGS / "02-reader.png", "weight": 2.0,
     "caption": "② 版式保真阅读：原版式 PDF、标题树、段落锚点三栏联动"},
    {"name": "03-graph", "file": FIGS / "03-graph.png", "weight": 1.6,
     "caption": "③ 引用图谱：基石论文识别与社区划分"},
    {"name": "04-compare", "file": FIGS / "04-compare.png", "weight": 1.6,
     "caption": "④ 跨篇对比：不确定之处明确写“未明确阐述”"},
    {"name": "05-discover", "file": FIGS / "05-discover.png", "weight": 1.0,
     "caption": "⑤ 论文发现：可复现性加权推荐"},
    {"name": "06-write", "file": FIGS / "06-write.png", "weight": 1.0,
     "caption": "⑥ 论文框架：提纲与草稿，引用逐条核验"},
]


def find_ffmpeg() -> str:
    """优先用工作区里的便携版，其次 PATH。"""
    for candidate in (
        ROOT / ".cache" / "ffmpeg" / "ffmpeg.exe",
        *ROOT.glob(".cache/ffmpeg/**/bin/ffmpeg.exe"),
        *ROOT.glob(".cache/ffmpeg/**/ffmpeg.exe"),
    ):
        if Path(candidate).exists():
            return str(candidate)
    from shutil import which

    found = which("ffmpeg")
    if found:
        return found
    raise SystemExit(
        "找不到 ffmpeg。放到 .cache/ffmpeg/ 下，或装到 PATH 里。\n"
        "下载地址：https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    )


def probe_duration(ffmpeg_exe: str, audio: Path) -> float:
    """用 ffmpeg 自带的 ffprobe 取时长。"""
    ffprobe = Path(ffmpeg_exe).with_name("ffprobe.exe")
    if not ffprobe.exists():
        from shutil import which

        found = which("ffprobe")
        if not found:
            raise SystemExit("找不到 ffprobe")
        ffprobe = Path(found)
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def plan(timing: list[float] | None, total: float) -> list[float]:
    if timing:
        if len(timing) != len(SHOTS):
            raise SystemExit(f"--timing 需要 {len(SHOTS)} 个秒数")
        return timing
    weight_sum = sum(s["weight"] for s in SHOTS)
    return [round(total * s["weight"] / weight_sum, 2) for s in SHOTS]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", help="讲解音频（m4a/mp3/wav）")
    ap.add_argument("--silent", help="无音频自测：给定时长 MM:SS，生成静音占位")
    ap.add_argument("--out", default="docs/演示视频.mp4")
    ap.add_argument("--timing", help="逗号分隔的每镜头秒数")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    missing = [s["name"] for s in SHOTS if not Path(s["file"]).exists()]
    if missing:
        print(f"[错误] 缺少截图：{missing}\n先把画面抓齐：scripts/ui_shot.py 或从 docs/preview 复制到 docs/figures-ui")
        return 1

    if args.audio:
        audio = Path(args.audio)
        if not audio.exists():
            raise SystemExit(f"音频不存在：{audio}")
        ffmpeg_exe = find_ffmpeg()
        total = probe_duration(ffmpeg_exe, audio)
        print(f"音频：{audio.name}  时长 {total:.1f}s")
    elif args.silent:
        mm, ss = args.silent.split(":")
        total = int(mm) * 60 + int(ss)
        ffmpeg_exe = find_ffmpeg()
        audio = None
        print(f"静音占位：{total}s（仅用于验证管线）")
    else:
        raise SystemExit("要么给 --audio，要么给 --silent MM:SS")

    timing = [float(x) for x in args.timing.split(",")] if args.timing else None
    durations = plan(timing, total)
    print(f"\n镜头 {len(SHOTS)} 个，合计 {sum(durations):.1f}s")
    for shot, dur in zip(SHOTS, durations):
        print(f"  {dur:6.1f}s  {shot['name']:<12} {shot['caption']}")

    if args.dry_run:
        print("\n（dry-run，未生成文件）")
        return 0

    # 每张图先做成固定时长的片段，再拼接；最后混入音频
    from tempfile import TemporaryDirectory

    out_path = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    W, H = 1920, 1080

    with TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        segs: list[Path] = []
        for i, (shot, dur) in enumerate(zip(SHOTS, durations)):
            seg = tmp_dir / f"seg{i:02d}.mp4"
            # 等比缩放并加黑边到 1920x1080；底部留白给字幕
            vf = (
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0b0e14"
            )
            cmd = [
                ffmpeg_exe, "-y", "-loop", "1", "-i", str(shot["file"]),
                "-t", f"{dur:.2f}", "-vf", vf, "-r", str(args.fps),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
                str(seg),
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            segs.append(seg)

        concat_list = tmp_dir / "list.txt"
        concat_list.write_text(
            "\n".join(f"file '{s.as_posix()}'" for s in segs), encoding="utf-8"
        )
        merged = tmp_dir / "merged.mp4"
        subprocess.run(
            [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", str(merged)],
            capture_output=True, check=True,
        )

        if audio is None:
            # 静音占位
            subprocess.run(
                [ffmpeg_exe, "-y", "-i", str(merged), "-f", "lavfi", "-i",
                 "anullsrc=channel_layout=stereo:sample_rate=44100",
                 "-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                 str(out_path)],
                capture_output=True, check=True,
            )
        else:
            subprocess.run(
                [ffmpeg_exe, "-y", "-i", str(merged), "-i", str(audio),
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                 "-shortest", "-movflags", "+faststart", str(out_path)],
                capture_output=True, check=True,
            )

    size_mb = out_path.stat().st_size / 1e6
    print(f"\n已生成 {out_path}  {size_mb:.1f}MB")
    print(f"分辨率 {W}x{H} @{args.fps}fps，时长约 {sum(durations):.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
