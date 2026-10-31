"""从演示视频脚本里提取每个镜头的旁白，并按镜头合成普通话语音。

为什么按镜头分别合成：每段音频的实际时长就是该镜头的画面时长，
这样解说与画面天然对齐，不需要事后猜时间分配。

用法：
  .venv\\Scripts\\python.exe scripts/make_voiceover.py --dry-run     # 只看解析结果
  .venv\\Scripts\\python.exe scripts/make_voiceover.py               # 全部合成
  .venv\\Scripts\\python.exe scripts/make_voiceover.py --voice zh-CN-YunxiNeural
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_MD = ROOT / "docs" / "演示视频脚本.md"
OUT_DIR = ROOT / "docs" / "voiceover"
MANIFEST = OUT_DIR / "manifest.json"


def find_ffmpeg() -> str:
    for c in (
        ROOT / ".cache" / "ffmpeg" / "ffmpeg.exe",
        *ROOT.glob(".cache/ffmpeg/**/bin/ffmpeg.exe"),
    ):
        if Path(c).exists():
            return str(c)
    from shutil import which

    f = which("ffmpeg")
    if f:
        return f
    raise SystemExit("找不到 ffmpeg")


def probe(ffmpeg_exe: str, audio: Path) -> float:
    ffprobe = Path(ffmpeg_exe).with_name("ffprobe.exe")
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def parse_script() -> list[dict]:
    """按 '### 镜头 N' 切段，取每段 '**旁白**：' 之后到下一个标题之间的引用行。"""
    text = SCRIPT_MD.read_text(encoding="utf-8")
    parts = re.split(r"^###\s+(镜头\s*\d+[^\n]*)$", text, flags=re.M)
    shots: list[dict] = []
    # parts: [前言, 标题1, 正文1, 标题2, 正文2, ...]
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        body = parts[i + 1]
        m = re.search(r"\*\*旁白\*\*[:：]\s*\n((?:>.*\n?)+)", body)
        if not m:
            continue
        lines = [ln.lstrip("> ").strip() for ln in m.group(1).splitlines()]
        narration = "".join(x for x in lines if x)
        if not narration:
            continue
        num = re.search(r"镜头\s*(\d+)", title)
        shots.append(
            {
                "index": int(num.group(1)) if num else len(shots),
                "title": title,
                "text": narration,
                "chars": len(re.sub(r"\s", "", narration)),
            }
        )
    return shots


async def synth(text: str, voice: str, out: Path, rate: str = "+8%") -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out))


def concat(ffmpeg_exe: str, segs: list[Path], gap_ms: int, out: Path) -> None:
    """把各段拼起来，段间插入固定静音。"""
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        silence = tmpdir / "gap.wav"
        subprocess.run(
            [ffmpeg_exe, "-y", "-f", "lavfi", "-i",
             f"anullsrc=channel_layout=mono:sample_rate=24000",
             "-t", f"{gap_ms / 1000:.3f}", str(silence)],
            capture_output=True, check=True,
        )
        listing = tmpdir / "list.txt"
        entries: list[str] = []
        for s in segs:
            entries.append(f"file '{s.as_posix()}'")
            entries.append(f"file '{silence.as_posix()}'")
        listing.write_text("\n".join(entries[:-1]), encoding="utf-8")
        subprocess.run(
            [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c:a", "libmp3lame", "-b:a", "128k", str(out)],
            capture_output=True, check=True,
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="zh-CN-XiaoxiaoNeural", help="Edge TTS 音色")
    ap.add_argument("--rate", default="+8%", help="语速，例如 +8%%")
    ap.add_argument("--gap-ms", type=int, default=450, help="段间静音")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    shots = parse_script()
    if not shots:
        raise SystemExit("没能从脚本里解析出旁白，检查 docs/演示视频脚本.md 的格式")
    print(f"解析到 {len(shots)} 个镜头的旁白：\n")
    for s in shots:
        print(f"  镜头 {s['index']}  {s['chars']:>4} 字  {s['text'][:46]}…")
    total_chars = sum(s["chars"] for s in shots)
    print(f"\n合计 {total_chars} 字，按每分钟 260 字估约 {total_chars / 260:.1f} 分钟")
    if args.dry_run:
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = find_ffmpeg()
    segs: list[Path] = []
    manifest: list[dict] = []
    print()
    for s in shots:
        seg = OUT_DIR / f"shot{s['index']:02d}.mp3"
        asyncio.run(synth(s["text"], args.voice, seg, args.rate))
        dur = probe(ffmpeg_exe, seg)
        segs.append(seg)
        manifest.append({**s, "file": seg.name, "duration": round(dur, 2)})
        print(f"  镜头 {s['index']} 合成完成 {dur:6.1f}s")

    full = OUT_DIR / "narration.mp3"
    concat(ffmpeg_exe, segs, args.gap_ms, full)
    total = probe(ffmpeg_exe, full)
    manifest_out = {
        "voice": args.voice,
        "rate": args.rate,
        "gap_ms": args.gap_ms,
        "total_seconds": round(total, 2),
        "shots": manifest,
    }
    MANIFEST.write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2), encoding="utf-8")

    timing = ",".join(f"{m['duration']:.2f}" for m in manifest)
    # 画面时长必须把段间静音算进去，否则每切一个镜头就早一截，
    # 到最后一个镜头时解说已经跑完了。
    gap_s = args.gap_ms / 1000
    timeline = [round(m["duration"] + (gap_s if i < len(manifest) - 1 else 0), 2)
                for i, m in enumerate(manifest)]
    timeline_str = ",".join(f"{x:.2f}" for x in timeline)
    manifest_out["timeline"] = timeline
    MANIFEST.write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n总时长 {total:.1f}s（{total / 60:.1f} 分钟）")
    print(f"合成文件：{full}")
    print(f"纯语音时长：{timing}")
    print(f"画面时间轴（含段间静音，合计 {sum(timeline):.1f}s）：--timing {timeline_str}")
    print(f"清单：{MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
