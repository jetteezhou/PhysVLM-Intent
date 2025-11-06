"""意图推理与目标定位数据标注Pipeline - 主入口文件（向后兼容）"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.pipeline import IntentLabelPipeline, main

# 为了向后兼容，保留原有的函数接口
from pipeline.audio_processor import (
    convert_to_mono,
    audio_to_words_with_timestamps,
    print_words_with_timestamps
)
from pipeline.video_processor import split_video_by_words
from utils.image_utils import image_to_base64 as build_base64_from_image_path
from pipeline.llm_client import LLMClient

# 导出主要类和函数
__all__ = [
    'IntentLabelPipeline',
    'main',
    'convert_to_mono',
    'audio_to_words_with_timestamps',
    'print_words_with_timestamps',
    'split_video_by_words',
    'build_base64_from_image_path',
    'LLMClient',
]

# 如果直接运行此文件，执行main函数
if __name__ == "__main__":
    main()
