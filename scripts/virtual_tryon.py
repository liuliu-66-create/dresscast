#!/usr/bin/env python3
"""
虚拟试穿脚本。
调用阿里云百炼 wan2.7-image API，将产品图（服装）融合到模特图上。

支持同步和异步两种调用模式：
- 同步: POST /services/aigc/multimodal-generation/generation
- 异步: POST /services/aigc/image-generation/generation (Header: X-DashScope-Async: enable)

支持单张生成和多角度批量生成：
- 单张: --prompt "提示词" --output <path>
- 多角度: --prompts-json '{"正面":"...", "侧面":"...", "背面":"..."}' --output-dir <dir>

Usage:
    python virtual_tryon.py --product-image <path> --model-image <path> --output <path> [--prompt <text>]
    python virtual_tryon.py --product-image <path> --model-image <path> --prompts-json '<json>' --output-dir <dir>

Returns:
    JSON: {"success": true, "output_path": "...", "image_url": "..."}
    JSON: {"success": true, "images": {"正面": {"path": "...", "url": "..."}, ...}}
"""

import argparse
import base64
import io
import json
import os
import sys
import time
import requests
from pathlib import Path

# Windows 终端 UTF-8 输出，避免中文乱码
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"

# DashScope API 端点
SYNC_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
ASYNC_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation"


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


def get_image_model() -> str:
    config = load_config()
    return config.get("dashscope", {}).get("image_model", "wan2.7-image")


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


def download_image(url: str, output_path: str) -> bool:
    """下载图片到本地"""
    try:
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except requests.RequestException as e:
        print(f"Error: 下载图片失败: {e}", file=sys.stderr)
        return False


