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
│   ├── data_collection/        # 数据采集工具
│   │   ├── collection_server.py
│   │   ├── collection_tool.html
│   │   └── start_collection_tool.py
│   └── sam/                    # SAM分割工具
│       └── sam_test.py
├── docs/                        # 文档
│   ├── README_PIPELINE.md      # Pipeline使用说明
│   ├── README_annotation.md    # 标注工具使用说明
│   └── QUICK_START.md          # 快速开始指南
├── models/                      # 模型文件
│   └── sam2.1_b.pt            # SAM模型
├── unified_server.py            # 统一Web应用服务器（推荐）
├── start_unified_app.py         # 启动统一Web应用（便捷脚本）
├── start_pipeline.py            # 启动标注生成Pipeline（单元测试用）
├── start_annotation.py          # 启动标注检验工具（单元测试用）
├── start_collection.py          # 启动数据采集工具（单元测试用）
├── data_label_gen_pipeline.py   # Pipeline主入口文件（向后兼容）
├── web_html/                    # Web前端页面
│   ├── unified_app.html         # 统一Web应用前端页面
│   ├── collection_tool.html     # 数据采集工具页面
│   ├── pipeline_page.html       # 标注生成页面
│   ├── annotation_page.html     # 标注检验页面
│   ├── annotation_tool.html      # 标注工具页面
│   └── history_page.html        # 历史记录页面
└── requirements.txt             # 项目依赖
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

### 3. 使用统一Web应用（推荐）⭐

运行统一Web应用，在浏览器中完成所有操作：

```bash
python start_unified_app.py
```

访问 **http://localhost:5000** 打开统一应用界面。

统一应用包含三个模块：
- 📹 **数据采集** - 管理采集任务和视频数据
- 🎬 **标注生成** - 运行Pipeline并实时查看进度
- ✏️ **标注检验** - 人工检验和修正标注结果

**特色功能**：
- ✅ 实时进度显示（进度条 + 日志）
- ✅ WebSocket实时更新
- ✅ 完成后自动跳转到标注检验页面
- ✅ 统一的用户界面

详细使用说明请查看：[统一应用使用指南](docs/UNIFIED_APP_GUIDE.md)

### 4. 单独运行各个模块（单元测试）

如果需要单独测试某个模块，可以使用以下脚本：

#### 启动数据采集模块

```bash
python start_collection.py
```

访问 http://localhost:5001 进行数据采集。

#### 启动标注生成Pipeline

```bash
python start_pipeline.py
```

或使用向后兼容的入口：

```bash
python data_label_gen_pipeline.py
```

#### 启动标注检验模块

```bash
python start_annotation.py
```

访问 http://localhost:5001 进行标注检验。

## 📚 文档

- [统一应用使用指南](docs/UNIFIED_APP_GUIDE.md) - **统一Web应用详细文档（推荐阅读）** ⭐
- [Pipeline使用说明](docs/README_PIPELINE.md) - Pipeline详细文档
- [标注工具使用说明](docs/README_annotation.md) - 标注工具详细文档
- [快速开始指南](docs/QUICK_START.md) - 快速入门指南

## 🔧 主要功能

1. **统一Web应用** (`unified_server.py` + `unified_app.html`) ⭐
   - 整合数据采集、标注生成和人工检验的完整流程
   - 实时进度显示（进度条 + 日志）
   - WebSocket实时更新
   - 统一的用户界面
   - 完成后自动跳转

2. **意图推理Pipeline** (`pipeline/`)
   - 语音识别（ASR）
   - 视频分割和帧采样
   - 意图分析
   - 目标定位

3. **标注检验工具** (`tools/annotation/`)
   - Web界面标注
   - 可视化修正
   - 数据备份和管理
   - 支持相对路径和绝对路径

4. **数据采集工具** (`tools/data_collection/`)
   - 管理员模式：管理任务模板和场景类型
   - 采集模式：创建采集任务，管理视频数据
   - 自动统计视频数量
   - 视频预览功能

6. **SAM分割工具** (`tools/sam/`)
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

### 数据采集工具

访问 `http://localhost:5001` 使用Web界面进行数据采集：

1. **管理员模式**：
   - 创建和管理任务模板（包含任务指令、场景类型、目标数量、任务说明）
   - 创建和管理场景类型（包含场景名称和描述）

2. **采集模式**：
   - 选择任务模板和场景类型创建采集任务
   - 系统自动创建文件夹（位于 `collected_data/` 目录）
   - 将视频文件复制到创建的文件夹中
   - 点击"扫描文件夹"自动统计视频数量
   - 点击"查看详情"预览视频文件
   - 完成任务后标记为已完成

## 📄 输出

Pipeline会生成 `pipeline_data.json` 文件，包含：
- 视频信息和描述
- 物品描述和定位点
- 图像尺寸信息

## 📂 数据目录

- `pipeline/outputs/`: Pipeline输出数据
  - `pipeline_data.json`: 标注数据文件
  - `output_frames/`: 视频帧图像
- `annotation_backups/`: 标注工具备份文件
- `tools/data_collection/datas/`: 采集的视频数据存储目录
- `tools/data_collection/task_config/`: 数据采集工具配置文件（任务模板、场景类型、采集任务记录）

## 🔗 相关链接

- 统一应用使用指南: [docs/UNIFIED_APP_GUIDE.md](docs/UNIFIED_APP_GUIDE.md) - **推荐阅读** ⭐
- Pipeline文档: [docs/README_PIPELINE.md](docs/README_PIPELINE.md)
- 标注工具文档: [docs/README_annotation.md](docs/README_annotation.md)

## ✨ 新特性

- ✅ **统一Web应用**：整合数据采集、标注生成和人工检验的完整流程，支持实时进度显示 ⭐
- ✅ **模块化设计**：三个模块可独立启动进行单元测试
- ✅ **路径自动对齐**：自动处理相对路径和绝对路径，确保各流程无缝衔接
- ✅ **从采集任务选择视频**：Pipeline支持直接从采集任务中选择视频进行处理
- ✅ **实时进度显示**：Pipeline处理过程实时显示进度条和日志

