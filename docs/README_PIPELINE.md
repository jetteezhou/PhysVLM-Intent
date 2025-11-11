# PhysVLM-Intent Pipeline 项目结构说明

## 📁 项目结构

```
PhysVLM-Intent/
├── pipeline/                    # Pipeline核心模块
│   ├── __init__.py
│   ├── pipeline.py             # 主Pipeline类
│   ├── audio_processor.py      # 音频处理模块（ASR）
│   ├── video_processor.py      # 视频处理模块（分割、帧采样）
│   └── llm_client.py          # LLM客户端模块（意图分析、目标定位）
├── config/                      # 配置模块
│   ├── __init__.py
│   └── settings.py             # 配置和常量
├── utils/                       # 工具函数模块
│   ├── __init__.py
│   └── image_utils.py          # 图像处理工具
├── data_label_gen_pipeline.py  # 主入口文件（向后兼容）
├── annotation_server.py        # 标注工具服务器
├── start_annotation_tool.py    # 标注工具启动脚本
└── requirements.txt            # 项目依赖

```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

可以通过环境变量或直接修改 `config/settings.py`：

```bash
export DASHSCOPE_API_KEY="your-dashscope-api-key"
export OPENAI_API_KEY="your-openai-api-key"
export OPENAI_BASE_URL="http://localhost:8000/v1"
```

### 3. 使用Pipeline

#### 方式一：使用新的Pipeline类（推荐）

```python
from pipeline import IntentLabelPipeline
from config import Config

# 创建配置（可选，默认从环境变量读取）
config = Config.from_env()

# 创建Pipeline
pipeline = IntentLabelPipeline(config)

# 执行处理
result = pipeline.process(
    audio_path='test_data/IMG_3492.mp3',
    video_path='test_data/IMG_3492_up.mp4'
)
```

#### 方式二：使用原有接口（向后兼容）

```python
from data_label_gen_pipeline import main

# 直接运行main函数
main()
```

或直接运行：

```bash
python data_label_gen_pipeline.py
```

## 📦 模块说明

### pipeline/pipeline.py
主Pipeline类，整合所有处理步骤：
- 语音识别
- 视频分割和帧采样
- 意图分析
- 目标定位

### pipeline/audio_processor.py
音频处理相关功能：
- `convert_to_mono()`: 音频格式转换
- `audio_to_words_with_timestamps()`: 语音识别（带时间戳）
- `print_words_with_timestamps()`: 打印识别结果

### pipeline/video_processor.py
视频处理相关功能：
- `split_video_by_words()`: 根据词汇时间戳分割视频并采样帧

### pipeline/llm_client.py
LLM交互相关功能：
- `LLMClient`: LLM客户端封装类
  - `analyze_video_intent()`: 分析视频意图
  - `extract_object_descriptions()`: 提取物品描述
  - `locate_object_in_image()`: 在图像中定位物品

### config/settings.py
配置和常量：
- API密钥配置
- 模型配置
- 音频/视频处理参数

### utils/image_utils.py
图像处理工具：
- `image_to_base64()`: 图像转base64编码

## 🔧 配置说明

主要配置项在 `config/settings.py` 中：

```python
# API配置
DASHSCOPE_API_KEY = "your-api-key"
OPENAI_API_KEY = "your-api-key"
OPENAI_BASE_URL = "http://localhost:8000/v1"

# 模型配置
ASR_MODEL = "fun-asr-realtime"
LLM_MODEL = "gemini-2.5-flash"

# 视频处理配置
DEFAULT_SAMPLING_INTERVAL = 300  # 毫秒
DEFAULT_OUTPUT_DIR = "output_frames"
```

## 📝 使用示例

### 自定义配置

```python
from pipeline import IntentLabelPipeline
from config import Config

# 自定义配置
config = Config(
    sampling_interval=200,  # 200ms采样间隔
    output_dir="custom_output",  # 自定义输出目录
    llm_model="custom-model"  # 自定义模型
)

pipeline = IntentLabelPipeline(config)
result = pipeline.process(audio_path, video_path)
```

### 单独使用各个模块

```python
from pipeline.audio_processor import audio_to_words_with_timestamps
from pipeline.video_processor import split_video_by_words
from pipeline.llm_client import LLMClient

# 语音识别
success, words_list = audio_to_words_with_timestamps("audio.mp3")

# 视频处理（返回result_data和最后一帧路径）
result_data, last_frame_path = split_video_by_words("video.mp4", words_list)

# LLM分析
llm_client = LLMClient(api_key="...", base_url="...")
description = llm_client.analyze_video_intent(result_data)
```

## 🔄 迁移指南

如果你之前使用的是 `data_label_gen_pipeline.py` 中的函数，现在可以：

1. **继续使用原有接口**：`data_label_gen_pipeline.py` 已更新为向后兼容的入口文件
2. **迁移到新接口**：使用 `IntentLabelPipeline` 类，代码更简洁

## 📄 输出格式

Pipeline会生成 `pipeline_data.json` 文件，包含：

```json
{
  "video_path": "视频路径",
  "last_image_path": "最后一张图像路径",
  "video_description": "视频描述",
  "result_data": [...],
  "objects": [
    {
      "id": 0,
      "description": "物品描述",
      "point": [500, 300],
      "label": "物品标签",
      "pixel_coords": [576, 540],
      "normalized_coords": [0.3, 0.5]
    }
  ],
  "image_dimensions": {
    "width": 1920,
    "height": 1080
  }
}
```

