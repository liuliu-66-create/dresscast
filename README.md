# DressCast

> 虚拟试穿 + 带货视频，一键生成。

上传一张服装产品图 + 一张模特图，DressCast 自动完成：

1. **多角度试穿** — 正面 / 侧面 / 背面 / 特写，4 张效果图
2. **有声带货视频** — 基于正面效果图，生成 10 秒带语音的营销视频
3. **飞书归档** — 全部结果自动上传到飞书多维表格

基于阿里云百炼平台，使用 `wan2.7-image`（试穿）+ `wan2.6-i2v-flash`（视频）+ `qwen3-vl-flash`（图片分析）模型。

---

## 效果展示

**输入：**
- 产品图（服装平铺 / 白底图）
- 模特图（全身或半身照）

**输出：**

| 正面 | 侧面 | 背面 | 视频 |
|------|------|------|------|
| 静态效果图 | 静态效果图 | 静态效果图 | 10秒有声MP4 |

---

## 快速开始

> 在使用 Claude Code 搭建时，我以 GLM-5.1 模型为例。请注意，Claude Code 支持多种模型，您可以根据需要选择其他模型进行替换。

### 1. 安装

在 Claude Code 中发送：

```
帮我安装这个技能：https://github.com/liuliu-66-create/tryon-video-generator
```

或在终端运行：

```bash
git clone https://github.com/liuliu-66-create/tryon-video-generator.git ~/.claude/skills/tryon-video-generator
```

### 2. 获取 API Key

访问 [阿里云百炼 API Key 管理页面](https://bailian.console.aliyun.com/cn-beijing?spm=5176.29597918.nav-v2-dropdown-menu-0.d_main_1_0_10.24c2133c4y8d1V&tab=model&scm=20140722.M_10944435._.V_1#/api-key)，注册并创建 API Key。

### 3. 配置

告诉 Claude Code：

```
请帮我配置试穿视频技能：1）写入 API Key（sk-你的Key） 2）安装 Python 依赖 3）如果需要飞书上传，一并帮我配置好
```

AI 会自动完成所有配置。

### 4. 使用

对 AI 说：

```
帮我生成试穿视频
```

然后提供产品图和模特图的路径，等待 5-15 分钟即可。

详细说明见 [安装使用指南](安装使用指南.md)。

---

## 工作流程

```
产品图 + 模特图
    │
    ├─ 1. 产品分析（qwen3-vl-flash）
    │     └─ 服装类型、颜色、卖点、试穿提示词
    │
    ├─ 2. 多角度提示词生成（qwen3-vl-flash）
    │     └─ 正面 / 侧面 / 背面 / 特写
    │
    ├─ 3. 虚拟试穿（wan2.7-image × 4）
    │     └─ 4 张融合效果图
    │
    ├─ 4. 正面图验证（qwen3-vl-flash）
    │     └─ 不合格自动重试
    │
    ├─ 5. 有声视频生成（wan2.6-i2v-flash）
    │     └─ 10 秒 720P 带语音 MP4
    │
    └─ 6. 上传飞书多维表格
          └─ 原图 + 效果图 + 视频
```

---

## 项目结构

```
tryon-video-generator/
├── SKILL.md                  # 技能定义（Claude Code 读取）
├── config.example.json       # 配置模板
├── 安装使用指南.md             # 小白用户指南
├── references/
│   └── prompts.md            # 提示词模板参考
├── scripts/
│   ├── analyze_image.py      # 图片分析 / 多角度提示词 / 融合验证
│   ├── virtual_tryon.py      # 虚拟试穿（同步 + 异步）
│   ├── generate_video.py     # 有声视频生成
│   ├── poll_task.py          # 异步任务轮询器
│   └── upload_to_feishu.py   # 飞书多维表格上传
└── workspace/                # 运行时输出目录（gitignore）
```

---

## 前置依赖

| 依赖 | 用途 | 是否必需 |
|------|------|---------|
| 阿里云百炼 API Key | 调用 AI 模型 | 必需 |
| Python 3 + requests | 运行脚本 | 必需 |
| lark-cli + Node.js | 飞书上传 | 可选 |

---

## 技术参数

| 项目 | 模型 | 说明 |
|------|------|------|
| 图片分析 | qwen3-vl-flash | 产品分析、提示词生成、融合验证 |
| 虚拟试穿 | wan2.7-image | 2K 分辨率，同步/异步双模式 |
| 视频生成 | wan2.6-i2v-flash | 720P、10 秒、有声 |
| 视频帧 | 固定正面效果图 | 作为视频首帧 |

---

## 许可

MIT
