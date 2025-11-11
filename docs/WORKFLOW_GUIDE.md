# PhysVLM-Intent 工作流使用指南

本项目提供了一个完整的数据采集、标注生成和人工检验标注的工作流。

## 快速开始

### 方式一：使用统一Web应用（推荐）⭐

运行统一Web应用，在浏览器中完成所有操作：

```bash
python start_unified_app.py
```

访问 **http://localhost:5001** 打开统一应用界面。

统一应用包含三个模块：
- 📹 **数据采集** - 管理采集任务和视频数据
- 🎬 **标注生成** - 运行Pipeline并实时查看进度
- ✏️ **标注检验** - 人工检验和修正标注结果

**特色功能**：
- ✅ 实时进度显示（进度条 + 日志）
- ✅ WebSocket实时更新
- ✅ 完成后自动跳转到标注检验页面
- ✅ 统一的用户界面

详细使用说明请查看：[统一应用使用指南](UNIFIED_APP_GUIDE.md)

### 方式二：单独运行各个模块（单元测试）

如果需要单独测试某个模块，可以使用以下脚本：

#### 1. 数据采集

```bash
python start_collection.py
# 或
python tools/data_collection/start_collection_tool.py
```

访问 http://localhost:5001 进行数据采集。

#### 2. 标注生成

```bash
python start_pipeline.py
# 或使用向后兼容的入口
python data_label_gen_pipeline.py
```

#### 3. 标注检验

```bash
python start_annotation.py
# 或
python tools/annotation/start_annotation_tool.py
```

访问 http://localhost:5000 进行标注检验。

## 工作流程

### 1. 数据采集阶段

1. 启动数据采集工具
2. 在管理员模式下创建指令模板和场景类型
3. 在采集模式下创建采集任务
4. 将视频文件复制到创建的文件夹中
5. 点击"扫描文件夹"统计视频数量

**数据存储位置：**
- 采集任务配置：`tools/data_collection/task_config/collections.json`
- 视频文件：`tools/data_collection/datas/{任务文件夹}/`

### 2. 标注生成阶段

1. 从采集任务中选择视频，或手动指定视频路径
2. Pipeline自动执行以下步骤：
   - 视频预处理（提取音频和视频）
   - 语音识别（ASR）
   - 视频分割和帧采样
   - LLM分析视频意图和物品描述
   - 物品定位

**输出位置：**
- 标注数据：`pipeline/outputs/pipeline_data.json`
- 帧图像：`pipeline/outputs/output_frames/{视频名称}/`
- 结果图像：`pipeline/outputs/pipeline_point_result.jpg`

### 3. 人工检验标注阶段

1. 启动标注工具
2. 查看自动生成的标注结果
3. 点击图像修正物品定位点
4. 编辑物品描述和标签
5. 保存修正结果

**备份位置：**
- 标注备份：`annotation_backups/`

## 路径对齐说明

项目已经实现了路径的自动对齐：

1. **Pipeline输出**：所有路径都保存为相对于项目根目录的相对路径
2. **标注工具**：自动识别相对路径和绝对路径，支持多种路径格式
3. **图像服务**：支持从多个目录查找图像文件

## 文件结构

```
PhysVLM-Intent/
├── start_unified_app.py         # 统一Web应用启动脚本（推荐）
├── start_pipeline.py            # Pipeline启动脚本（单元测试用）
├── start_collection.py          # 数据采集工具启动脚本（单元测试用）
├── start_annotation.py          # 标注工具启动脚本（单元测试用）
├── data_label_gen_pipeline.py   # Pipeline主入口文件（向后兼容）
│
├── pipeline/                    # Pipeline核心代码
│   ├── pipeline.py              # 主Pipeline
│   ├── outputs/                 # Pipeline输出目录
│   │   ├── pipeline_data.json   # 标注数据
│   │   └── output_frames/       # 帧图像
│   └── ...
│
├── tools/
│   ├── data_collection/         # 数据采集工具
│   │   ├── datas/               # 采集的视频数据
│   │   └── task_config/         # 任务配置
│   └── annotation/              # 标注工具
│       └── ...
│
└── annotation_backups/          # 标注备份目录
```

## 注意事项

1. **视频格式**：支持 mp4, mov, avi, mkv, flv, wmv, m4v, webm 等格式
2. **路径要求**：建议使用相对路径，系统会自动处理路径转换
3. **数据备份**：标注工具会自动创建备份，保存在 `annotation_backups/` 目录
4. **API配置**：请确保在环境变量或 `config/settings.py` 中配置了必要的API密钥

## 常见问题

### Q: 图像无法显示？
A: 检查 `pipeline_data.json` 中的 `last_image_path` 路径是否正确，确保图像文件存在。

### Q: 如何从采集任务中选择视频？
A: 使用统一Web应用 (`start_unified_app.py`)，在"标注生成"模块中选择"从采集任务中选择"。

### Q: Pipeline执行失败？
A: 检查视频文件是否存在，API密钥是否正确配置，以及网络连接是否正常。

## 更新日志

- **2024-01-XX**: 实现统一Web应用，整合数据采集、标注生成和人工检验流程
- **2024-01-XX**: 修复路径对齐问题，确保各流程能够无缝衔接
- **2024-01-XX**: 优化项目结构，删除冗余文件，保留统一Web应用和独立模块启动脚本

