#!/usr/bin/env python3
"""
飞书多维表格上传脚本。
将虚拟试穿融合图和带货视频上传到飞书多维表格。

两步上传模式：
1. 创建文本字段记录 → 获取 record_id
2. 逐个上传附件 → 间隔 1.5 秒（API 限流）

Usage:
    python upload_to_feishu.py setup [--name "虚拟试穿视频"]
    python upload_to_feishu.py upload --product-name <name> --fused-image <path> --video <path> --prompt <text>

依赖: lark-cli (npm install -g @larksuite/cli), lark-bitable-creator skill
"""

import argparse
import io
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

# Windows 终端 UTF-8 输出，避免中文乱码
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
LARK_BITABLE_CREATOR_DIR = SKILL_DIR.parent / "lark-bitable-creator"

API_INTERVAL = 1.5

BITABLE_FIELDS = [
    {"field_name": "产品名称", "type": "text"},
    {"field_name": "模特图", "type": "attachment"},
    {"field_name": "产品图", "type": "attachment"},
    {"field_name": "正面效果图", "type": "attachment"},
    {"field_name": "侧面效果图", "type": "attachment"},
    {"field_name": "背面效果图", "type": "attachment"},
    {"field_name": "特写效果图", "type": "attachment"},
    {"field_name": "营销视频", "type": "attachment"},
    {"field_name": "视频提示词", "type": "text"},
    {"field_name": "使用模型", "type": "text"},
    {"field_name": "创建时间", "type": "datetime"},
]


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def find_lark_cli() -> str:
    found = shutil.which("lark-cli")
    if found:
        return found
    npm_global = Path.home() / "AppData" / "Roaming" / "npm"
    for ext in [".cmd", ".ps1", ""]:
        candidate = npm_global / f"lark-cli{ext}"
        if candidate.exists():
            return str(candidate)
    return "lark-cli"


def run_lark(args: list, timeout: int = 120, cwd: str = None) -> dict:
    lark = find_lark_cli()
    cmd = [lark] + args
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd,
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0 and not stdout.strip():
        return {"ok": False, "error": stderr or stdout or "命令执行失败"}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"无法解析返回: {stdout[:300]}"}


def get_bitable_config() -> tuple:
    config = load_config()
    feishu_cfg = config.get("feishu", {})
    app_token = feishu_cfg.get("app_token", "")
    table_id = feishu_cfg.get("table_id", "")
    if not app_token or not table_id:
        return "", ""
    return app_token, table_id


