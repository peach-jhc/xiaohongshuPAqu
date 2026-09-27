"""筛选横竖屏并按配置时间切割无水印原视频。"""

from configparser import ConfigParser
from pathlib import Path
import json
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def is_yes(value):
    return value.strip().lower() in {"是", "true", "1", "yes", "y"}


print("吉航程变得很有钱")
def settings():
    cfg = ConfigParser()
    cfg.read(HERE / "config.txt", encoding="utf-8-sig")
    s = cfg["切割视频"]
    source, output = s.get("输入目录", "").strip(), s.get("输出目录", "").strip()
    direction = s.get("画面方向", "全部").strip()
    if direction not in {"全部", "竖屏", "横屏"}:
        raise ValueError("画面方向只能填写：全部、竖屏或横屏。")
    return {
        "source": Path(source) if source else HERE / "无水印原视频",
        "output": Path(output) if output else HERE / "切割后视频",
        "direction": direction,
        "start": s.getfloat("开始时间", fallback=0),
        "end": s.getfloat("结束时间", fallback=0),
        "group": is_yes(s.get("启用分组", "否")),
        "size": max(1, s.getint("每组数量", fallback=19)),
        "crf": s.getint("视频质量", fallback=18),
        "skip": is_yes(s.get("跳过已有视频", "是")),
    }


def video_info(path):
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height,duration:stream_tags=rotate:stream_side_data=rotation",
               "-show_entries", "format=duration", "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if result.returncode:
        raise RuntimeError("无法读取视频信息")
    data = json.loads(result.stdout)
    stream = data.get("streams", [{}])[0]
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    rotation = int(stream.get("tags", {}).get("rotate", 0) or 0)
    for item in stream.get("side_data_list", []):
        rotation = int(item.get("rotation", rotation) or rotation)
    if abs(rotation) in {90, 270}:
        width, height = height, width
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    return width, height, duration


def wanted(direction, width, height):
    return direction == "全部" or (direction == "竖屏" and height > width) or (direction == "横屏" and width > height)


def cut(source, target, start, end, crf):
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-ss", str(start), "-i", str(source), "-t", str(end - start),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(target)]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="ignore")
    return result.returncode == 0 and target.exists() and target.stat().st_size >= 20_000


def main():
    s = settings()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("找不到 ffmpeg/ffprobe，请先安装并加入 PATH。")
    if not s["source"].exists():
        raise FileNotFoundError(f"找不到无水印原视频目录：{s['source']}")
    if s["end"] <= s["start"]:
        raise ValueError("结束时间必须大于开始时间。")
    s["output"].mkdir(parents=True, exist_ok=True)
    # 纯数字文件名按数值排序，确保顺序是 1、2、3……而不是 1、10、2。
    videos = sorted(
        s["source"].glob("*.mp4"),
        key=lambda item: (0, int(item.stem)) if item.stem.isdigit() else (1, item.name.lower())
    )
    exported = filtered = short = failed = 0
    for scan_index, source in enumerate(videos, 1):
        try:
            width, height, duration = video_info(source)
            if not wanted(s["direction"], width, height):
                filtered += 1
                continue
            if duration < s["end"]:
                short += 1
                continue
            output_index = exported + 1
            if s["group"]:
                group_no = (output_index - 1) // s["size"] + 1
                folder = s["output"] / f"group_{group_no:02d}"
            else:
                # 不分组也建立一个文件夹，绝不把视频散放在输出根目录。
                folder = s["output"] / "all_videos"
            target = folder / f"{output_index}.mp4"
            print(f"[{scan_index}/{len(videos)}] {width}x{height} → {target.relative_to(s['output'])}")
            if s["skip"] and target.exists() and target.stat().st_size >= 20_000:
                exported += 1
            elif cut(source, target, s["start"], s["end"], s["crf"]):
                exported += 1
            else:
                failed += 1
        except Exception as exc:
            print(f"处理失败：{source.name}：{exc}")
            failed += 1
    print(f"切割完成：导出 {exported}，方向过滤 {filtered}，时长不足 {short}，失败 {failed}")
    print(f"切割后视频位置：{s['output']}")


if __name__ == "__main__":
    main()
