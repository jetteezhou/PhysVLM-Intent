# 🚀 快速开始指南

## 1. 安装依赖

```bash
pip install flask flask-cors
```

## 2. 生成数据

### 方式一：使用真实数据
```bash
python asr_test.py
```

### 方式二：使用演示数据
```bash
python demo_data.py
```

## 3. 启动标注工具

### 方式一：使用启动脚本（推荐）
```bash
python start_annotation_tool.py
```

### 方式二：直接启动服务器
```bash
python annotation_server.py
```

## 4. 使用标注工具

1. 打开浏览器访问 `http://localhost:5000`
2. 选择右侧面板中的物品
3. 点击图像修正定位点
4. 编辑描述和标签
5. 保存修正结果

## 🎯 主要功能

- ✅ 可视化物品定位点
- ✅ 点击修正位置坐标  
- ✅ 编辑物品描述和标签
- ✅ 自动备份和保存
- ✅ 历史记录管理
- ✅ 数据验证和导出

## 📁 文件说明

- `asr_test.py` - 主程序，生成标注数据
- `annotation_tool.html` - 前端标注界面
- `annotation_server.py` - 后端API服务器
- `start_annotation_tool.py` - 启动脚本
- `demo_data.py` - 创建演示数据
- `pipeline_data.json` - 标注数据文件

## ❓ 常见问题

**Q: 数据文件不存在怎么办？**
A: 先运行 `python demo_data.py` 创建演示数据

**Q: 图像无法显示？**  
A: 确保图像文件路径正确，或使用演示数据

**Q: 如何保存修改？**
A: 点击右侧面板的"保存修正结果"按钮

**Q: 如何重置修改？**
A: 点击"重置修改"按钮恢复到加载时的状态
