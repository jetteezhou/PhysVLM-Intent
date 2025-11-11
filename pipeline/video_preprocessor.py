"""视频预处理模块 - 从视频文件中提取音频和视频"""
import os
import subprocess
import tempfile
from typing import Tuple, Optional


def extract_audio_and_video(
    input_video_path: str,
    output_dir: Optional[str] = None,
    audio_filename: Optional[str] = None,
    video_filename: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    从视频文件中提取音频和视频
    
    支持的输入格式: mp4, mov, avi, mkv等ffmpeg支持的格式
    输出格式: 
        - 音频: mp3
        - 视频: mp4
    
    Args:
        input_video_path: 输入视频文件路径
        output_dir: 输出目录，如果为None则使用输入文件所在目录
        audio_filename: 输出音频文件名，如果为None则自动生成（基于输入文件名）
        video_filename: 输出视频文件名，如果为None则自动生成（基于输入文件名）
    
    Returns:
        (audio_path, video_path) 元组，失败时返回(None, None)
    """
    if not os.path.exists(input_video_path):
        print(f"错误：输入视频文件不存在 - {input_video_path}")
        return None, None
    
    # 确定输出目录
    if output_dir is None:
        output_dir = os.path.dirname(input_video_path) or "."
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成输出文件名
    input_basename = os.path.splitext(os.path.basename(input_video_path))[0]
    
    if audio_filename is None:
        audio_filename = f"{input_basename}.mp3"
    if video_filename is None:
        video_filename = f"{input_basename}.mp4"
    
    audio_path = os.path.join(output_dir, audio_filename)
    video_path = os.path.join(output_dir, video_filename)
    
    try:
        # 提取音频
        print(f"\n@@@ 开始提取音频: {input_video_path} -> {audio_path}")
        subprocess.run([
            "ffmpeg", "-y",  # -y 表示覆盖输出文件
            "-i", input_video_path,
            "-vn",  # 不包含视频流
            "-acodec", "libmp3lame",  # 使用mp3编码器
            "-ar", "16000",  # 采样率16kHz（与ASR模型匹配）
            "-ac", "1",  # 单声道
            audio_path
        ], check=True, capture_output=True)
        print(f"@@@ 音频提取成功: {audio_path}")
        
        # 提取视频（去除音频轨道）
        print(f"\n@@@ 开始提取视频: {input_video_path} -> {video_path}")
        subprocess.run([
            "ffmpeg", "-y",  # -y 表示覆盖输出文件
            "-i", input_video_path,
            "-an",  # 不包含音频流
            "-c:v", "copy",  # 复制视频流，不重新编码（更快）
            video_path
        ], check=True, capture_output=True)
        print(f"@@@ 视频提取成功: {video_path}")
        
        return audio_path, video_path
        
    except subprocess.CalledProcessError as e:
        print(f"错误：ffmpeg处理失败 - {e}")
        if e.stderr:
            print(f"错误信息: {e.stderr.decode('utf-8', errors='ignore')}")
        return None, None
    except FileNotFoundError:
        print("错误：未找到ffmpeg，请确保已安装ffmpeg并添加到系统PATH中")
        return None, None
    except Exception as e:
        print(f"错误：视频预处理失败 - {e}")
        return None, None

