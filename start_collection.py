#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动数据采集工具的便捷脚本"""
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入并运行启动脚本
from tools.data_collection.start_collection_tool import main

if __name__ == "__main__":
    main()

