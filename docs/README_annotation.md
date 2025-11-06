# 意图目标标注工具

这是一个用于人工检查和修正AI生成的意图目标描述和定位点的Web工具。

## 功能特性

- 🎯 **可视化标注**: 在图像上直观显示物品定位点
- ✏️ **点击修正**: 点击图像任意位置修正物品定位
- 📝 **描述编辑**: 编辑物品描述和标签
- 💾 **数据保存**: 自动备份和保存修正结果
- 📊 **历史记录**: 查看和恢复历史标注版本
- 🔄 **数据验证**: 验证数据完整性

## 安装依赖

```bash
pip install -r requirements_annotation.txt
```

## 使用步骤

### 1. 生成数据文件

首先运行主程序生成标注数据：

```bash
python asr_test.py
```

这将生成 `pipeline_data.json` 文件，包含：
- 视频信息和描述
- 物品描述和定位点
- 图像尺寸信息

### 2. 启动标注服务器

```bash
python annotation_server.py
```

服务器将在 `http://localhost:5000` 启动。

### 3. 使用标注工具

1. 打开浏览器访问 `http://localhost:5000`
2. 页面会自动加载 `pipeline_data.json` 中的数据
3. 在右侧面板中选择要修正的物品
4. 点击图像上的任意位置来修正物品定位点
5. 编辑物品描述和标签
6. 点击"保存修正结果"按钮保存修改

## 文件结构

```
PhysVLM-Intent/
├── asr_test.py                 # 主程序，生成标注数据
├── annotation_tool.html        # 前端标注界面
├── annotation_server.py        # Flask后端服务器
├── pipeline_data.json          # 标注数据文件
├── annotation_backups/         # 备份目录
│   ├── pipeline_data_backup_*.json
│   └── annotated_data_*.json
├── output_frames/              # 视频帧图像
├── requirements_annotation.txt # 依赖包列表
└── README_annotation.md        # 使用说明
```

## API接口

### 数据接口
- `GET /pipeline_data.json` - 获取标注数据
- `POST /api/save_annotations` - 保存标注结果
- `GET /api/validate_data` - 验证数据完整性

### 历史记录
- `GET /api/get_annotations_history` - 获取标注历史
- `GET /api/load_annotation/<filename>` - 加载指定标注文件
- `POST /api/reset_annotations` - 重置到原始状态

### 文件服务
- `GET /images/<filename>` - 提供图像文件服务
- `GET /api/export_annotations` - 导出标注数据

## 数据格式

### pipeline_data.json 结构

```json
{
  "video_path": "test_data/IMG_3492_up.mp4",
  "last_image_path": "output_frames/充电_3400.jpg",
  "video_description": "视频描述文本...",
  "result_data": [...],
  "image_dimensions": {
    "width": 1920,
    "height": 1080
  },
  "objects": [
    {
      "id": 0,
      "description": "物品描述",
      "point": [500, 300],           // 归一化坐标 [y, x] 0-1000
      "label": "物品标签",
      "pixel_coords": [576, 540],    // 绝对像素坐标 [x, y]
      "normalized_coords": [0.3, 0.5] // 归一化坐标 [x, y] 0-1
    }
  ]
}
```

## 使用说明

### 界面操作

1. **选择物品**: 点击右侧面板中的物品卡片来选择要修正的物品
2. **修正位置**: 选中物品后，点击图像上的任意位置来更新物品定位点
3. **编辑描述**: 在物品卡片中直接编辑描述和标签文本
4. **保存修改**: 点击"保存修正结果"按钮保存所有修改
5. **重置修改**: 点击"重置修改"按钮恢复到加载时的状态

### 颜色标识

- 🔴 红色: 物品1
- 🟢 绿色: 物品2  
- 🔵 蓝色: 物品3

### 数据备份

- 每次保存时自动创建备份文件
- 备份文件保存在 `annotation_backups/` 目录
- 文件名格式: `annotated_data_YYYYMMDD_HHMMSS.json`

## 故障排除

### 常见问题

1. **数据文件不存在**
   - 确保先运行 `asr_test.py` 生成数据文件

2. **图像无法显示**
   - 检查图像文件路径是否正确
   - 确保图像文件存在于指定位置

3. **保存失败**
   - 检查文件权限
   - 确保有足够的磁盘空间

4. **服务器启动失败**
   - 检查端口5000是否被占用
   - 确保安装了所有依赖包

### 日志查看

服务器运行时会在控制台输出详细日志，包括：
- 数据加载状态
- 保存操作结果
- 错误信息

## 扩展功能

可以根据需要扩展以下功能：
- 支持更多物品类型
- 添加标注质量评估
- 集成更多AI模型
- 支持批量处理
- 添加用户权限管理
