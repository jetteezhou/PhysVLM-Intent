#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from test import sam3_segment_with_points, normalize_to_pixel
from config.settings import DASHSCOPE_API_KEY
from pipeline.audio_processor import audio_to_words_with_timestamps
from pipeline.video_preprocessor import extract_audio_and_video
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import os
import sys
import logging
import cv2
import tempfile
import shutil
import subprocess
import hashlib
import time
import platform
from pathlib import Path
from threading import Lock
from collections import OrderedDict

# 获取项目根目录路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 导入ASR相关模块

# 导入SAM3工具函数

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 临时文件存储目录
TEMP_DIR = os.path.join(PROJECT_ROOT, 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)

# Windows 转换视频临时目录
WINDOWS_TEMP_DIR = os.path.join(PROJECT_ROOT, 'Windows_temp')
os.makedirs(WINDOWS_TEMP_DIR, exist_ok=True)

# 缓存配置
CACHE_MAX_SIZE_MB = 500  # 最大缓存大小（MB）
CACHE_MAX_AGE_HOURS = 24  # 缓存文件最大保留时间（小时）
CACHE_CLEANUP_INTERVAL = 3600  # 清理间隔（秒）

# 缓存管理锁
_cache_lock = Lock()

# 文件访问时间记录（用于LRU缓存清理）
_file_access_times = OrderedDict()


def get_file_hash(file_path: str) -> str:
    """计算文件的MD5哈希值（用于缓存键）"""
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            # 只读取文件的前1MB来计算hash（提高性能）
            chunk = f.read(1024 * 1024)
            hash_md5.update(chunk)
            # 同时使用文件大小和修改时间
            stat = os.stat(file_path)
            hash_md5.update(str(stat.st_size).encode())
            hash_md5.update(str(int(stat.st_mtime)).encode())
        return hash_md5.hexdigest()
    except Exception as e:
        logger.warning(f"计算文件hash失败: {e}")
        # 如果计算hash失败，使用文件名和修改时间
        try:
            stat = os.stat(file_path)
            return hashlib.md5(f"{file_path}_{stat.st_mtime}".encode()).hexdigest()
        except:
            return hashlib.md5(file_path.encode()).hexdigest()


def update_file_access_time(file_path: str):
    """更新文件访问时间（用于LRU缓存管理）"""
    with _cache_lock:
        if file_path in _file_access_times:
            _file_access_times.move_to_end(file_path)
        else:
            _file_access_times[file_path] = time.time()
        # 限制字典大小，避免内存占用过大
        if len(_file_access_times) > 1000:
            _file_access_times.popitem(last=False)


def cleanup_temp_files(max_age_hours: int = CACHE_MAX_AGE_HOURS, max_size_mb: int = CACHE_MAX_SIZE_MB):
    """
    清理临时文件
    策略：
    1. 删除超过最大保留时间的文件
    2. 如果总大小超过限制，删除最久未访问的文件（LRU）
    """
    try:
        temp_dirs = [TEMP_DIR]
        if platform.system() == 'Windows':
            temp_dirs.append(WINDOWS_TEMP_DIR)

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        max_size_bytes = max_size_mb * 1024 * 1024

        total_size = 0
        files_info = []

        # 收集所有文件信息
        for temp_dir in temp_dirs:
            if not os.path.exists(temp_dir):
                continue
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        stat = os.stat(file_path)
                        file_age = current_time - stat.st_mtime
                        file_size = stat.st_size
                        access_time = _file_access_times.get(
                            file_path, stat.st_mtime)

                        files_info.append({
                            'path': file_path,
                            'size': file_size,
                            'age': file_age,
                            'access_time': access_time,
                            'mtime': stat.st_mtime
                        })
                        total_size += file_size
                    except Exception as e:
                        logger.debug(f"无法获取文件信息 {file_path}: {e}")

        # 按访问时间排序（最久未访问的在前面）
        files_info.sort(key=lambda x: x['access_time'])

        deleted_count = 0
        deleted_size = 0

        # 1. 删除超过最大保留时间的文件
        for file_info in files_info[:]:
            if file_info['age'] > max_age_seconds:
                try:
                    os.remove(file_info['path'])
                    deleted_count += 1
                    deleted_size += file_info['size']
                    total_size -= file_info['size']
                    files_info.remove(file_info)
                    if file_info['path'] in _file_access_times:
                        del _file_access_times[file_info['path']]
                    logger.debug(f"删除过期文件: {file_info['path']}")
                except Exception as e:
                    logger.warning(f"删除文件失败 {file_info['path']}: {e}")

        # 2. 如果总大小超过限制，删除最久未访问的文件（LRU）
        while total_size > max_size_bytes and files_info:
            file_info = files_info.pop(0)
            try:
                os.remove(file_info['path'])
                deleted_count += 1
                deleted_size += file_info['size']
                total_size -= file_info['size']
                if file_info['path'] in _file_access_times:
                    del _file_access_times[file_info['path']]
                logger.debug(f"删除LRU文件: {file_info['path']}")
            except Exception as e:
                logger.warning(f"删除文件失败 {file_info['path']}: {e}")

        if deleted_count > 0:
            logger.info(
                f"[缓存清理] 删除了 {deleted_count} 个文件，释放 {deleted_size / 1024 / 1024:.2f} MB 空间")

        return deleted_count, deleted_size

    except Exception as e:
        logger.error(f"[缓存清理] 清理临时文件失败: {e}")
        return 0, 0


# 启动时清理一次
cleanup_temp_files()


