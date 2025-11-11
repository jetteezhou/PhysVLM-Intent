"""视频处理模块"""
import os
import cv2
from typing import List, Dict, Any, Tuple


def split_video_by_words(
    video_path: str,
    words_list: List[Dict[str, Any]],
    output_dir: str = "output_frames",
    sampling_interval: int = 300
) -> Tuple[List[Dict[str, Any]], str]:
    """
    根据词汇时间戳分割视频并采样帧
    
    Args:
        video_path: 视频文件路径
        words_list: 词汇列表，每个元素包含text、begin_time、end_time字段
        output_dir: 输出图片的目录
        sampling_interval: 采样间隔，单位毫秒，默认300ms
    
    Returns:
        (result_data, last_frame_path) 元组
        result_data: 包含词汇、时间戳和图片路径的列表
        格式: [{
            "词汇": str,
            "时间戳": [begin_time, end_time],
            "图片路径列表": [str, ...]
        }, ...]
        last_frame_path: 视频最后一帧的图片路径
    """
    if not os.path.exists(video_path):
        print(f"错误：视频文件不存在 - {video_path}")
        return [], ""
    
    if not words_list:
        print("错误：词汇列表为空")
        return [], ""
    
    # 创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建输出目录: {output_dir}")
    
    # 打开视频文件
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"错误：无法打开视频文件 - {video_path}")
        return [], ""
    
    # 获取视频信息
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_ms = (total_frames / fps) * 1000
    
    print(f"视频信息: FPS={fps:.2f}, 总帧数={total_frames}, 时长={duration_ms:.0f}ms")
    
    # 计算最后一帧的时间戳（毫秒）
    last_frame_time_ms = int(duration_ms)
    
    result_data = []
    
    try:
        for word_info in words_list:
            word_text = word_info['text']
            begin_time = word_info['begin_time']  # 毫秒
            end_time = word_info['end_time']      # 毫秒
            
            print(f"处理词汇: {word_text} ({begin_time}ms - {end_time}ms)")
            
            # 计算需要采样的时间点
            sample_times = [begin_time]
            
            # 添加中间的采样点（每sampling_interval毫秒一个）
            current_time = begin_time + sampling_interval
            while current_time < end_time:
                sample_times.append(current_time)
                current_time += sampling_interval
            
            # 添加结束时间（如果不在列表中）
            if end_time not in sample_times:
                sample_times.append(end_time)
            
            # 提取帧并保存
            image_paths = []
            for sample_time in sample_times:
                # 计算对应的帧号
                frame_number = int((sample_time / 1000.0) * fps)
                
                # 确保帧号在有效范围内
                if frame_number >= total_frames:
                    frame_number = total_frames - 1
                
                # 跳转到指定帧
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                ret, frame = cap.read()
                
                if ret:
                    # 生成文件名
                    filename = f"{sample_time}_{word_text}.jpg"
                    filepath = os.path.join(output_dir, filename)
                    
                    # 保存图片
                    success = cv2.imwrite(filepath, frame)
                    if success:
                        image_paths.append(filepath)
                        print(f"  保存帧: {filepath}")
                    else:
                        print(f"  保存帧失败: {filepath}")
                else:
                    print(f"  读取帧失败: 时间={sample_time}ms, 帧号={frame_number}")
            
            # 添加到结果数据
            word_data = {
                "词汇": word_text,
                "时间戳": [begin_time, end_time],
                "图片路径列表": image_paths
            }
            result_data.append(word_data)
        
        # 保存视频的最后一帧
        print(f"\n@@@ 保存视频最后一帧...")
        last_frame_number = total_frames - 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, last_frame_number)
        ret, last_frame = cap.read()
        
        last_frame_path = ""
        if ret:
            # 生成最后一帧的文件名：时间戳_last.jpg
            last_frame_filename = f"{last_frame_time_ms}_last.jpg"
            last_frame_path = os.path.join(output_dir, last_frame_filename)
            
            # 保存最后一帧
            success = cv2.imwrite(last_frame_path, last_frame)
            if success:
                print(f"  保存最后一帧: {last_frame_path}")
            else:
                print(f"  保存最后一帧失败: {last_frame_path}")
                last_frame_path = ""
        else:
            print(f"  读取最后一帧失败: 帧号={last_frame_number}")
    
    finally:
        cap.release()
    
    return result_data, last_frame_path

