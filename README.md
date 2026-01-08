# PhysVLM-Intent

一个用于意图推理与目标定位的视频数据标注工具集，支持视频标注、语音识别（ASR）和跨平台路径自动解析。

## 🚀 快速开始

### 1. 环境要求

- Python 3.8+
- ffmpeg（用于视频处理）
- 支持的浏览器（Chrome、Firefox、Safari、Edge）

### 2. 安装依赖

```bash
# 安装项目依赖
pip install -r requirements.txt

# 安装标注工具额外依赖（如果需要）
pip install -r tools/annotation/requirements_annotation.txt
```

### 3. 配置 API 密钥

设置环境变量或修改 `config/settings.py`：

```bash
# DashScope API（用于 ASR 语音识别）
export DASHSCOPE_API_KEY="your-dashscope-api-key"

# OpenAI API（如果需要使用 OpenAI 模型）
export OPENAI_API_KEY="your-openai-api-key"
export OPENAI_BASE_URL="http://localhost:8000/v1"  # 可选，用于本地部署的模型
```

### 4. 启动标注工具

```bash
python start_simple_annotation.py
```

启动后访问：**http://localhost:5001**

## 📖 使用指南

### 简易标注工具使用流程

1. **选择文件夹**
   - 在浏览器中打开 http://localhost:5001
   - 输入包含视频文件的文件夹路径（支持绝对路径和相对路径）
   - 点击"扫描视频"按钮

2. **加载视频**
   - 系统会自动扫描文件夹下的所有视频文件（支持 .mp4, .mov, .avi, .mkv 等格式）
   - 选择要标注的视频

3. **进行标注**
   - 查看视频最后一帧预览图
   - 点击"ASR识别"按钮进行语音识别（可选）
   - 在预览图上点击标注对象或放置空间
   - 输入对象名称和类型（object/space）
   - 可以标注多个对象

4. **保存标注**
   - 点击"保存标注"按钮
   - 标注数据会保存到文件夹下的 `annotations.json` 文件

### 标注数据格式

标注数据保存在 `annotations.json` 文件中，格式如下：

```json
[
  {
    "id": "时间戳",
    "folder": "文件夹路径",
    "video_name": "视频文件名",
    "task_template": "任务模板",
    "scene": "场景名称",
    "object_space": [
      {
        "name": "对象名称",
        "type": "object",  // 或 "space"
        "points": [
          [x1, y1],
          [x2, y2],
          ...
        ]
      }
    ],
    "is_invalid": false,
    "asr_result": {
      "text": "识别的文本",
      "sentences": [...],
      "words": [...]
    }
  }
]
```