def setup(app_name: str = "虚拟试穿视频") -> dict:
    """调用 lark-bitable-creator 创建多维表格"""
    creator_script = LARK_BITABLE_CREATOR_DIR / "scripts" / "create_bitable.py"
    if not creator_script.exists():
        print(f"Error: create_bitable.py not found at {creator_script}", file=sys.stderr)
        print("Tip: 请确保 lark-bitable-creator skill 已安装", file=sys.stderr)
        return {"success": False, "error": "lark-bitable-creator skill 未安装"}

    config_json = {
        "app_name": app_name,
        "tables": [{
            "table_name": "试穿记录",
            "fields": BITABLE_FIELDS,
        }],
    }

    workspace = SKILL_DIR / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    config_file = workspace / "_bitable_config.json"
    config_file.write_text(json.dumps(config_json, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"正在创建多维表格: {app_name}", file=sys.stderr)
    result = subprocess.run(
        [sys.executable, str(creator_script), str(config_file)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    stdout = result.stdout or ""

    output = None
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "__JSON_OUTPUT__":
            if i + 1 < len(lines):
                try:
                    output = json.loads(lines[i + 1])
                except json.JSONDecodeError:
                    pass
            break

    if not output or not output.get("ok"):
        stderr = result.stderr or ""
        error_msg = output.get("error", "") if output else stderr or stdout or "未知错误"
        return {"success": False, "error": error_msg}

    app_token = output.get("app_token", "")
    tables = output.get("tables", [])
    table_id = tables[0]["table_id"] if tables else ""
    app_url = output.get("app_url", f"https://my.feishu.cn/base/{app_token}")

    config = load_config()
    if "feishu" not in config:
        config["feishu"] = {}
    config["feishu"]["app_token"] = app_token
    config["feishu"]["table_id"] = table_id
    save_config(config)

    config_file.unlink(missing_ok=True)
    print(f"多维表格已创建: app_token={app_token}, table_id={table_id}", file=sys.stderr)

    return {"success": True, "app_token": app_token, "table_id": table_id, "url": app_url}


def create_text_record(fields: dict) -> dict:
    """创建只含文本字段的记录"""
    app_token, table_id = get_bitable_config()
    if not app_token or not table_id:
        return {"success": False, "error": "飞书多维表格未配置，请先运行 setup"}

    attachment_fields = {"模特图", "产品图", "正面效果图", "侧面效果图", "背面效果图", "特写效果图", "营销视频"}
    text_fields = {k: v for k, v in fields.items() if k not in attachment_fields}

    workspace = SKILL_DIR / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    tmp_json = workspace / "_feishu_upload.json"
    tmp_json.write_text(json.dumps(text_fields, ensure_ascii=False), encoding="utf-8")

    resp = run_lark([
        "base", "+record-upsert",
        "--base-token", app_token,
        "--table-id", table_id,
        "--json", "@_feishu_upload.json",
    ], cwd=str(workspace))

    if resp.get("ok"):
        record_id = ""
        try:
            record_id = resp["data"]["record"]["record_id_list"][0]
        except (KeyError, IndexError):
            pass
        return {"success": True, "record_id": record_id}
    else:
        return {"success": False, "error": resp.get("error", "创建记录失败")}


def upload_attachment(record_id: str, field_name: str, file_path: str) -> dict:
    """上传附件到指定记录的指定字段"""
    app_token, table_id = get_bitable_config()

    # lark-cli 要求相对路径，将文件复制到 workspace 并使用相对路径
    workspace = SKILL_DIR / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    src = Path(file_path).resolve()
    dst = workspace / src.name
    if src != dst:
        shutil.copy2(str(src), str(dst))

    resp = run_lark([
        "base", "+record-upload-attachment",
        "--base-token", app_token,
        "--table-id", table_id,
        "--record-id", record_id,
        "--field-id", field_name,
        "--file", dst.name,
    ], timeout=120, cwd=str(workspace))

    if resp.get("ok"):
        file_token = ""
        try:
            file_token = resp["data"]["attachment"]["file_token"]
        except (KeyError, IndexError):
            pass
        print(f"附件已上传: {Path(file_path).name} -> {field_name}", file=sys.stderr)
        return {"success": True, "file_token": file_token}
    else:
        return {"success": False, "error": resp.get("error", f"上传附件失败: {field_name}")}


def upload(product_name: str, model_image: str, product_image: str,
           front_image: str, side_image: str, back_image: str, detail_image: str,
           video_path: str, prompt: str, model: str) -> dict:
    """完整上传流程"""
    # 1. 创建文本记录
    print("正在创建记录...", file=sys.stderr)
    rec_result = create_text_record({
        "产品名称": product_name,
        "视频提示词": prompt,
        "使用模型": model,
        "创建时间": int(datetime.now().timestamp() * 1000),
    })

    if not rec_result["success"]:
        return rec_result

    record_id = rec_result["record_id"]
    print(f"记录已创建: {record_id}", file=sys.stderr)
    time.sleep(API_INTERVAL)

    # 2. 上传原图、四角度效果图、视频
    uploaded = {}
    uploads = [
        ("模特图", model_image),
        ("产品图", product_image),
        ("正面效果图", front_image),
        ("侧面效果图", side_image),
        ("背面效果图", back_image),
        ("特写效果图", detail_image),
        ("营销视频", video_path),
    ]
    for field_name, file_path in uploads:
        if file_path and Path(file_path).exists():
            print(f"正在上传{field_name}...", file=sys.stderr)
            result = upload_attachment(record_id, field_name, file_path)
            if result["success"]:
                uploaded[field_name] = result["file_token"]
            else:
                print(f"Warning: {field_name}上传失败: {result.get('error')}", file=sys.stderr)
            time.sleep(API_INTERVAL)

    config = load_config()
    app_url = f"https://my.feishu.cn/base/{config.get('feishu', {}).get('app_token', '')}"

    return {
        "success": True,
        "record_id": record_id,
        "uploaded_fields": list(uploaded.keys()),
        "url": app_url,
    }


def main():
    parser = argparse.ArgumentParser(description="飞书多维表格上传")
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser("setup", help="创建多维表格")
    setup_parser.add_argument("--name", default="虚拟试穿视频")

    upload_parser = subparsers.add_parser("upload", help="上传原图、三角度效果图和视频")
    upload_parser.add_argument("--product-name", required=True)
    upload_parser.add_argument("--model-image", default="", help="模特原图路径")
    upload_parser.add_argument("--product-image", default="", help="产品原图路径")
    upload_parser.add_argument("--front-image", default="", help="正面效果图路径")
    upload_parser.add_argument("--side-image", default="", help="侧面效果图路径")
    upload_parser.add_argument("--back-image", default="", help="背面效果图路径")
    upload_parser.add_argument("--detail-image", default="", help="特写效果图路径")
    upload_parser.add_argument("--video", required=True)
    upload_parser.add_argument("--prompt", default="")
    upload_parser.add_argument("--model", default="wan2.7-image + wan2.6-i2v-flash")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "setup":
        result = setup(args.name)
    elif args.command == "upload":
        result = upload(args.product_name, args.model_image, args.product_image,
                        args.front_image, args.side_image, args.back_image, args.detail_image,
                        args.video, args.prompt, args.model)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
