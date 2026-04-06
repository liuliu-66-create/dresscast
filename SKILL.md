---
name: dresscast
description: "DressCast — 虚拟试穿带货视频生成器。用户提供商品图（服装）和模特图，自动完成虚拟试穿融合 + 带货视频生成，结果写入飞书多维表格。触发方式：'试穿视频'、'虚拟试穿'、'生成试穿视频'、'衣服上身视频'、'带货视频'、'产品试穿宣传片'、'tryon video'、'virtual try-on'、'dresscast'。使用阿里云百炼 wan2.7-image（图像融合）+ wan2.6-i2v-flash（有声视频）+ qwen3-vl-flash（图片分析）模型。"
---

# DressCast — 虚拟试穿带货视频生成器

将产品图（服装）融合到模特图上，生成正面/侧面/背面/特写四张效果图，选取正面图生成有声带货营销视频，上传到飞书多维表格。

## 前置条件

1. **config.json 配置**：确认 `~/.claude/skills/dresscast/config.json` 中 `dashscope.api_key` 已填入阿里云百炼 API Key
2. **lark-cli**：确认已安装且已登录（`lark-cli auth status`），用于飞书上传
3. **Python 依赖**：`requests`（`pip install requests`）

## 模型配置

| 用途 | 模型 | 计费 |
|------|------|------|
| 产品图分析 | qwen3-vl-flash | ~0.0007元/张 |
| 多角度提示词 | qwen3-vl-flash | ~0.001元/次 |
| 虚拟试穿（×4） | wan2.7-image | 0.2元/张 × 4 = 0.8元 |
| 融合验证 | qwen3-vl-flash | ~0.0007元/张 |
| 视频生成 | wan2.6-i2v-flash | 0.3元/秒（有声720P） |
| 视频时长 | 固定 10 秒 | 3.0元 |
| 音频 | 默认开启 | — |
| **总计** | — | **~3.8元/次** |

## 工作流

### Step 1: 确认用户输入

用户需要提供：
- **产品图路径**：一张服装产品图（如上衣、裙子、裤子等）
- **模特图路径**：一张模特全身或半身照片

确认两个路径都指向真实存在的文件。如果用户只提供了一张图，询问另一张。

### Step 2: 产品图分析（qwen3-vl-flash）

**不要使用 Claude 视觉能力分析图片**，改为调用脚本：

```bash
python ~/.claude/skills/dresscast/scripts/analyze_image.py \
  --image "<产品图路径>" \
  --mode product
```

**输出 JSON 示例：**
```json
{
  "success": true,
  "analysis": {
    "garment_type": "连衣裙",
    "garment_scope": "全身",
    "color": "黑色",
    "pattern": "纯色",
    "style": "方领长袖修身款",
    "material": "针织",
    "details": ["方领设计", "腰部系带", "A字裙摆"],
    "selling_points": ["姐妹们看这个方领，锁骨杀绝了", "A字裙摆超遮肉显瘦", "针织面料软糯到不行"],
    "product_name": "黑色方领针织连衣裙",
    "tryon_prompt": "将图2的连衣裙完整穿到图1模特身上..."
  }
}
```

**关键信息：`selling_points`**（用于后续视频提示词）。

### Step 3: 生成多角度提示词（qwen3-vl-flash）

同时发送产品图和模特图，生成正面/侧面/背面/特写四段融合提示词：

```bash
python ~/.claude/skills/dresscast/scripts/analyze_image.py \
  --image "<产品图路径>" \
  --model-image "<模特图路径>" \
  --mode multi_angle
```

**输出 JSON 示例：**
```json
{
  "success": true,
  "prompts": {
    "正面": "全身正面展示\n[时尚摄影] [纯白背景] ...模特全身正面站立...",
    "侧面": "全身侧面展示\n[时尚摄影] [纯白背景] ...模特全身侧面站立...",
    "背面": "全身背面展示\n[时尚摄影] [纯白背景] ...模特全身背面站立..."
  }
}
```

### Step 4: 多角度虚拟试穿（wan2.7-image × 4）

使用 Step 3 的四段提示词，批量生成正面/侧面/背面/特写四张效果图：

```bash
python ~/.claude/skills/dresscast/scripts/virtual_tryon.py \
  --product-image "<产品图路径>" \
  --model-image "<模特图路径>" \
  --prompts-json '<Step 3 返回的 prompts JSON>' \
  --output-dir ~/.claude/skills/dresscast/workspace
```

**输出文件：**
- `workspace/fused_正面.jpg`
- `workspace/fused_侧面.jpg`
- `workspace/fused_背面.jpg`
- `workspace/fused_特写.jpg`

**等待完成**：每张 30-60 秒，共约 2-4 分钟。

### Step 5: 正面图验证（qwen3-vl-flash）

**不要用 Claude 视觉验证**，改用脚本检查正面效果图：

