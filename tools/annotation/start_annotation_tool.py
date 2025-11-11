#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import json
from pathlib import Path

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

def check_data_file():
    """检查数据文件是否存在"""
    data_file = os.path.join(PROJECT_ROOT, "pipeline/outputs/pipeline_data.json")
    if os.path.exists(data_file):
        print(f"✅ 找到数据文件: {data_file}")
        
        # 验证数据文件格式
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            required_fields = ['video_path', 'last_image_path', 'objects', 'image_dimensions']
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                print(f"⚠️  数据文件格式不完整，缺少字段: {', '.join(missing_fields)}")
                return False
            
            print(f"📊 数据文件包含 {len(data['objects'])} 个物品")
            
            # 检查图像文件是否存在（支持相对路径和绝对路径）
            image_path = data.get('last_image_path_absolute') or data.get('last_image_path', '')
            if image_path:
                # 如果是相对路径，转换为绝对路径
                if not os.path.isabs(image_path):
                    image_path = os.path.join(PROJECT_ROOT, image_path)
                if os.path.exists(image_path):
                    print(f"✅ 图像文件存在: {image_path}")
                else:
                    print(f"⚠️  图像文件不存在: {image_path}")
                    print("   标注工具仍可使用，但图像可能无法显示")
            else:
                print("⚠️  未找到图像路径信息")
                print("   标注工具仍可使用，但图像可能无法显示")
            
            return True
            
        except json.JSONDecodeError:
            print("❌ 数据文件格式错误，不是有效的JSON文件")
            return False
        except Exception as e:
            print(f"❌ 读取数据文件失败: {e}")
            return False
    else:
        print(f"❌ 数据文件不存在: {data_file}")
        print("请先运行 asr_test.py 生成数据文件")
        return False

def create_backup_dir():
    """创建备份目录"""
    backup_dir = os.path.join(PROJECT_ROOT, "annotation_backups")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        print(f"📁 创建备份目录: {backup_dir}")
    else:
        print(f"📁 备份目录已存在: {backup_dir}")

def start_server():
    """启动标注服务器"""
    try:
        print("\n🚀 启动标注工具服务器...")
        print("=" * 50)
        print("📋 访问地址: http://localhost:5001")
        print("💡 使用说明:")
        print("   1. 在右侧面板选择要修正的物品")
        print("   2. 点击图像上的位置来修正定位点")
        print("   3. 编辑物品描述和标签")
        print("   4. 点击'保存修正结果'按钮保存修改")
        print("=" * 50)
        print("按 Ctrl+C 停止服务器\n")
        
        # 启动Flask服务器
        server_path = os.path.join(CURRENT_DIR, "annotation_server.py")
        subprocess.run([sys.executable, server_path])
        
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
    except Exception as e:
        print(f"❌ 启动服务器失败: {e}")

def main():
    """主函数"""
    print("🎯 意图目标标注工具启动器")
    print("=" * 40)
    
    # 检查依赖
    if not check_dependencies():
        return
    
    # 检查数据文件
    if not check_data_file():
        response = input("\n是否继续启动服务器？(y/N): ").strip().lower()
        if response != 'y':
            print("👋 已取消启动")
            return
    
    # 创建备份目录
    create_backup_dir()
    
    # 启动服务器
    start_server()

if __name__ == "__main__":
    main()
