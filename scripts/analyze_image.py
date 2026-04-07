#!/usr/bin/env python3
"""
图片分析脚本。
调用阿里云百炼 qwen3-vl-flash 视觉模型，分析产品图、验证融合图、生成多角度提示词。

Usage:
    python analyze_image.py --image <path> --mode product
    python analyze_image.py --image <path> --mode fused --product-type "连衣裙"
    python analyze_image.py --image <path> --mode multi_angle --model-image <path>

Modes:
    product:     分析产品图，输出服装类型、颜色、款式、卖点等
    fused:       验证融合图，检查服装是否完整替换
    multi_angle: 接收产品图+模特图，生成正面/侧面/背面三段融合提示词

Returns:
    JSON: {"success": true, "analysis": {...}} or {"success": true, "prompts": {...}}
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

# DashScope 兼容 OpenAI 的对话端点
CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

PRODUCT_SYSTEM_PROMPT = """你是一个电商服装分析专家。分析用户提供的服装产品图片，提取以下信息并以 JSON 格式返回：

{
  "garment_type": "服装类型，必须是以下之一：上衣、衬衫、T恤、外套、夹克、半身裙、连衣裙、裤子、套装、其他",
  "garment_scope": "替换范围，必须是以下之一：上半身、下半身、全身、外套层",
  "color": "主色调描述，如：黑色、白色、浅蓝色等",
  "pattern": "花色描述，如：纯色、条纹、碎花、格纹等",
  "style": "款式描述，如：方领长袖修身款、V领短袖宽松款等",
  "material": "材质推测，如：针织、丝绸、棉质、牛仔等",
  "details": ["细节特征列表，如：方领设计、腰部系带、泡泡袖等"],
  "selling_points": ["3个口语化卖点，用带货主播的口吻，每个不超过15字"],
  "product_name": "简短产品名称，5-10字",
  "tryon_prompt": "用于虚拟试穿的精准提示词，明确指出要替换的服装范围"
}

只返回 JSON，不要其他内容。"""

FUSED_SYSTEM_PROMPT = """你是一个虚拟试穿质量检验员。检查融合图中服装是否完整、正确地穿在模特身上。

判断标准：
1. 服装类型是否与预期一致（如预期是连衣裙，图中应该是连衣裙）
2. 服装是否完整覆盖了应替换的范围（上半身/下半身/全身）
3. 是否有明显的不自然痕迹（如拼接痕迹、颜色断层）

以 JSON 格式返回：
{
  "pass": true/false,
  "garment_correct": true/false,
  "scope_complete": true/false,
  "issues": ["问题描述列表，如果没有问题则为空数组"],
  "retry_suggestion": "如果 pass 为 false，给出更精准的试穿提示词建议；如果 pass 为 true 则为空字符串"
}

只返回 JSON，不要其他内容。"""

MULTI_ANGLE_SYSTEM_PROMPT = """# Role
你是一个虚拟试穿提示词专家。你的核心任务是：根据模特图和服装产品图，生成四段虚拟试穿提示词（正面/侧面/背面/特写）。

# ⚠️ 绝对红线
- 第1张图 = 模特照片，第2张图 = 服装产品图
- 每段提示词必须以"将图2的衣服穿到图1模特身上，保持模特脸部完全不变，仅替换衣服，保持背景、姿势、光线等所有其他元素不变。"开头
- 服装描述只能来自第2张产品图，禁止使用模特身上的衣服

# 提示词结构（每段必须遵循）
"将图2的衣服穿到图1模特身上，保持模特脸部完全不变，仅替换衣服，保持背景、姿势、光线等所有其他元素不变。[角度姿势描述]。模特穿着[第2张产品图的服装完整细节]。"

# 输出格式
直接输出四段提示词，用标题分隔，不要输出其他内容：

正面
将图2的衣服穿到图1模特身上，保持模特脸部完全不变，仅替换衣服，保持背景、姿势、光线等所有其他元素不变。模特全身正面站立，表情自然放松，[补充合理的正面手部或配饰动作]。模特穿着[第2张产品图的服装完整细节：颜色、款式、面料、图案、领型、袖型、装饰等]。

侧面
将图2的衣服穿到图1模特身上，保持模特脸部完全不变，仅替换衣服，保持背景、姿势、光线等所有其他元素不变。模特全身侧面站立，身体转向一侧，回头看。模特穿着[第2张产品图的服装完整细节]，展示服装的侧面轮廓。

背面
将图2的衣服穿到图1模特身上，保持模特脸部完全不变，仅替换衣服，保持背景、姿势、光线等所有其他元素不变。模特全身背面站立，身体微转向一侧，回头看。模特穿着[第2张产品图的服装完整细节]，[补充该服装背部特征]清晰可见。