def extract_last_frame(video_path: str) -> str:
    """
    提取视频的最后一帧并保存为临时图片
    优先使用ffmpeg，如果失败则回退到OpenCV
    使用文件hash作为缓存键，避免重复提取

    Args:
        video_path: 视频文件路径

    Returns:
        临时图片文件路径
    """
    # 使用文件hash作为缓存键
    file_hash = get_file_hash(video_path)
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    temp_filename = f"{video_name}_{file_hash[:8]}_last_frame.jpg"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    # 如果缓存文件存在且有效，直接返回
    if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
        update_file_access_time(temp_path)
        logger.debug(f"[提取最后一帧] 使用缓存: {temp_path}")
        return temp_path

    # 方法1: 尝试使用ffmpeg提取最后一帧（更可靠，特别是在Windows上）
    try:
        logger.info(f"[提取最后一帧] 尝试使用ffmpeg提取: {video_path}")

        # 优化：优先使用 -sseof 参数，避免调用 ffprobe 获取时长，减少子进程开销
        extract_result = subprocess.run([
            "ffmpeg", "-y",
            "-sseof", "-0.1",  # 从文件末尾倒数 0.1 秒开始，通常能快速命中最后一帧
            "-i", video_path,
            "-update", "1",
            "-vframes", "1",
            "-q:v", "2",
            temp_path
        ], capture_output=True, text=True, timeout=15, encoding='utf-8', errors='replace')

        if extract_result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            update_file_access_time(temp_path)
            logger.info(f"[提取最后一帧] ffmpeg -sseof 提取成功: {temp_path}")
            return temp_path

        logger.warning(
            f"[提取最后一帧] ffmpeg -sseof 失败，尝试常规方法: {extract_result.stderr}")

        # 如果 -sseof 失败（某些老版本 ffmpeg 不支持），再尝试获取时长的方法
        probe_result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ], capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace')

        if probe_result.returncode == 0:
            try:
                duration = float(probe_result.stdout.strip())
                start_time = max(0, duration - 0.2)  # 缩短搜寻范围

                extract_result = subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-i", video_path,
                    "-vframes", "1",
                    "-q:v", "2",
                    temp_path
                ], capture_output=True, text=True, timeout=20, encoding='utf-8', errors='replace')

                if extract_result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    update_file_access_time(temp_path)
                    logger.info(f"[提取最后一帧] ffmpeg -ss 提取成功: {temp_path}")
                    return temp_path
            except:
                pass

        raise ValueError("ffmpeg所有提取方法均失败")

    except FileNotFoundError:
        logger.warning(f"[提取最后一帧] 未找到ffmpeg，回退到OpenCV方法")
    except subprocess.TimeoutExpired:
        logger.warning(f"[提取最后一帧] ffmpeg超时，回退到OpenCV方法")
    except Exception as e:
        logger.warning(f"[提取最后一帧] ffmpeg方法失败: {e}，回退到OpenCV方法")

    # 方法2: 回退到OpenCV方法
    try:
        logger.info(f"[提取最后一帧] 使用OpenCV提取: {video_path}")
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"无法打开视频文件: {video_path}")

        # 获取视频总帧数
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames == 0:
            raise ValueError("视频文件没有帧")

        # 跳转到最后一帧
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
        ret, frame = cap.read()

        if not ret:
            raise ValueError("无法读取最后一帧")

        # 保存最后一帧
        success = cv2.imwrite(temp_path, frame)
        if not success:
            raise ValueError("保存最后一帧失败")

        cap.release()
        update_file_access_time(temp_path)
        logger.info(f"[提取最后一帧] OpenCV提取成功: {temp_path}")
        return temp_path

    except Exception as e:
        logger.error(f"[提取最后一帧] 所有方法都失败: {e}")
        raise ValueError(f"无法提取视频的最后一帧: {str(e)}")


def check_video_codec_compatible(video_path: str) -> bool:
    """
    检查视频编码是否与浏览器兼容（主要用于 Windows 平台）

    Args:
        video_path: 视频文件路径

    Returns:
        如果视频编码兼容返回 True，否则返回 False
    """
    try:
        # 使用 ffprobe 检查视频编码
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ], capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace')

        if result.returncode == 0:
            codec = result.stdout.strip().lower()
            # 浏览器兼容的视频编码
            compatible_codecs = {'h264', 'avc1', 'avc', 'vp8', 'vp9', 'av1'}
            is_compatible = codec in compatible_codecs
            logger.debug(f"[编码检查] 视频编码: {codec}, 兼容性: {is_compatible}")
            return is_compatible
        else:
            logger.warning(f"[编码检查] ffprobe 检查失败: {result.stderr}")
            return True  # 检查失败时假设兼容

    except FileNotFoundError:
        logger.debug("[编码检查] ffprobe 未找到，跳过编码检查")
        return True  # ffprobe 未安装时假设兼容
    except Exception as e:
        logger.warning(f"[编码检查] 检查视频编码失败: {e}")
        return True  # 检查失败时假设兼容


