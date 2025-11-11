#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动标注生成Pipeline的便捷脚本"""
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入并运行Pipeline的main函数
from pipeline.pipeline import main

if __name__ == "__main__":
    main()