特写
将图2的衣服穿到图1模特身上，保持模特脸部完全不变，仅替换衣服，保持背景、姿势、光线等所有其他元素不变。镜头聚焦于[服装核心细节位置]，[面料纹理、图案等特征]清晰可见。模特穿着[第2张产品图的服装完整细节]。"""


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


def get_vl_model() -> str:
    config = load_config()
    return config.get("dashscope", {}).get("vl_model", "qwen3-vl-flash")


def encode_image_base64(image_path: str) -> str:
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


def parse_angle_prompts(text: str) -> dict:
    """从模型输出的多行文本中解析三个角度的提示词"""
    angles = ["正面", "侧面", "背面", "特写"]
    prompts = {}
    lines = text.strip().split("\n")
    current_angle = None
    current_lines = []

    for line in lines:
        matched_angle = None
        for angle in angles:
            if angle in line and ("展示" in line or "全身" in line) and not line.startswith("["):
                matched_angle = angle
                break

        if matched_angle:
            if current_angle:
                prompts[current_angle] = "\n".join(current_lines).strip()
            current_angle = matched_angle
            current_lines = [line]
        elif current_angle:
            current_lines.append(line)

    if current_angle:
        prompts[current_angle] = "\n".join(current_lines).strip()

    return prompts


def analyze_image(api_key: str, image_path: str, mode: str, product_type: str = "",
                  model_image_path: str = "") -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    image_url = encode_image_base64(image_path)

    if mode == "product":
        system_prompt = PRODUCT_SYSTEM_PROMPT
        user_content = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": "请分析这张服装产品图片。"},
        ]
    elif mode == "fused":
        system_prompt = FUSED_SYSTEM_PROMPT
        user_content = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": f"请检查这张融合图。预期的服装类型是：{product_type}。检查服装是否完整正确地穿在模特身上。"},
        ]
    elif mode == "multi_angle":
        if not model_image_path:
            return {"success": False, "error": "multi_angle 模式需要 --model-image 参数"}
        model_url = encode_image_base64(model_image_path)
        system_prompt = MULTI_ANGLE_SYSTEM_PROMPT
        user_content = [
            {"type": "image_url", "image_url": {"url": model_url}},
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": '请根据这两张图片生成四个角度的融合提示词。\n重要提醒：第1张图是模特照片（只提取人物特征），第2张图是服装产品图（这是要描述的目标服装，"她穿着"后面只能描述第2张图中的衣服）。'},
        ]
    else:
        return {"success": False, "error": f"未知模式: {mode}"}

    vl_model = get_vl_model()

    payload = {
        "model": vl_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 1500,
    }

    try:
        resp = requests.post(CHAT_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return {"success": False, "error": "模型返回为空"}

        usage = result.get("usage", {})
        cost_input = usage.get("prompt_tokens", 0) * 0.15 / 1_000_000
        cost_output = usage.get("completion_tokens", 0) * 1.5 / 1_000_000
        print(f"Token 用量: 输入 {usage.get('prompt_tokens', 0)}, 输出 {usage.get('completion_tokens', 0)}", file=sys.stderr)
        print(f"费用: 输入 {cost_input:.6f}元, 输出 {cost_output:.6f}元, 合计 {cost_input + cost_output:.6f}元", file=sys.stderr)

        if mode == "multi_angle":
            # multi_angle 模式返回纯文本提示词
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            prompts = parse_angle_prompts(content)
            return {"success": True, "prompts": prompts, "raw": content}

        # product/fused 模式返回 JSON
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        analysis = json.loads(content)
        return {"success": True, "analysis": analysis}

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON 解析失败: {e}", "raw": content[:500]}
    except requests.RequestException as e:
        return {"success": False, "error": f"请求失败: {str(e)}"}


def main():
    parser = argparse.ArgumentParser(description="图片分析：调用 qwen3-vl-flash 分析产品图、验证融合图、生成多角度提示词")
    parser.add_argument("--image", required=True, help="图片路径（产品图或融合图）")
    parser.add_argument("--mode", required=True, choices=["product", "fused", "multi_angle"],
                        help="分析模式：product=分析产品图, fused=验证融合图, multi_angle=生成多角度提示词")
    parser.add_argument("--product-type", default="", help="融合验证时的预期产品类型（如：连衣裙）")
    parser.add_argument("--model-image", default="", help="多角度模式时的模特图路径")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        result = {"success": False, "error": "未找到 DASHSCOPE_API_KEY"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    mode_desc = {"product": "产品图分析", "fused": "融合验证", "multi_angle": "多角度提示词生成"}
    print(f"正在分析图片（模式: {mode_desc.get(args.mode, args.mode)}）...", file=sys.stderr)
    result = analyze_image(api_key, args.image, args.mode, args.product_type, args.model_image)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