def call_sync(api_key: str, model: str, model_image_b64: str, product_image_b64: str, prompt: str) -> dict:
    """同步调用 wan2.7-image API"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "input": {
            "messages": [{
                "role": "user",
                "content": [
                    {"image": model_image_b64},
                    {"image": product_image_b64},
                    {"text": prompt},
                ]
            }]
        },
        "parameters": {
            "size": "2K",
            "n": 1,
            "watermark": False,
        }
    }

    try:
        resp = requests.post(SYNC_URL, headers=headers, json=payload, timeout=180)
        resp.raise_for_status()
        result = resp.json()

        # 检查是否有错误
        if "code" in result:
            return {"error": f"API 错误: {result.get('code')} - {result.get('message')}"}

        # 提取图片 URL
        choices = result.get("output", {}).get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", [])
            for item in content:
                if item.get("type") == "image" and item.get("image"):
                    return {
                        "success": True,
                        "image_url": item["image"],
                        "sync": True,
                    }

        return {"error": "同步调用未返回图片", "response": result}

    except requests.Timeout:
        return {"timeout": True, "error": "同步调用超时，将尝试异步模式"}
    except requests.RequestException as e:
        return {"error": f"请求失败: {str(e)}"}


def call_async(api_key: str, model: str, model_image_b64: str, product_image_b64: str, prompt: str) -> dict:
    """异步调用 wan2.7-image API"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-DashScope-Async": "enable",
    }
    payload = {
        "model": model,
        "input": {
            "messages": [{
                "role": "user",
                "content": [
                    {"image": model_image_b64},
                    {"image": product_image_b64},
                    {"text": prompt},
                ]
            }]
        },
        "parameters": {
            "size": "2K",
            "n": 1,
            "watermark": False,
        }
    }

    try:
        resp = requests.post(ASYNC_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()

        if "code" in result and "output" not in result:
            return {"error": f"API 错误: {result.get('code')} - {result.get('message')}"}

        task_id = result.get("output", {}).get("task_id", "")
        if not task_id:
            return {"error": "异步调用未返回 task_id", "response": result}

        print(f"异步任务已提交: task_id={task_id}", file=sys.stderr)
        return {"success": True, "task_id": task_id, "sync": False}

    except requests.RequestException as e:
        return {"error": f"异步请求失败: {str(e)}"}


def extract_image_url_from_poll(poll_result: dict) -> str:
    """从轮询结果中提取图片 URL"""
    output = poll_result.get("output", {})

    # 异步调用结果格式
    choices = output.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", [])
        for item in content:
            if item.get("type") == "image" and item.get("image"):
                return item["image"]

    # 同步调用结果格式（results 字段）
    results = output.get("results", [])
    if results:
        url = results[0].get("url", "")
        if url:
            return url

    return ""


def generate_single(api_key: str, model: str, model_b64: str, product_b64: str,
                    prompt: str, output_path: str) -> dict:
    """生成单张融合图，返回 {"success": true, "output_path": "...", "image_url": "..."}"""
    # 尝试同步调用
    print(f"正在调用 {model} 进行虚拟试穿（同步模式）...", file=sys.stderr)
    result = call_sync(api_key, model, model_b64, product_b64, prompt)

    # 如果同步超时或失败，尝试异步
    if result.get("timeout") or (not result.get("success") and not result.get("image_url")):
        if result.get("timeout"):
            print("同步调用超时，切换到异步模式...", file=sys.stderr)
        else:
            print(f"同步调用失败: {result.get('error')}，尝试异步模式...", file=sys.stderr)

        async_result = call_async(api_key, model, model_b64, product_b64, prompt)
        if not async_result.get("success"):
            result = async_result
        else:
            task_id = async_result["task_id"]
            print(f"正在轮询任务 {task_id}...", file=sys.stderr)

            poll_script = Path(__file__).parent / "poll_task.py"
            import subprocess
            poll_proc = subprocess.run(
                [sys.executable, str(poll_script), task_id, "600", "10"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if poll_proc.returncode != 0:
                result = {"success": False, "error": f"轮询失败: {poll_proc.stderr}"}
            else:
                poll_result = json.loads(poll_proc.stdout)
                image_url = extract_image_url_from_poll(poll_result)
                if image_url:
                    result = {"success": True, "image_url": image_url, "sync": False}
                else:
                    result = {"success": False, "error": "未找到生成的图片 URL", "poll_result": poll_result}

    # 下载图片
    if result.get("success") and result.get("image_url"):
        image_url = result["image_url"]
        print(f"正在下载融合图: {image_url[:80]}...", file=sys.stderr)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if download_image(image_url, output_path):
            result["output_path"] = str(out.resolve())
            print(f"融合图已保存: {output_path}", file=sys.stderr)
        else:
            result["download_error"] = True
            result["error"] = "图片下载失败"

    return result


def main():
    parser = argparse.ArgumentParser(description="虚拟试穿：将产品图融合到模特图上")
    parser.add_argument("--product-image", required=True, help="产品图（服装）路径")
    parser.add_argument("--model-image", required=True, help="模特图路径")
    # 单张模式
    parser.add_argument("--output", default="", help="单张模式：融合图输出路径")
    parser.add_argument("--prompt", default="", help="单张模式：自定义提示词（可选）")
    # 多角度批量模式
    parser.add_argument("--prompts-json", default="", help="批量模式：JSON 格式的多角度提示词，如 '{\"正面\":\"...\", \"侧面\":\"...\", \"背面\":\"...\"}'")
    parser.add_argument("--output-dir", default="", help="批量模式：输出目录")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        result = {"success": False, "error": "未找到 DASHSCOPE_API_KEY，请在 config.json 或环境变量中配置"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    model = get_image_model()

    # 编码图片
    print("正在编码图片...", file=sys.stderr)
    model_b64 = encode_image_base64(args.model_image)
    product_b64 = encode_image_base64(args.product_image)

    # 多角度批量模式
    if args.prompts_json:
        prompts = json.loads(args.prompts_json)
        output_dir = Path(args.output_dir) if args.output_dir else SKILL_DIR / "workspace"
        output_dir.mkdir(parents=True, exist_ok=True)

        results = {}
        all_success = True
        for angle, prompt_text in prompts.items():
            print(f"\n--- 生成 {angle} 视图 ---", file=sys.stderr)
            output_path = output_dir / f"fused_{angle}.jpg"
            result = generate_single(api_key, model, model_b64, product_b64, prompt_text, str(output_path))
            if result.get("success"):
                results[angle] = {"path": result["output_path"], "url": result.get("image_url", "")}
            else:
                results[angle] = {"error": result.get("error", "生成失败")}
                all_success = False

        final = {"success": all_success, "images": results}
        print(json.dumps(final, ensure_ascii=False, indent=2))
        if not all_success:
            sys.exit(1)
        return

    # 单张模式
    if not args.output:
        print("Error: 单张模式需要 --output 参数", file=sys.stderr)
        sys.exit(1)

    prompt = args.prompt or "将图2的衣服穿到图1模特身上，保持模特脸部完全不变，仅替换衣服，保持背景、姿势、光线等所有其他元素不变。"
    result = generate_single(api_key, model, model_b64, product_b64, prompt, args.output)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