```bash
python ~/.claude/skills/dresscast/scripts/analyze_image.py \
  --image "<正面效果图路径>" \
  --mode fused \
  --product-type "<analysis.garment_type>"
```

**如果 `pass: false`**：使用返回的 `retry_suggestion` 重新运行正面图（最多重试 1 次）。
**如果 `pass: true`**：继续下一步。

### Step 6: 生成有声带货视频

使用**正面效果图**生成视频。基于 Step 2 的 `selling_points` 构建视频提示词。

**图生视频有声公式：运动（配合语音的动作） + 运镜 + 声音描述**

**提示词模板：**
```
模板 A（展示面料）：镜头缓慢推进，模特面带微笑，右手轻抚{garment_part}展示面料质感，说道："{口语化文案}"语气热情亲切，语速轻快。说完后双手在身前自然交叠，微微侧身。

模板 B（展示版型）：固定镜头，模特面带微笑，双手在腰线位置轻轻比划展示修身版型，说道："{口语化文案}"语气轻松自然，语速适中。说完后右手自然垂放，微微右转展示侧面轮廓。

模板 C（展示垂坠感）：镜头缓慢拉远，模特左手轻提{garment_part}左右轻晃展示垂坠感，说道："{口语化文案}"语气温柔亲切，语速适中。说完后双手自然下垂，面带微笑看向镜头。
```

**{garment_part} 填充：** 上衣→衣袖/衣领，连衣裙→裙摆/腰线，裤子→裤脚，外套→衣领

**口语化文案原则：**
- 用"姐妹们""你们看""绝了"等口语
- 10 秒约 40-50 字
- 包含 2 个具体卖点 + 1 个使用场景

运行脚本（固定参数：720P、10秒、有声）：

```bash
python ~/.claude/skills/dresscast/scripts/generate_video.py \
  --image "<正面效果图路径>" \
  --prompt "<视频提示词>" \
  --output ~/.claude/skills/dresscast/workspace/video_<timestamp>.mp4 \
  --resolution 720P \
  --duration 10 \
  --audio
```

**等待完成**：通常 3-10 分钟。

### Step 7: 上传到飞书多维表格

如果是第一次使用，先创建表格：

```bash
python ~/.claude/skills/dresscast/scripts/upload_to_feishu.py setup --name "虚拟试穿视频"
```

然后上传结果（含四张效果图）：

```bash
python ~/.claude/skills/dresscast/scripts/upload_to_feishu.py upload \
  --product-name "<product_name>" \
  --model-image "<模特图路径>" \
  --product-image "<产品图路径>" \
  --front-image "<正面效果图路径>" \
  --side-image "<侧面效果图路径>" \
  --back-image "<背面效果图路径>" \
  --detail-image "<特写效果图路径>" \
  --video "<视频路径>" \
  --prompt "<视频提示词>" \
  --model "wan2.7-image + wan2.6-i2v-flash"
```

### Step 8: 报告结果

向用户展示：
- 四张效果图路径（正面/侧面/背面/特写）
- 视频文件路径
- 飞书多维表格链接

## 脚本参考

| 脚本 | 用途 | 参数 |
|------|------|------|
| `scripts/analyze_image.py` | 产品分析/融合验证/多角度提示词 | `--image`, `--mode` (product/fused/multi_angle), `--model-image`, `--product-type` |
| `scripts/virtual_tryon.py` | 虚拟试穿（单张/批量） | `--product-image`, `--model-image`, `--output/--prompts-json`, `--output-dir` |
| `scripts/generate_video.py` | 生成有声视频 | `--image`, `--prompt`, `--output`, `--resolution`, `--duration`, `--audio` |
| `scripts/poll_task.py` | 任务轮询 | `<task_id>` `[max_wait]` `[interval]` |
| `scripts/upload_to_feishu.py` | 飞书上传 | `setup` 或 `upload` 子命令 |

## 错误处理

| 场景 | 处理方式 |
|------|---------|
| API Key 未配置 | 提示用户在 config.json 中填入 `dashscope.api_key` |
| 产品分析失败 | 检查图片格式（JPEG/PNG）和大小（<20MB） |
| 多角度提示词失败 | 检查两张图片是否都有效 |
| 某角度融合失败 | 跳过该角度，继续生成其他角度 |
| 正面图验证不通过 | 使用 `retry_suggestion` 重试一次，仍失败则告知用户 |
| 视频生成超时 | 脚本默认等待 10 分钟，超时后建议简化提示词重试 |
| lark-cli 未安装 | 提示运行 `npm install -g @larksuite/cli` 并 `lark-cli auth login --recommend` |

## config.json 格式

```json
{
  "dashscope": {
    "api_key": "sk-xxx",
    "image_model": "wan2.7-image",
    "video_model": "wan2.6-i2v-flash"
  },
  "feishu": {
    "app_token": "",
    "table_id": ""
  }
}
```

## 提示词模板

详见 `references/prompts.md`。
