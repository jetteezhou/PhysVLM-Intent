"""图像处理工具函数"""
import base64
from typing import Optional


def image_to_base64(image_path: str) -> Optional[str]:
    """
    将图片转换为base64编码
    
    Args:
        image_path: 图片文件路径
    
    Returns:
        base64编码的字符串，失败时返回None
    """
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        print(f"图像转换错误: {e}")
        return None

