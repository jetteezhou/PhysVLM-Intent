#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动统一Web应用"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from unified_server import app, socketio

if __name__ == '__main__':
    print("🚀 启动统一Web应用服务器...")
    print("📋 访问地址: http://localhost:5001")
    print("=" * 50)
    print("💡 功能模块:")
    print("   1. 📹 数据采集 - 管理采集任务和视频数据")
    print("   2. 🎬 标注生成 - 运行Pipeline并查看进度")
    print("   3. ✏️  标注检验 - 人工检验和修正标注结果")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)

