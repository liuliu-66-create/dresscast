#!/usr/bin/env python3
"""
带货视频生成脚本。
调用阿里云百炼 wan2.7-i2v API，基于融合图生成带货视频。

Usage:
    python generate_video.py --image <path> --prompt <text> --output <path> [--resolution 720P]

Returns:
    JSON: {"success": true, "video_path": "...", "video_url": "..."}
"""

import argparse
import base64
import io
import json
import os
import sys
import requests
from pathlib import Path

# Windows 终端 UTF-8 输出，避免中文乱码
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"

# DashScope 图生视频端点（异步）
VIDEO_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_api_key() -> str:
    config = load_config()
    key = config.get("dashscope", {}).get("api_key", "")
    if key:
        return key
    return os.environ.get("DASHSCOPE_API_KEY", "")


def get_video_model() -> str:
    config = load_config()
    return config.get("dashscope", {}).get("video_model", "wan2.7-i2v")


def encode_image_base64(image_path: str) -> str:
    """将图片编码为 Base64 data URI"""
    path = Path(image_path)
    if not path.exists():
        print(f"Error: 图片不存在: {image_path}", file=sys.stderr)
        sys.exit(1)

    suffix = path.suffix.lower().lstrip(".")
    mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "bmp": "bmp", "webp": "webp"}
    mime = f"image/{mime_map.get(suffix, 'jpeg')}"
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{data}"


def submit_video_task(api_key: str, model: str, image_url: str, prompt: str,
                      resolution: str, duration: int = 5, audio: bool = True) -> dict:
    """提交图生视频异步任务"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-DashScope-Async": "enable",
    }

    # wan2.7-i2v 使用 input.media 数组格式，旧版用 input.img_url
    if "2.7" in model:
        payload = {
            "model": model,
            "input": {
                "media": [{"type": "first_frame", "url": image_url}],
                "prompt": prompt,
            },
            "parameters": {
                "resolution": resolution,
            }
        }
    else:
        payload = {
            "model": model,
            "input": {
                "img_url": image_url,
                "prompt": prompt,
            },
            "parameters": {
                "resolution": resolution,
            }
        }

    # wan2.6 系列支持 duration 和 audio 参数
    if "2.6" in model:
        payload["parameters"]["duration"] = duration
        payload["parameters"]["prompt_extend"] = True
        if "flash" in model:
            payload["parameters"]["audio"] = audio

    try:
        resp = requests.post(VIDEO_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()

        if "code" in result and "output" not in result:
            return {"error": f"API 错误: {result.get('code')} - {result.get('message')}"}

        task_id = result.get("output", {}).get("task_id", "")
        if not task_id:
            return {"error": "未返回 task_id", "response": result}

        return {"success": True, "task_id": task_id}

    except requests.RequestException as e:
        return {"error": f"请求失败: {str(e)}"}


def download_video(url: str, output_path: str) -> bool:
    """下载视频到本地"""
    try:
        resp = requests.get(url, timeout=300, stream=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_mb = Path(output_path).stat().st_size / (1024 * 1024)
        print(f"视频已下载: {output_path} ({size_mb:.1f}MB)", file=sys.stderr)
        return True
    except requests.RequestException as e:
        print(f"Error: 视频下载失败: {e}", file=sys.stderr)
        return False


def extract_video_url_from_poll(poll_result: dict) -> str:
    """从轮询结果中提取视频 URL"""
    output = poll_result.get("output", {})

    # 视频生成 API 返回 output.video_url
    url = output.get("video_url", "")
    if url:
        return url

    # results.video_url 格式（兼容旧版）
    results = output.get("results", {})
    if isinstance(results, dict):
        url = results.get("video_url", "")
        if url:
            return url

    return ""


def main():
    parser = argparse.ArgumentParser(description="生成带货视频：基于融合图调用 wan2.7-i2v")
    parser.add_argument("--image", required=True, help="融合图路径")
    parser.add_argument("--prompt", required=True, help="视频描述提示词")
    parser.add_argument("--output", required=True, help="视频输出路径")
    parser.add_argument("--resolution", default="720P", choices=["480P", "720P", "1080P"], help="视频分辨率")
    parser.add_argument("--duration", type=int, default=5, help="视频时长（秒），wan2.6 支持 2-15 秒")
    parser.add_argument("--audio", action="store_true", default=True, help="生成有声视频（仅 wan2.6-i2v-flash）")
    parser.add_argument("--no-audio", dest="audio", action="store_false", help="生成无声视频")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        result = {"success": False, "error": "未找到 DASHSCOPE_API_KEY，请在 config.json 或环境变量中配置"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    model = get_video_model()

    # 编码图片为 Base64
    print(f"正在编码图片...", file=sys.stderr)
    image_url = encode_image_base64(args.image)

    # 提交视频生成任务
    print(f"正在提交 {model} 视频生成任务（时长={args.duration}秒，音频={'开启' if args.audio else '关闭'}）...", file=sys.stderr)
    submit_result = submit_video_task(api_key, model, image_url, args.prompt, args.resolution, args.duration, args.audio)

    if not submit_result.get("success"):
        print(json.dumps(submit_result, ensure_ascii=False, indent=2))
        sys.exit(1)

    task_id = submit_result["task_id"]
    print(f"任务已提交: task_id={task_id}", file=sys.stderr)
    print("视频生成通常需要 3-10 分钟，请耐心等待...", file=sys.stderr)

    # 轮询任务
    poll_script = Path(__file__).parent / "poll_task.py"
    import subprocess
    poll_proc = subprocess.run(
        [sys.executable, str(poll_script), task_id, "600", "10"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )

    if poll_proc.returncode != 0:
        result = {"success": False, "error": f"轮询失败: {poll_proc.stderr}"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    poll_result = json.loads(poll_proc.stdout)
    video_url = extract_video_url_from_poll(poll_result)

    if not video_url:
        result = {
            "success": False,
            "error": "未找到生成的视频 URL",
            "poll_result": poll_result,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    # 下载视频
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"正在下载视频: {video_url[:80]}...", file=sys.stderr)
    if download_video(video_url, args.output):
        result = {
            "success": True,
            "video_path": str(output_path.resolve()),
            "video_url": video_url,
            "task_id": task_id,
            "usage": poll_result.get("usage", {}),
        }
    else:
        result = {
            "success": False,
            "error": "视频下载失败",
            "video_url": video_url,
            "task_id": task_id,
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
