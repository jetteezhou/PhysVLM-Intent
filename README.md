# PhysVLM-Intent 项目

意图推理与目标定位数据标注Pipeline项目

## 📁 项目结构

```
PhysVLM-Intent/
├── pipeline/                    # Pipeline核心模块
│   ├── __init__.py
│   ├── pipeline.py             # 主Pipeline类
│   ├── audio_processor.py      # 音频处理模块（ASR）
│   ├── video_processor.py      # 视频处理模块（分割、帧采样）
│   └── llm_client.py           # LLM客户端模块（意图分析、目标定位）
├── config/                      # 配置模块
│   ├── __init__.py
│   └── settings.py             # 配置和常量
├── utils/                       # 工具函数模块
│   ├── __init__.py
│   └── image_utils.py          # 图像处理工具
├── tools/                       # 工具和脚本
│   ├── annotation/             # 标注工具
│   │   ├── annotation_server.py
│   │   ├── annotation_tool.html
│   │   ├── start_annotation_tool.py
│   │   └── requirements_annotation.txt
│   └── sam/                    # SAM分割工具
│       └── sam_test.py
├── docs/                        # 文档
│   ├── README_PIPELINE.md      # Pipeline使用说明
│   ├── README_annotation.md    # 标注工具使用说明
│   └── QUICK_START.md          # 快速开始指南
├── models/                      # 模型文件
│   └── sam2.1_b.pt            # SAM模型
├── data_label_gen_pipeline.py  # 主入口文件（向后兼容）
├── start_annotation.py         # 启动标注工具（便捷脚本）
└── requirements.txt            # 项目依赖
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

设置环境变量或修改 `config/settings.py`：

```bash
export DASHSCOPE_API_KEY="your-dashscope-api-key"
export OPENAI_API_KEY="your-openai-api-key"
export OPENAI_BASE_URL="http://localhost:8000/v1"
```

### 3. 运行Pipeline

```bash
python data_label_gen_pipeline.py
```

### 4. 启动标注工具

```bash
python start_annotation.py
```

或直接运行：

```bash
python tools/annotation/start_annotation_tool.py
```

## 📚 文档

- [Pipeline使用说明](docs/README_PIPELINE.md) - Pipeline详细文档
- [标注工具使用说明](docs/README_annotation.md) - 标注工具详细文档
- [快速开始指南](docs/QUICK_START.md) - 快速入门指南

## 🔧 主要功能

1. **意图推理Pipeline** (`pipeline/`)
   - 语音识别（ASR）
   - 视频分割和帧采样
   - 意图分析
   - 目标定位

2. **标注工具** (`tools/annotation/`)
   - Web界面标注
   - 可视化修正
   - 数据备份和管理

3. **SAM分割工具** (`tools/sam/`)
   - 视频对象分割
   - 多目标跟踪

## 📝 使用示例

### Pipeline使用

```python
from pipeline import IntentLabelPipeline
from config import Config

config = Config.from_env()
pipeline = IntentLabelPipeline(config)
result = pipeline.process(audio_path, video_path)
```

### 标注工具

访问 `http://localhost:5000` 使用Web界面进行标注。

## 📄 输出

Pipeline会生成 `pipeline_data.json` 文件，包含：
- 视频信息和描述
- 物品描述和定位点
- 图像尺寸信息

## 🔗 相关链接

- Pipeline文档: [docs/README_PIPELINE.md](docs/README_PIPELINE.md)
- 标注工具文档: [docs/README_annotation.md](docs/README_annotation.md)

