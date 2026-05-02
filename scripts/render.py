#!/usr/bin/env python3
"""Generalised renderer driven by EDL JSON.

Usage:
  render.py --edl <edl.json> --out <preview.mp4> [--src <override.mp4>]
            [--format horizontal|vertical] [--grade neutral_punch]
            [--keep-clips]

Reads ranges from EDL, applies framing rotation (cycle of 4) by pick order,
extracts each segment with single grade + 30ms fades, concats lossless.

Framing rotations:
  horizontal (default, 1920x1080):
    0: 100% full
    1: 104% center crop
    2: 100% full reset
    3: 104% shifted right
  vertical (1080x1920, Shorts/TikTok):
    0: center-crop vertical from 1920x1080
    1: center-crop + 108% pseudo-tight
    2: center-crop vertical reset
    3: center-crop + 108% shifted right
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

GRADES = {
    "neutral_punch": (
        "eq=contrast=1.06:brightness=0.0:saturation=1.0,"
        "curves=master='0/0 0.25/0.23 0.75/0.77 1/1'"
    ),
    "screen_punch": (
        "eq=contrast=1.12:brightness=0.0:saturation=1.08,"
        "curves=master='0/0 0.20/0.16 0.80/0.84 1/1',"
        "unsharp=3:3:0.45:3:3:0.0"
    ),
}

HORIZONTAL_FRAMES = [
    "scale=1920:-2",
    "scale=1996:1122:flags=lanczos,crop=1920:1080:38:21",
    "scale=1920:-2,crop=1920:1080:0:0",
    "scale=1996:1122:flags=lanczos,crop=1920:1080:62:21",
]

VERTICAL_FRAMES = [
    "crop=608:1080:656:0,scale=1080:1920:flags=lanczos",
    "scale=2074:1166:flags=lanczos,crop=608:1080:733:43,scale=1080:1920",
    "crop=608:1080:656:0,scale=1080:1920:flags=lanczos",
    "scale=2074:1166:flags=lanczos,crop=608:1080:813:43,scale=1080:1920",
]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def render_segment(src: Path, out: Path, start: float, duration: float,
                   frame_filter: str, grade_filter: str) -> None:
    fade_out_start = max(0.0, duration - 0.03)
    af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out_start}:d=0.03"
    vf = f"{frame_filter},{grade_filter}"
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start}", "-i", str(src), "-t", f"{duration}",
        "-vf", vf, "-af", af,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", "24",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out),
    ])


def concat(segments: list[Path], out: Path) -> None:
    listfile = out.parent / f"_concat_{out.stem}.txt"
    listfile.write_text("\n".join(f"file '{p.resolve()}'" for p in segments) + "\n")
    try:
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(listfile),
            "-c", "copy", "-movflags", "+faststart", str(out),
        ])
    finally:
        listfile.unlink(missing_ok=True)


def probe_duration(path: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(res.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edl", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--src", type=Path, help="override source .mp4")
    ap.add_argument("--format", choices=["horizontal", "vertical"],
                    default="horizontal")
    ap.add_argument("--grade", default="neutral_punch", choices=list(GRADES))
    ap.add_argument("--keep-clips", action="store_true")
    args = ap.parse_args()

    if not args.edl.exists():
        print(f"EDL not found: {args.edl}", file=sys.stderr)
        return 2

    edl = json.loads(args.edl.read_text())
    ranges = edl.get("ranges", [])
    if not ranges:
        print("EDL has no ranges", file=sys.stderr)
        return 3

    sources = edl.get("sources") or {}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    clips_dir = args.out.parent / f"clips_{args.out.stem}"
    clips_dir.mkdir(exist_ok=True)
    for old in clips_dir.glob("seg_*.mp4"):
        old.unlink()

    frames = VERTICAL_FRAMES if args.format == "vertical" else HORIZONTAL_FRAMES
    grade_filter = GRADES[args.grade]

    print(f"=== render: {args.format}, {args.grade}, {len(ranges)} segments ===")
    segments: list[Path] = []
    for i, r in enumerate(ranges):
        if args.src:
            src = args.src
        else:
            key = r.get("source")
            if not key or key not in sources:
                print(f"pick {i}: missing source mapping", file=sys.stderr)
                return 3
            src = Path(sources[key])
        if not src.exists():
            print(f"source not found: {src}", file=sys.stderr)
            return 2

        start = float(r["start"])
        duration = float(r.get("duration_s") or r.get("duration")
                         or (float(r["end"]) - start))
        beat = r.get("beat", f"seg{i:02d}").replace("/", "_")
        frame = frames[i % len(frames)]
        seg_path = clips_dir / f"seg_{i:02d}_{beat}.mp4"
        print(f"  [{i}] {beat}  {start:.3f} → {start + duration:.3f}s "
              f"({duration:.2f}s)  frame[{i % len(frames)}]")
        render_segment(src, seg_path, start, duration, frame, grade_filter)
        segments.append(seg_path)

    print(f"=== concat → {args.out.name} ===")
    concat(segments, args.out)

    if not args.keep_clips:
        shutil.rmtree(clips_dir, ignore_errors=True)

    dur = probe_duration(args.out)
    size_mb = args.out.stat().st_size / 1e6
    print("=== done ===")
    print(f"  output:   {args.out}")
    print(f"  duration: {dur:.2f}s")
    print(f"  size:     {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
