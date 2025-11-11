#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess

# 获取项目根目录和当前脚本目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

def check_dependencies():
    """检查依赖包是否安装"""
    try:
        import flask
        import flask_cors
        print("✅ 依赖包检查通过")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖包: {e}")
        print("请运行: pip install -r requirements_annotation.txt")
        return False

def create_directories():
    """创建必要的目录"""
    directories = [
        os.path.join(CURRENT_DIR, "task_config"),  # 任务配置目录
        os.path.join(CURRENT_DIR, "datas")  # 采集数据存储目录
    ]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"📁 创建目录: {directory}")
        else:
            print(f"📁 目录已存在: {directory}")

def start_server():
    """启动数据采集服务器"""
    try:
        print("\n🚀 启动数据采集工具服务器...")
        print("=" * 50)
        print("📋 访问地址: http://localhost:5001")
        print("💡 使用说明:")
        print("   1. 管理员模式：管理任务模板和场景类型")
        print("   2. 采集模式：创建采集任务，选择模板和场景")
        print("   3. 将视频文件复制到创建的文件夹中")
        print("   4. 点击'扫描文件夹'自动统计视频数量")
        print("   5. 点击'查看详情'预览视频文件")
        print("=" * 50)
        print("按 Ctrl+C 停止服务器\n")
        
        # 启动Flask服务器
        server_path = os.path.join(CURRENT_DIR, "collection_server.py")
        subprocess.run([sys.executable, server_path])
        
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
    except Exception as e:
        print(f"❌ 启动服务器失败: {e}")

def main():
    """主函数"""
    print("📹 数据采集工具启动器")
    print("=" * 40)
    
    # 检查依赖
    if not check_dependencies():
        return
    
    # 创建必要目录
    create_directories()
    
    # 启动服务器
    start_server()

if __name__ == "__main__":
    main()

