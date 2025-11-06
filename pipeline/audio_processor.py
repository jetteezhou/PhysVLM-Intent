"""音频处理模块"""
import os
import tempfile
from typing import List, Dict, Tuple, Optional
from http import HTTPStatus
from pydub import AudioSegment
import dashscope

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import AUDIO_SAMPLE_RATE, AUDIO_FORMAT, AUDIO_CHANNELS, ASR_MODEL


def convert_to_mono(input_file: str, output_file: Optional[str] = None) -> Optional[str]:
    """
    将音频文件转换为单声道16kHz的MP3格式
    
    Args:
        input_file: 输入音频文件路径
        output_file: 输出文件路径，如果为None则创建临时文件
    
    Returns:
        转换后的文件路径，失败时返回None
    """
    try:
        audio = AudioSegment.from_file(input_file)
        mono_audio = audio.set_channels(AUDIO_CHANNELS)
        mono_audio = mono_audio.set_frame_rate(AUDIO_SAMPLE_RATE)
        
        if output_file is None:
            temp_fd, output_file = tempfile.mkstemp(suffix='.mp3')
            os.close(temp_fd)
        
        mono_audio.export(output_file, format=AUDIO_FORMAT)
        return output_file
    except Exception as e:
        print(f"音频转换错误: {e}")
        return None


def audio_to_words_with_timestamps(
    audio_file_path: str,
    api_key: Optional[str] = None
) -> Tuple[bool, List[Dict[str, any]]]:
    """
    将音频文件转换为带时间戳的词汇列表
    
    Args:
        audio_file_path: 音频文件路径
        api_key: DashScope API密钥，如果为None则使用默认配置
    
    Returns:
        (识别是否成功, 词汇列表)
        词汇列表每个元素包含: text, begin_time, end_time
    """
    mono_audio_file = None
    
    try:
        if not os.path.exists(audio_file_path):
            print(f"错误：音频文件不存在 - {audio_file_path}")
            return False, []
        
        # 设置API密钥
        if api_key:
            dashscope.api_key = api_key
        
        # 转换音频为单声道
        mono_audio_file = convert_to_mono(audio_file_path)
        if mono_audio_file is None:
            print("音频转换失败")
            return False, []
        
        print(f"已将音频转换为单声道: {mono_audio_file}")
        
        # 创建识别对象
        from dashscope.audio.asr import Recognition
        recognition = Recognition(
            model=ASR_MODEL,
            format=AUDIO_FORMAT,
            sample_rate=AUDIO_SAMPLE_RATE,
            callback=None
        )
        
        # 执行语音识别
        result = recognition.call(mono_audio_file)
        
        if result.status_code == HTTPStatus.OK:
            print('识别成功')
            sentence = result.get_sentence()
            
            if sentence and len(sentence) > 0 and "words" in sentence[0]:
                words_list = sentence[0]["words"]
                
                # 打印识别指标
                print(f'[Metric] requestId: {recognition.get_last_request_id()}, '
                      f'first package delay ms: {recognition.get_first_package_delay()}, '
                      f'last package delay ms: {recognition.get_last_package_delay()}')
                
                return True, words_list
            else:
                print("识别结果为空")
                return False, []
        else:
            print(f'识别错误: {result.message}')
            return False, []
            
    except Exception as e:
        print(f"处理音频时发生错误: {e}")
        return False, []
    
    finally:
        # 清理临时文件
        if mono_audio_file and os.path.exists(mono_audio_file):
            try:
                os.remove(mono_audio_file)
                print(f"已清理临时文件: {mono_audio_file}")
            except Exception as e:
                print(f"清理临时文件时出错: {e}")


def print_words_with_timestamps(words_list: List[Dict[str, any]]) -> None:
    """
    打印带时间戳的词汇列表
    
    Args:
        words_list: 词汇列表
    """
    print("\n识别结果（词汇 | 开始时间 | 结束时间）：")
    print("-" * 50)
    for word in words_list:
        print(f"{word['text']} | {word['begin_time']}ms | {word['end_time']}ms")

