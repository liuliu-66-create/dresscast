#!/usr/bin/env python3
"""
DashScope 异步任务轮询器。
轮询 DashScope 任务状态直到完成。

Usage:
    python poll_task.py <task_id> [max_wait_seconds] [poll_interval]

Environment:
    DASHSCOPE_API_KEY - 阿里云百炼 API Key（或通过 config.json 配置）

Returns:
    JSON 输出到 stdout，进度输出到 stderr
"""

import sys
import io
import json
import os
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
POLL_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"


def load_api_key() -> str:
    """从 config.json 或环境变量获取 API Key"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        key = config.get("dashscope", {}).get("api_key", "")
        if key:
            return key
    return os.environ.get("DASHSCOPE_API_KEY", "")


def get_task_status(task_id: str, api_key: str) -> dict:
    """查询任务状态"""
    url = POLL_URL.format(task_id=task_id)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": f"请求失败: {str(e)}"}


def poll(task_id: str, max_wait: int = 600, interval: int = 10) -> dict:
    """
    轮询任务状态直到完成。

    Args:
        task_id: DashScope 任务 ID
        max_wait: 最大等待秒数（默认 600）
        interval: 轮询间隔秒数（默认 10）

    Returns:
        结果 JSON
    """
    api_key = load_api_key()
    if not api_key:
        return {"error": "未找到 DASHSCOPE_API_KEY，请在 config.json 或环境变量中配置"}

    start = time.time()

    while time.time() - start < max_wait:
        result = get_task_status(task_id, api_key)

        if "error" in result:
            return result

        output = result.get("output", {})
        status = output.get("task_status", "UNKNOWN")

        if status == "SUCCEEDED":
            return {
                "success": True,
                "task_id": task_id,
                "task_status": status,
                "output": output,
                "usage": result.get("usage", {}),
                "request_id": result.get("request_id", ""),
            }

        if status in ("FAILED", "UNKNOWN", "CANCELED"):
            return {
                "success": False,
                "task_id": task_id,
                "task_status": status,
                "code": output.get("code", ""),
                "message": output.get("message", ""),
            }

        # 仍在处理中
        elapsed = int(time.time() - start)
        print(json.dumps({
            "status": "polling",
            "task_status": status,
            "elapsed_seconds": elapsed,
            "remaining_seconds": max_wait - elapsed,
        }, ensure_ascii=False), file=sys.stderr, flush=True)

        time.sleep(interval)

    return {"error": f"轮询超时（{max_wait}秒）", "task_id": task_id}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "用法: poll_task.py <task_id> [max_wait] [interval]"}))
        sys.exit(1)

    task_id = sys.argv[1]
    max_wait = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    interval = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    result = poll(task_id, max_wait, interval)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