def convert_video_for_browser(video_path: str, force_convert: bool = False) -> str:
    """
    将视频转换为浏览器兼容的MP4格式
    如果视频已经是MP4格式且浏览器兼容，则直接返回原文件路径
    否则转换为MP4格式并保存到临时目录
    使用文件hash作为缓存键，避免重复转换

    Args:
        video_path: 原始视频文件路径
        force_convert: 是否强制转换（用于 Windows 兼容性）

    Returns:
        转换后的MP4文件路径（如果已经是兼容格式则返回原路径）
    """
    # 检查文件扩展名
    file_ext = os.path.splitext(video_path)[1].lower()

    # 浏览器兼容的格式列表（主要是MP4）
    browser_compatible_formats = {'.mp4'}

    # 使用文件hash作为缓存键，避免重复转换
    file_hash = get_file_hash(video_path)
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    converted_filename = f"{video_name}_{file_hash[:8]}_converted.mp4"

    # Windows 转换的视频存放在 Windows_temp 目录
    if platform.system() == 'Windows':
        converted_path = os.path.join(WINDOWS_TEMP_DIR, converted_filename)
    else:
        converted_path = os.path.join(TEMP_DIR, converted_filename)

    # 如果转换后的文件已存在，直接返回
    if os.path.exists(converted_path) and os.path.getsize(converted_path) > 0:
        update_file_access_time(converted_path)
        logger.info(f"[视频转换] 使用已存在的转换文件: {converted_path}")
        return converted_path

    # 如果已经是兼容格式，检查是否需要转换
    if file_ext in browser_compatible_formats and not force_convert:
        # 在 Windows 上额外检查视频编码是否兼容
        if platform.system() == 'Windows':
            if check_video_codec_compatible(video_path):
                logger.info(f"[视频转换] 视频格式和编码已兼容: {video_path}")
                return video_path
            else:
                logger.info(f"[视频转换] [Windows兼容] 视频编码不兼容，需要转换: {video_path}")
        else:
            logger.info(f"[视频转换] 视频格式已兼容: {video_path}")
            return video_path
    elif not force_convert:
        # 需要转换格式（MOV等格式在Windows上需要转换）
        # 特别处理MOV格式：Windows下通常需要转换
        if platform.system() == 'Windows' and file_ext in {'.mov', '.MOV'}:
            logger.info(f"[视频转换] [Windows兼容] MOV格式需要转换: {video_path}")
        else:
            logger.info(f"[视频转换] 开始转换视频格式: {video_path} (格式: {file_ext})")
    else:
        logger.info(f"[视频转换] [Windows兼容] 强制转换视频: {video_path}")

    try:
        # 使用ffmpeg转换为MP4格式（使用H.264编码，浏览器兼容性最好）
        logger.info(f"[视频转换] 使用ffmpeg转换视频...")
        result = subprocess.run([
            "ffmpeg", "-y",  # -y 表示覆盖输出文件
            "-i", video_path,
            "-c:v", "libx264",  # 使用H.264视频编码
            "-preset", "fast",  # 编码速度预设（fast是速度和质量的平衡）
            "-crf", "23",  # 质量参数（18-28，23是默认值）
            "-c:a", "aac",  # 使用AAC音频编码
            "-b:a", "128k",  # 音频比特率
            "-movflags", "+faststart",  # 优化MP4文件以便流式播放
            "-pix_fmt", "yuv420p",  # 确保像素格式兼容（Windows 兼容性）
            converted_path
        ], capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace')  # 5分钟超时

        if result.returncode == 0 and os.path.exists(converted_path) and os.path.getsize(converted_path) > 0:
            update_file_access_time(converted_path)
            logger.info(f"[视频转换] 视频转换成功: {converted_path}")
            # 触发清理检查（异步，不阻塞）
            try:
                cleanup_temp_files()
            except:
                pass
            return converted_path
        else:
            error_msg = result.stderr if result.stderr else "未知错误"
            logger.error(f"[视频转换] 视频转换失败: {error_msg}")
            # 转换失败时返回原文件路径（让浏览器尝试播放）
            logger.warning(f"[视频转换] 转换失败，返回原文件路径: {video_path}")
            return video_path

    except FileNotFoundError:
        logger.error(f"[视频转换] 未找到ffmpeg，无法转换视频")
        return video_path
    except subprocess.TimeoutExpired:
        logger.error(f"[视频转换] 视频转换超时")
        return video_path
    except Exception as e:
        logger.error(f"[视频转换] 视频转换异常: {e}")
        return video_path


def is_valid_video_file(file_path: str) -> bool:
    """
    检查文件是否为有效的视频文件
    在 Windows 上，从 macOS 复制的文件可能包含无效的资源分叉文件

    Args:
        file_path: 文件路径

    Returns:
        如果是有效视频文件返回 True，否则返回 False
    """
    # 获取文件名
    filename = os.path.basename(file_path)

    # 在 Windows 平台上，跳过 macOS 资源分叉文件（以 ._ 开头的隐藏文件）
    # 这些文件在 macOS 上是隐藏的，但在 Windows 上会显示出来
    if platform.system() == 'Windows' and filename.startswith('._'):
        logger.debug(f"[Windows兼容] 跳过 macOS 资源分叉文件: {filename}")
        return False

    # 检查文件大小（资源分叉文件通常很小，小于1KB）
    try:
        file_size = os.path.getsize(file_path)
        if file_size < 1024:  # 小于 1KB 的文件可能不是有效视频
            logger.debug(f"跳过过小的文件 ({file_size} bytes): {filename}")
            return False
    except OSError:
        return False

    return True


# 文件夹内容缓存
_folder_contents_cache = {}


def scan_video_files(folder_path: str) -> list:
    """
    扫描文件夹下的所有视频文件
    使用缓存优化性能
    """
    # 检查缓存
    with _cache_lock:
        if folder_path in _folder_contents_cache:
            cache_entry = _folder_contents_cache[folder_path]
            # 检查文件夹是否发生变化（通过修改时间）
            try:
                if os.path.getmtime(folder_path) <= cache_entry['mtime']:
                    logger.debug(f"[扫描视频] 使用缓存: {folder_path}")
                    return cache_entry['videos']
            except:
                pass

    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v'}
    videos = []

    try:
        if not os.path.exists(folder_path):
            raise ValueError(f"文件夹不存在: {folder_path}")

        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_ext = os.path.splitext(file)[1].lower()

                if file_ext in video_extensions:
                    # 验证是否为有效的视频文件（Windows 兼容性检查）
                    if not is_valid_video_file(file_path):
                        continue
                    videos.append({
                        'name': file,
                        'path': file_path
                    })

        logger.info(f"扫描到 {len(videos)} 个视频文件")

        # 更新缓存
        with _cache_lock:
            _folder_contents_cache[folder_path] = {
                'videos': videos,
                'mtime': os.path.getmtime(folder_path) if os.path.exists(folder_path) else 0
            }
            # 限制缓存大小
            if len(_folder_contents_cache) > 100:
                _folder_contents_cache.clear()

        return videos

    except Exception as e:
        logger.error(f"扫描视频文件失败: {e}")
        raise


# 路径解析缓存
_path_resolution_cache = {}


def resolve_folder_path(annotation_folder: str, current_folder_path: str = None) -> str:
    """
    解析标注文件中的文件夹路径，支持绝对路径和相对路径的回退
    使用缓存优化性能

    策略：
    1. 先尝试使用绝对路径
    2. 如果绝对路径不存在，从绝对路径中提取相对路径部分
    3. 在项目 data 目录下查找相对路径
    4. 支持 Windows 和 Mac/Linux 的路径自动转换
    """
    if not annotation_folder:
        return current_folder_path or ''

    # 使用缓存
    cache_key = f"{annotation_folder}|{current_folder_path}"
    with _cache_lock:
        if cache_key in _path_resolution_cache:
            return _path_resolution_cache[cache_key]

    # 标准化路径分隔符（统一使用当前系统的分隔符）
    normalized_path = annotation_folder.replace(
        '\\', os.sep).replace('/', os.sep)

    def _resolve():
        # 检测是否为 Windows 绝对路径（以驱动器字母开头，如 C:\ 或 C:/）
        is_windows_abs = False
        if len(normalized_path) >= 2 and normalized_path[1] == ':':
            is_windows_abs = True

        # 检测是否为 Unix/Mac 绝对路径
        is_unix_abs = os.path.isabs(normalized_path)

        # 策略1: 先尝试直接使用绝对路径
        if is_unix_abs or is_windows_abs:
            if is_unix_abs and os.path.exists(normalized_path):
                logger.debug(f"[路径解析] 使用绝对路径: {normalized_path}")
                return normalized_path
            logger.debug(f"[路径解析] 绝对路径不存在: {normalized_path}")

        # 策略2: 如果是绝对路径但不存在，尝试提取相对路径部分
        if is_unix_abs or is_windows_abs:
            # 从绝对路径中提取最后几级目录作为相对路径
            path_str = normalized_path.replace(
                '\\', os.sep).replace('/', os.sep)
            path_parts = [part for part in path_str.split(os.sep) if part]

            # 尝试从后往前提取路径部分，最多提取5级目录
            for i in range(1, min(len(path_parts) + 1, 6)):
                relative_parts = path_parts[-i:]
                relative_path = os.path.join(*relative_parts)

                # 在项目 data 目录下查找
                data_dir = os.path.join(PROJECT_ROOT, 'data')
                candidate_path = os.path.join(data_dir, relative_path)

                if os.path.exists(candidate_path):
                    logger.info(
                        f"[路径解析] 找到相对路径: {candidate_path} (从 {normalized_path} 提取，相对路径: {relative_path})")
                    return candidate_path

                # 也在当前文件夹的父目录中查找
                if current_folder_path:
                    parent_dir = os.path.dirname(current_folder_path)
                    candidate_path = os.path.join(parent_dir, relative_path)
                    if os.path.exists(candidate_path):
                        logger.info(
                            f"[路径解析] 在当前文件夹父目录找到: {candidate_path} (相对路径: {relative_path})")
                        return candidate_path

            logger.warning(f"[路径解析] 无法解析路径: {normalized_path}，使用原始路径")
            return normalized_path

        # 策略3: 如果已经是相对路径，尝试在 data 目录下查找
        if not os.path.isabs(normalized_path):
            data_dir = os.path.join(PROJECT_ROOT, 'data')
            candidate_path = os.path.join(data_dir, normalized_path)
            if os.path.exists(candidate_path):
                logger.info(f"[路径解析] 在 data 目录找到相对路径: {candidate_path}")
                return candidate_path

            # 也在当前文件夹的父目录中查找
            if current_folder_path:
                parent_dir = os.path.dirname(current_folder_path)
                candidate_path = os.path.join(parent_dir, normalized_path)
                if os.path.exists(candidate_path):
                    logger.info(f"[路径解析] 在当前文件夹父目录找到相对路径: {candidate_path}")
                    return candidate_path

        # 策略4: 如果都找不到，尝试直接使用（可能是相对于当前工作目录）
        if not os.path.isabs(normalized_path):
            data_dir = os.path.join(PROJECT_ROOT, 'data')
            candidate_path = os.path.join(data_dir, normalized_path)
            if os.path.exists(candidate_path):
                logger.info(f"[路径解析] 在项目data目录找到路径: {candidate_path}")
                return candidate_path

        if os.path.exists(normalized_path):
            logger.info(f"[路径解析] 使用直接路径: {normalized_path}")
            return normalized_path

        logger.warning(f"[路径解析] 所有策略都失败，返回原始路径: {normalized_path}")
        return normalized_path

    resolved_path = _resolve()
    with _cache_lock:
        _path_resolution_cache[cache_key] = resolved_path
        # 限制缓存大小
        if len(_path_resolution_cache) > 2000:
            _path_resolution_cache.clear()

    return resolved_path


def get_annotations_file_path(folder_path: str) -> str:
    """
    获取标注文件的路径（保存在选择的文件夹中）

    Args:
        folder_path: 文件夹路径

    Returns:
        标注文件路径
    """
    return os.path.join(folder_path, 'annotations.json')


@app.route('/')
def index():
    """返回简易标注工具页面"""
    html_file = os.path.join(PROJECT_ROOT, 'web_html',
                             'simple_annotation_tool.html')
    return send_file(html_file)


@app.route('/api/simple_annotation/scan_videos', methods=['POST'])
def scan_videos():
    """扫描文件夹下的所有视频文件"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()

        if not folder_path:
            return jsonify({'error': '文件夹路径不能为空'}), 400

        logger.info(f"[标注交互] 扫描视频文件夹: {folder_path}")

        # 解析文件夹路径（支持绝对路径到相对路径的回退）
        resolved_folder_path = resolve_folder_path(folder_path, folder_path)
        if not os.path.exists(resolved_folder_path):
            logger.warning(
                f"[标注交互] 解析后的文件夹路径不存在: {resolved_folder_path}，尝试使用原始路径: {folder_path}")
            resolved_folder_path = folder_path

        logger.info(
            f"[标注交互] 使用文件夹路径: {resolved_folder_path} (原始: {folder_path})")

        videos = scan_video_files(resolved_folder_path)

        logger.info(f"[标注交互] 扫描完成，找到 {len(videos)} 个视频文件")
        for idx, video in enumerate(videos):
            logger.info(f"  视频 {idx + 1}: {video['name']} ({video['path']})")

        return jsonify({
            'success': True,
            'videos': videos
        })

    except Exception as e:
        logger.error(f"扫描视频失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/get_video_info', methods=['POST'])
def get_video_info():
    """获取视频信息和最后一帧"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()
        video_name = data.get('video_name', '').strip()

        if not folder_path or not video_name:
            return jsonify({'error': '参数不完整'}), 400

        logger.info(f"[标注交互] 获取视频信息: {video_name}")

        # 解析文件夹路径（支持绝对路径到相对路径的回退）
        resolved_folder_path = resolve_folder_path(folder_path, folder_path)
        if not os.path.exists(resolved_folder_path):
            logger.warning(
                f"[标注交互] 解析后的文件夹路径不存在: {resolved_folder_path}，尝试使用原始路径: {folder_path}")
            resolved_folder_path = folder_path

        logger.info(
            f"[标注交互] 使用文件夹路径: {resolved_folder_path} (原始: {folder_path})")

        # 查找视频文件 (优化：使用 scan_video_files 的缓存)
        videos = scan_video_files(resolved_folder_path)
        video_path = next((v['path']
                          for v in videos if v['name'] == video_name), None)

        if not video_path:
            logger.error(
                f"[标注交互] 视频文件不存在: {video_name}，在 {resolved_folder_path} 中未找到")
            return jsonify({
                'error': f'视频文件不存在: {video_name}',
                'searched_folder': resolved_folder_path
            }), 404

        if not os.path.exists(video_path):
            logger.error(f"[标注交互] 视频文件路径无效: {video_path}")
            return jsonify({
                'error': f'视频文件路径无效: {video_path}'
            }), 404

        logger.info(f"[标注交互] 找到视频文件: {video_path}")

        # 转换视频格式为浏览器兼容的MP4格式
        # Windows下MOV格式需要转换，其他情况按需转换
        logger.info(f"[标注交互] 检查视频格式兼容性...")
        file_ext = os.path.splitext(video_path)[1].lower()
        needs_conversion = False

        if platform.system() == 'Windows' and file_ext in {'.mov', '.MOV'}:
            needs_conversion = True
            logger.info(f"[标注交互] [Windows兼容] MOV格式需要转换")

        try:
            converted_video_path = convert_video_for_browser(
                video_path, force_convert=needs_conversion)
            logger.info(f"[标注交互] 视频格式处理完成: {converted_video_path}")
        except Exception as e:
            logger.warning(f"[标注交互] 视频格式转换失败，使用原文件: {e}")
            converted_video_path = video_path

        # 提取最后一帧（使用原始视频文件，因为转换后的视频可能还在处理中）
        logger.info(f"[标注交互] 开始提取最后一帧...")
        try:
            last_frame_path = extract_last_frame(video_path)
            logger.info(f"[标注交互] 最后一帧提取完成: {last_frame_path}")
        except Exception as e:
            logger.error(f"[标注交互] 提取最后一帧失败: {e}")
            return jsonify({
                'error': f'提取视频最后一帧失败: {str(e)}',
                'video_path': video_path
            }), 500

        # 生成URL路径（需要对路径进行URL编码）
        import urllib.parse
        # 如果视频被转换了，使用转换后的视频路径
        if converted_video_path != video_path:
            video_dir = os.path.dirname(converted_video_path)
            video_filename = os.path.basename(converted_video_path)
        else:
            video_dir = os.path.dirname(video_path)
            video_filename = os.path.basename(video_path)

        video_url = f'/api/simple_annotation/video/{urllib.parse.quote(video_filename)}?path={urllib.parse.quote(video_dir)}'
        last_frame_url = f'/api/simple_annotation/image/{urllib.parse.quote(os.path.basename(last_frame_path))}'

        # 检查是否存在已有的标注数据
        annotation = None
        annotations_file = get_annotations_file_path(resolved_folder_path)
        if os.path.exists(annotations_file):
            try:
                logger.info(f"[标注交互] 发现标注文件，尝试读取: {annotations_file}")
                with open(annotations_file, 'r', encoding='utf-8') as f:
                    annotations_data = json.load(f)

                # 转换为字典格式，key为 "folder|video_name"
                # 使用解析后的路径作为 key，同时保存原始标注数据
                annotations_dict = {}
                if isinstance(annotations_data, list):
                    for ann in annotations_data:
                        ann_folder = ann.get('folder', resolved_folder_path)
                        # 解析标注中的文件夹路径
                        resolved_folder = resolve_folder_path(
                            ann_folder, resolved_folder_path)
                        # 标准化路径以便比较（统一使用绝对路径和标准化分隔符）
                        normalized_resolved = os.path.normpath(os.path.abspath(
                            resolved_folder)) if os.path.exists(resolved_folder) else resolved_folder
                        key = f"{normalized_resolved}|{ann.get('video_name', '')}"
                        annotations_dict[key] = ann
                elif isinstance(annotations_data, dict):
                    annotations_dict = annotations_data

                # 解析并标准化当前文件夹路径
                normalized_current_folder = os.path.normpath(os.path.abspath(
                    resolved_folder_path)) if os.path.exists(resolved_folder_path) else resolved_folder_path

                # 查找当前视频的标注（使用标准化后的路径）
                annotation_key = f"{normalized_current_folder}|{video_name}"
                annotation = annotations_dict.get(annotation_key)

                # 如果直接匹配失败，尝试遍历所有标注进行路径匹配
                if not annotation:
                    for key, ann in annotations_dict.items():
                        ann_video_name = ann.get('video_name', '')
                        if ann_video_name == video_name:
                            # 提取 key 中的文件夹路径部分
                            key_folder = key.split(
                                '|')[0] if '|' in key else ''
                            # 比较标准化后的路径
                            if os.path.normpath(key_folder) == normalized_current_folder:
                                annotation = ann
                                logger.info(f"[标注交互] 通过路径匹配找到标注: {key}")
                                break

                    # 如果还是找不到，尝试使用原始 folder_path 和 resolved_folder_path 匹配（兼容旧数据）
                    if not annotation:
                        annotation_key_original = f"{folder_path}|{video_name}"
                        annotation = annotations_dict.get(
                            annotation_key_original)
                        if not annotation:
                            annotation_key_resolved = f"{resolved_folder_path}|{video_name}"
                            annotation = annotations_dict.get(
                                annotation_key_resolved)

                if annotation:
                    logger.info(f"[标注交互] 找到已有标注: {annotation_key}")
                    # 兼容旧的objects字段和新的object_space字段
                    object_space_list = annotation.get(
                        'object_space', annotation.get('objects', []))
                    logger.info(
                        f"[标注交互] 标注包含 {len(object_space_list)} 个对象/放置空间")
                else:
                    logger.info(f"[标注交互] 未找到该视频的标注数据")

            except Exception as e:
                logger.warning(f"[标注交互] 读取标注文件失败: {e}")
                annotation = None

        logger.info(f"[标注交互] 视频信息获取成功")

        response_data = {
            'success': True,
            'video_url': video_url,
            'last_frame_url': last_frame_url,
            'video_path': video_path
        }

        # 如果有标注数据，添加到响应中
        if annotation:
            response_data['annotation'] = annotation

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"获取视频信息失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/video/<filename>')
def serve_video(filename):
    """提供视频文件服务"""
    try:
        import urllib.parse

        folder_path = urllib.parse.unquote(request.args.get('path', ''))
        filename = urllib.parse.unquote(filename)
        force_convert = request.args.get('convert', '').lower() == 'true'

        if not folder_path:
            return jsonify({'error': '缺少路径参数'}), 400

        # 解析文件夹路径（支持绝对路径到相对路径的回退）
        resolved_folder_path = resolve_folder_path(folder_path, folder_path)

        # 确保路径是绝对路径，避免相对路径导致的路径拼接错误
        if not os.path.isabs(resolved_folder_path):
            # 如果是相对路径，优先在项目data目录下查找
            data_dir = os.path.join(PROJECT_ROOT, 'data')

            # 尝试1: 直接拼接resolved_folder_path
            candidate_path = os.path.join(data_dir, resolved_folder_path)
            if os.path.exists(candidate_path):
                logger.info(f"[视频服务] 将相对路径转换为绝对路径: {candidate_path}")
                resolved_folder_path = candidate_path
            else:
                # 尝试2: 使用原始folder_path拼接
                candidate_path = os.path.join(data_dir, folder_path)
                if os.path.exists(candidate_path):
                    logger.info(f"[视频服务] 使用原始路径在data目录找到: {candidate_path}")
                    resolved_folder_path = candidate_path
                else:
                    # 尝试3: 如果resolved_folder_path以data/开头，去掉data/前缀后拼接
                    if resolved_folder_path.startswith('data/'):
                        # 去掉 'data/' 前缀
                        relative_path = resolved_folder_path[5:]
                        candidate_path = os.path.join(data_dir, relative_path)
                        if os.path.exists(candidate_path):
                            logger.info(
                                f"[视频服务] 去掉data/前缀后找到: {candidate_path}")
                            resolved_folder_path = candidate_path
                    else:
                        logger.warning(
                            f"[视频服务] 无法解析相对路径: {resolved_folder_path}")

        # 如果解析后的路径仍然不存在，再次尝试在项目data目录下查找
        if not os.path.exists(resolved_folder_path):
            logger.warning(
                f"[视频服务] 解析后的文件夹路径不存在: {resolved_folder_path}，尝试在项目data目录下查找")
            data_dir = os.path.join(PROJECT_ROOT, 'data')
            if not os.path.isabs(folder_path):
                candidate_path = os.path.join(data_dir, folder_path)
                if os.path.exists(candidate_path):
                    logger.info(f"[视频服务] 在项目data目录找到路径: {candidate_path}")
                    resolved_folder_path = candidate_path

        video_path = os.path.join(resolved_folder_path, filename)

        if not os.path.exists(video_path):
            # 如果直接拼接的路径不存在，尝试在项目data目录下查找
            if not os.path.isabs(folder_path):
                data_dir = os.path.join(PROJECT_ROOT, 'data')
                candidate_video_path = os.path.join(
                    data_dir, folder_path, filename)
                if os.path.exists(candidate_video_path):
                    logger.info(
                        f"[视频服务] 在项目data目录找到视频文件: {candidate_video_path}")
                    video_path = candidate_video_path
                else:
                    logger.error(
                        f"[视频服务] 视频文件不存在: {video_path} (原始路径: {folder_path}, 文件名: {filename}, 尝试路径: {candidate_video_path})")
                    return jsonify({'error': '视频文件不存在'}), 404
            else:
                logger.error(
                    f"[视频服务] 视频文件不存在: {video_path} (原始路径: {folder_path}, 文件名: {filename})")
                return jsonify({'error': '视频文件不存在'}), 404

        # Windows 兼容性处理：检查是否需要转换视频格式
        # 特别处理MOV格式：Windows下通常需要转换
        file_ext = os.path.splitext(video_path)[1].lower()
        needs_conversion = False

        if platform.system() == 'Windows':
            # Windows下MOV格式通常需要转换
            if file_ext in {'.mov', '.MOV'}:
                needs_conversion = True
                logger.info(f"[视频服务] [Windows兼容] MOV格式需要转换: {video_path}")
            elif force_convert or not check_video_codec_compatible(video_path):
                needs_conversion = True
                logger.info(f"[视频服务] [Windows兼容] 视频编码可能不兼容，尝试转换: {video_path}")
        elif force_convert:
            needs_conversion = True

        if needs_conversion:
            converted_path = convert_video_for_browser(
                video_path, force_convert=True)
            if converted_path != video_path and os.path.exists(converted_path):
                update_file_access_time(converted_path)
                logger.info(
                    f"[视频服务] [Windows兼容] 使用转换后的视频: {converted_path}")
                return send_file(converted_path, mimetype='video/mp4')

        update_file_access_time(video_path)
        logger.debug(f"[视频服务] 提供视频文件: {video_path}")
        return send_file(video_path)

    except Exception as e:
        logger.error(f"提供视频文件失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/image/<filename>')
def serve_image(filename):
    """提供图像文件服务"""
    try:
        import urllib.parse
        filename = urllib.parse.unquote(filename)
        image_path = os.path.join(TEMP_DIR, filename)

        if not os.path.exists(image_path):
            return jsonify({'error': '图像文件不存在'}), 404

        update_file_access_time(image_path)
        return send_file(image_path)

    except Exception as e:
        logger.error(f"提供图像文件失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/asr_recognition', methods=['POST'])
def asr_recognition():
    """对视频进行ASR语音识别"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()
        video_name = data.get('video_name', '').strip()

        if not folder_path or not video_name:
            return jsonify({'error': '参数不完整'}), 400

        logger.info(f"[ASR识别] 开始处理视频: {video_name}")

        # 解析文件夹路径（支持绝对路径到相对路径的回退）
        resolved_folder_path = resolve_folder_path(folder_path, folder_path)
        if not os.path.exists(resolved_folder_path):
            logger.warning(
                f"[ASR识别] 解析后的文件夹路径不存在: {resolved_folder_path}，尝试使用原始路径: {folder_path}")
            resolved_folder_path = folder_path

        logger.info(
            f"[ASR识别] 使用文件夹路径: {resolved_folder_path} (原始: {folder_path})")

        # 查找视频文件 (优化：使用 scan_video_files 的缓存)
        videos = scan_video_files(resolved_folder_path)
        video_path = next((v['path']
                          for v in videos if v['name'] == video_name), None)

        if not video_path or not os.path.exists(video_path):
            logger.error(
                f"[ASR识别] 视频文件不存在: {video_name}，在 {resolved_folder_path} 中未找到")
            return jsonify({'error': '视频文件不存在'}), 404

        logger.info(f"[ASR识别] 找到视频文件: {video_path}")

        # 提取音频（使用hash作为缓存键，避免重复提取）
        logger.info(f"[ASR识别] 开始提取音频...")
        file_hash = get_file_hash(video_path)
        video_name = os.path.splitext(video_name)[0]
        audio_filename = f"{video_name}_{file_hash[:8]}.mp3"
        audio_path = os.path.join(TEMP_DIR, audio_filename)

        # 如果音频文件已存在，直接使用
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            update_file_access_time(audio_path)
            logger.info(f"[ASR识别] 使用已存在的音频文件: {audio_path}")
        else:
            # 提取音频
            audio_path_extracted, _ = extract_audio_and_video(
                video_path,
                output_dir=TEMP_DIR,
                audio_filename=audio_filename
            )

            if audio_path_extracted:
                audio_path = audio_path_extracted
                update_file_access_time(audio_path)
                logger.info(f"[ASR识别] 音频提取成功: {audio_path}")
            else:
                logger.error(f"[ASR识别] 音频提取失败")
                return jsonify({'error': '音频提取失败'}), 500

        if not audio_path or not os.path.exists(audio_path):
            logger.error(f"[ASR识别] 音频文件不存在")
            return jsonify({'error': '音频文件不存在'}), 500

        # 进行ASR识别
        logger.info(f"[ASR识别] 开始ASR识别...")
        success, words_list, error_msg = audio_to_words_with_timestamps(
            audio_path,
            api_key=DASHSCOPE_API_KEY
        )

        if not success:
            logger.error(f"[ASR识别] ASR识别失败: {error_msg}")
            return jsonify({
                'success': False,
                'error': error_msg or 'ASR识别失败'
            }), 500

        # 需要重新调用API获取完整的句子信息
        # 因为audio_to_words_with_timestamps只返回了第一句的词汇列表
        # 我们需要重新调用API来获取所有句子的信息
        try:
            from pipeline.audio_processor import convert_to_mono
            import dashscope
            from dashscope.audio.asr import Recognition
            from http import HTTPStatus
            from config.settings import ASR_MODEL, AUDIO_FORMAT, AUDIO_SAMPLE_RATE

            # 使用已经提取的音频路径（避免重复提取视频）
            audio_path_for_sentence = audio_path

            # 设置API密钥
            dashscope.api_key = DASHSCOPE_API_KEY

            # 转换音频为单声道
            mono_audio_file = convert_to_mono(audio_path_for_sentence)
            if not mono_audio_file:
                raise ValueError("无法转换音频格式")

            # 调用API获取所有句子信息
            recognition = Recognition(
                model=ASR_MODEL,
                format=AUDIO_FORMAT,
                sample_rate=AUDIO_SAMPLE_RATE,
                callback=None
            )

            result = recognition.call(mono_audio_file)
            sentences_list = []

            if result.status_code == HTTPStatus.OK:
                sentence = result.get_sentence()
                if sentence and len(sentence) > 0:
                    # 遍历所有句子
                    for sent in sentence:
                        if isinstance(sent, dict):
                            # 提取句子文本和时间信息
                            sent_text = sent.get('text', '')
                            if sent_text:
                                sentences_list.append({
                                    'text': sent_text,
                                    'begin_time': sent.get('begin_time', 0),
                                    'end_time': sent.get('end_time', 0)
                                })

            # 清理临时文件
            if mono_audio_file and os.path.exists(mono_audio_file):
                try:
                    os.remove(mono_audio_file)
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")

            # 构建完整文本（所有句子合并）
            recognition_text = ''
            if sentences_list:
                recognition_text = ' '.join(
                    [sent.get('text', '') for sent in sentences_list])
            elif words_list:
                # 如果没有句子信息，使用词汇列表构建文本
                recognition_text = ' '.join(
                    [word.get('text', '') for word in words_list])

            # 如果没有获取到句子信息，至少构建一个句子
            if not sentences_list and words_list:
                sentences_list = [{
                    'text': recognition_text,
                    'begin_time': words_list[0].get('begin_time', 0) if words_list else 0,
                    'end_time': words_list[-1].get('end_time', 0) if words_list else 0
                }]

            logger.info(
                f"[ASR识别] ASR识别成功，识别到 {len(sentences_list)} 个句子，识别文本: {recognition_text}")

            return jsonify({
                'success': True,
                'text': recognition_text,  # 完整文本（所有句子合并，用于前端显示）
                'sentences': sentences_list,  # 多个句子级别数据
                'words': words_list  # 词汇级别数据（包含时间戳）
            })

        except Exception as e:
            logger.warning(f"[ASR识别] 获取句子信息失败，使用词汇列表构建结果: {e}")
            import traceback
            logger.warning(traceback.format_exc())
            # 如果获取句子信息失败，使用词汇列表构建结果（兼容旧逻辑）
            recognition_text = ''
            if words_list:
                recognition_text = ' '.join(
                    [word.get('text', '') for word in words_list])

            sentence_data = {
                'text': recognition_text,
                'begin_time': words_list[0].get('begin_time', 0) if words_list else 0,
                'end_time': words_list[-1].get('end_time', 0) if words_list else 0
            }

            logger.info(f"[ASR识别] ASR识别成功（使用词汇列表），识别文本: {recognition_text}")

            return jsonify({
                'success': True,
                'text': recognition_text,  # 完整句子文本（用于前端显示）
                'sentences': [sentence_data],  # 单个句子（兼容格式）
                'words': words_list  # 词汇级别数据（包含时间戳）
            })

    except Exception as e:
        logger.error(f"ASR识别失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/sam_segment', methods=['POST'])
def sam_segment():
    """
    调用 SAM3 API 对图像进行分割

    请求参数:
        - folder_path: 文件夹路径
        - video_name: 视频名称
        - points: [[x, y], ...] 归一化坐标 (0-1)
        - point_labels: [1, 1, ...] 1=前景点, 0=背景点（可选，默认全为1）

    返回:
        - success: 是否成功
        - mask_image_url: mask 叠加图像的 URL
        - results: SAM3 返回的结果数量
    """
    import urllib.parse

    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()
        video_name = data.get('video_name', '').strip()
        points = data.get('points', [])  # [[x, y], ...] 归一化坐标 (0-1)
        point_labels = data.get('point_labels', None)  # [1, 1, ...] 可选

        if not folder_path or not video_name:
            return jsonify({'error': '参数不完整: 需要 folder_path 和 video_name'}), 400

        if not points or len(points) == 0:
            return jsonify({'error': '参数不完整: 需要至少一个点坐标'}), 400

        # 如果没有提供 point_labels，默认全为前景点 (1)
        if point_labels is None:
            point_labels = [1] * len(points)

        logger.info(f"[SAM3分割] 开始处理: video={video_name}, points={points}")

        # 解析文件夹路径
        resolved_folder_path = resolve_folder_path(folder_path, folder_path)
        if not os.path.exists(resolved_folder_path):
            return jsonify({'error': f'文件夹不存在: {folder_path}'}), 404

        # 查找最后一帧图像
        video_basename = os.path.splitext(video_name)[0]
        last_frame_filename = f"{video_basename}_last_frame.jpg"
        last_frame_path = os.path.join(TEMP_DIR, last_frame_filename)

        if not os.path.exists(last_frame_path):
            # 如果没有最后一帧图像，需要从视频中提取
            # 查找视频文件 (优化：使用 scan_video_files 的缓存)
            videos = scan_video_files(resolved_folder_path)
            video_path = next((v['path']
                              for v in videos if v['name'] == video_name), None)

            if not video_path or not os.path.exists(video_path):
                return jsonify({'error': f'视频文件不存在: {video_name}'}), 404

            try:
                last_frame_path = extract_last_frame(video_path)
            except Exception as e:
                return jsonify({'error': f'提取最后一帧失败: {str(e)}'}), 500

        # 读取图像获取尺寸，将归一化坐标转换为像素坐标
        image = cv2.imread(last_frame_path)
        if image is None:
            return jsonify({'error': f'无法读取图像: {last_frame_path}'}), 500

        height, width = image.shape[:2]
        logger.info(f"[SAM3分割] 图像尺寸: {width} x {height}")

        # 使用 test.py 中的工具函数转换坐标
        pixel_points = normalize_to_pixel(points, width, height)
        logger.info(f"[SAM3分割] 像素坐标: {pixel_points}")

        # 生成输出路径
        mask_output_filename = f"{video_basename}_sam_mask.jpg"
        mask_output_path = os.path.join(TEMP_DIR, mask_output_filename)

        # 使用 test.py 中的 SAM3 工具函数进行分割
        result = sam3_segment_with_points(
            image_path=last_frame_path,
            points=pixel_points,
            point_labels=point_labels,
            output_path=mask_output_path,
            confidence_threshold=0.3
        )

        if not result.get('success'):
            error_msg = result.get('error', '未知错误')
            logger.error(f"[SAM3分割] 分割失败: {error_msg}")
            return jsonify({'error': error_msg}), 500

        # 生成 URL
        mask_image_url = f'/api/simple_annotation/image/{urllib.parse.quote(mask_output_filename)}'

        logger.info(f"[SAM3分割] Mask 图像已保存: {mask_output_path}")

        # 提取第一个结果的完整 mask 数据（如果存在）
        mask_data = None
        if result.get('results') and len(result['results']) > 0:
            first_result = result['results'][0]
            mask_data = {
                'mask_base64': first_result.get('mask_base64'),
                'bbox': first_result.get('bbox'),
                'score': first_result.get('score', 0),
                'point_on_mask': True  # 因为已经筛选过了
            }

        response_data = {
            'success': True,
            'mask_image_url': mask_image_url,
            'results_count': result.get('results_count', 0),
            'message': result.get('message', '分割完成')
        }

        # 如果有 mask 数据，添加到响应中
        if mask_data:
            response_data['mask'] = mask_data

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"[SAM3分割] 处理失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/load_annotations', methods=['POST'])
def load_annotations():
    """加载标注数据"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()

        if not folder_path:
            return jsonify({'error': '文件夹路径不能为空'}), 400

        logger.info(f"[标注交互] 加载标注数据: {folder_path}")

        # 解析文件夹路径（支持绝对路径到相对路径的回退）
        resolved_folder_path = resolve_folder_path(folder_path, folder_path)
        if not os.path.exists(resolved_folder_path):
            logger.warning(
                f"[标注交互] 解析后的文件夹路径不存在: {resolved_folder_path}，尝试使用原始路径: {folder_path}")
            resolved_folder_path = folder_path

        annotations_file = get_annotations_file_path(resolved_folder_path)

        if not os.path.exists(annotations_file):
            logger.info(f"[标注交互] 标注文件不存在，返回空数据: {annotations_file}")
            return jsonify({
                'success': True,
                'annotations': {}
            })

        with open(annotations_file, 'r', encoding='utf-8') as f:
            annotations_data = json.load(f)

        # 转换为字典格式，key为 "folder|video_name"
        # 使用解析后的路径作为 key，以便匹配时能正确找到标注
        annotations_dict = {}
        if isinstance(annotations_data, list):
            for ann in annotations_data:
                ann_folder = ann.get('folder', resolved_folder_path)
                # 解析标注中的文件夹路径
                resolved_folder = resolve_folder_path(
                    ann_folder, resolved_folder_path)
                # 使用解析后的路径作为 key
                key = f"{resolved_folder}|{ann.get('video_name', '')}"
                annotations_dict[key] = ann
        elif isinstance(annotations_data, dict):
            # 如果是字典格式，也需要解析路径
            for key, ann in annotations_data.items():
                if isinstance(ann, dict):
                    ann_folder = ann.get('folder', resolved_folder_path)
                    resolved_folder = resolve_folder_path(
                        ann_folder, resolved_folder_path)
                    video_name = ann.get('video_name', '')
                    new_key = f"{resolved_folder}|{video_name}"
                    annotations_dict[new_key] = ann
                else:
                    annotations_dict[key] = ann

        logger.info(f"[标注交互] 成功加载标注数据: {len(annotations_dict)} 条")
        for key, ann in annotations_dict.items():
            # 兼容旧的objects字段和新的object_space字段
            object_space_list = ann.get('object_space', ann.get('objects', []))
            logger.info(f"  - {key}: {len(object_space_list)} 个对象/放置空间")

        return jsonify({
            'success': True,
            'annotations': annotations_dict
        })

    except Exception as e:
        logger.error(f"加载标注数据失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/save_annotations', methods=['POST'])
def save_annotations():
    """保存标注数据"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()
        annotations = data.get('annotations', {})

        if not folder_path:
            return jsonify({'error': '文件夹路径不能为空'}), 400

        annotations_file = get_annotations_file_path(folder_path)

        # 确保目录存在
        os.makedirs(os.path.dirname(annotations_file), exist_ok=True)

        # 转换为列表格式保存
        annotations_list = list(annotations.values())

        # 打印详细的标注交互信息
        logger.info("=" * 60)
        logger.info("[标注交互] 保存标注数据")
        logger.info(f"文件夹路径: {folder_path}")
        logger.info(f"标注文件: {annotations_file}")
        logger.info(f"标注数量: {len(annotations_list)}")

        for ann in annotations_list:
            logger.info(f"  - 视频: {ann.get('video_name', 'N/A')}")
            logger.info(f"    标注ID: {ann.get('id', 'N/A')}")
            logger.info(f"    任务模板: {ann.get('task_template', 'N/A')}")
            logger.info(f"    场景: {ann.get('scene', 'N/A')}")
            # 兼容旧的objects字段和新的object_space字段
            object_space_list = ann.get('object_space', ann.get('objects', []))
            logger.info(f"    对象/放置空间数量: {len(object_space_list)}")

            for idx, obj in enumerate(object_space_list):
                obj_type = obj.get('type', 'object')
                type_label = '放置空间' if obj_type == 'space' else '对象'
                logger.info(f"      {type_label} {idx + 1}:")
                logger.info(f"        名称: {obj.get('name', 'N/A')}")
                logger.info(f"        类型: {obj_type}")
                logger.info(f"        标注点数: {len(obj.get('points', []))}")
                for pidx, point in enumerate(obj.get('points', [])):
                    logger.info(
                        f"          点 {pidx + 1}: [{point[0]}, {point[1]}]")

        logger.info("=" * 60)

        # 保存到文件
        with open(annotations_file, 'w', encoding='utf-8') as f:
            json.dump(annotations_list, f, ensure_ascii=False, indent=2)

        logger.info(f"成功保存标注数据: {annotations_file}")

        return jsonify({
            'success': True,
            'message': '标注保存成功',
            'file': annotations_file
        })

    except Exception as e:
        logger.error(f"保存标注数据失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '页面不存在'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': '服务器内部错误'}), 500


# 定期清理任务（在后台线程中运行）
_last_cleanup_time = 0


def periodic_cleanup():
    """定期清理临时文件"""
    global _last_cleanup_time
    current_time = time.time()
    if current_time - _last_cleanup_time > CACHE_CLEANUP_INTERVAL:
        try:
            cleanup_temp_files()
            _last_cleanup_time = current_time
        except Exception as e:
            logger.warning(f"定期清理失败: {e}")


@app.before_request
def before_request():
    """在每个请求前检查是否需要清理缓存"""
    periodic_cleanup()


@app.route('/api/simple_annotation/cleanup_cache', methods=['POST'])
def cleanup_cache():
    """手动触发缓存清理"""
    try:
        deleted_count, deleted_size = cleanup_temp_files()
        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'deleted_size_mb': round(deleted_size / 1024 / 1024, 2)
        })
    except Exception as e:
        logger.error(f"手动清理缓存失败: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("🚀 启动简易标注工具服务器...")
    print("📋 访问地址: http://localhost:5002")
    print(f"📦 缓存配置: 最大 {CACHE_MAX_SIZE_MB}MB, 保留 {CACHE_MAX_AGE_HOURS} 小时")
    print("=" * 50)

    app.run(host='0.0.0.0', port=5001, debug=True)
