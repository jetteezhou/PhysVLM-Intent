#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动简易标注工具服务器
"""

import sys
import os

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from tools.annotation.simple_annotation_server import app

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 启动简易标注工具服务器")
    print("=" * 60)
    print("📋 访问地址: http://localhost:5002")
    print("💡 使用说明:")
    print("   1. 在浏览器中打开 http://localhost:5002")
    print("   2. 选择包含视频文件的文件夹")
    print("   3. 输入任务指令模板和场景")
    print("   4. 点击'加载视频'按钮")
    print("   5. 选择视频进行标注")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5002, debug=True)

