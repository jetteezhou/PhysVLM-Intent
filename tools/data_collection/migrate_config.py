#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""迁移配置文件到新位置"""
import os
import shutil
import sys

# 获取项目根目录和当前脚本目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

OLD_CONFIG_DIR = os.path.join(PROJECT_ROOT, 'data_collection')
NEW_CONFIG_DIR = os.path.join(CURRENT_DIR, 'task_config')

CONFIG_FILES = ['templates.json', 'scenes.json', 'collections.json']

def migrate_config_files():
    """迁移配置文件到新位置"""
    # 创建新目录
    if not os.path.exists(NEW_CONFIG_DIR):
        os.makedirs(NEW_CONFIG_DIR)
        print(f"✅ 创建新配置目录: {NEW_CONFIG_DIR}")
    
    migrated_count = 0
    for filename in CONFIG_FILES:
        old_path = os.path.join(OLD_CONFIG_DIR, filename)
        new_path = os.path.join(NEW_CONFIG_DIR, filename)
        
        if os.path.exists(old_path):
            if os.path.exists(new_path):
                print(f"⚠️  {filename} 在新位置已存在，跳过迁移")
            else:
                shutil.copy2(old_path, new_path)
                print(f"✅ 迁移 {filename} 到新位置")
                migrated_count += 1
        else:
            print(f"ℹ️  {filename} 在旧位置不存在，跳过")
    
    if migrated_count > 0:
        print(f"\n✅ 成功迁移 {migrated_count} 个配置文件")
        print(f"📁 新配置目录: {NEW_CONFIG_DIR}")
        print(f"💡 建议：确认新位置文件正常后，可以删除旧目录 {OLD_CONFIG_DIR}")
    else:
        print("\nℹ️  没有需要迁移的配置文件")

if __name__ == "__main__":
    print("🔄 开始迁移配置文件...")
    print("=" * 50)
    migrate_config_files()
    print("=" * 50)

