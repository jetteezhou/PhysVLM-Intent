#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量补充 mask 字段脚本

遍历 data 目录下的所有 annotations.json 文件，
对于没有 mask 字段的标注对象，自动调用 SAM3 生成 mask 并保存。

使用方法 (CMD 终端):
    conda activate data_check
    cd E:\PhysVLM-Intent
    python tools/annotation/add_masks_to_annotations.py
"""

import os
import sys
import json
import base64
import cv2
import numpy as np
import concurrent.futures
import threading
import time
from pathlib import Path
import requests
import subprocess
import tempfile

# 添加项目根目录到 path
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

SAM3_API_URL = "https://algo-pre.roboticsx.tencent.com/v1/models/sam3"


# 导入 SAM3 工具函数

# 配置
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
TEMP_DIR = os.path.join(PROJECT_ROOT, 'temp')
MAX_WORKERS = 5  # 并发线程数


def extract_last_frame(video_path):
    """
    从视频中提取最后一帧
    优先使用ffmpeg，如果失败则回退到OpenCV
    对于OpenCV方法，如果无法读取最后一帧，会尝试读取倒数几帧
    """
    # 方法1: 尝试使用ffmpeg提取最后一帧（更可靠）
    try:
        # 首先获取视频时长
        probe_result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ], capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace')

        if probe_result.returncode == 0:
            try:
                duration = float(probe_result.stdout.strip())

                # 创建临时文件
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                    temp_path = tmp_file.name

                try:
                    # 方法1: 从倒数0.5秒开始提取
                    start_time = max(0, duration - 0.5)
                    extract_result = subprocess.run([
                        "ffmpeg", "-y",
                        "-ss", str(start_time),
                        "-i", video_path,
                        "-vframes", "1",
                        "-q:v", "2",
                        temp_path
                    ], capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')

                    if extract_result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                        # 读取提取的帧
                        frame = cv2.imread(temp_path)
                        if frame is not None:
                            os.unlink(temp_path)  # 删除临时文件
                            return frame

                    # 方法2: 尝试使用-sseof参数（从文件末尾开始）
                    extract_result2 = subprocess.run([
                        "ffmpeg", "-y",
                        "-sseof", "-0.5",
                        "-i", video_path,
                        "-vframes", "1",
                        "-q:v", "2",
                        temp_path
                    ], capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')

                    if extract_result2.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                        frame = cv2.imread(temp_path)
                        if frame is not None:
                            os.unlink(temp_path)
                            return frame
                finally:
                    # 确保临时文件被清理
                    if os.path.exists(temp_path):
                        try:
                            os.unlink(temp_path)
                        except:
                            pass

            except (ValueError, subprocess.TimeoutExpired):
                pass
    except FileNotFoundError:
        # ffmpeg不可用，继续使用OpenCV
        pass
    except Exception:
        # ffmpeg失败，继续使用OpenCV
        pass

    # 方法2: 回退到OpenCV方法
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")

    # 获取总帧数
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        raise ValueError(f"视频帧数无效: {video_path}")

    # 尝试读取最后一帧，如果失败则尝试倒数几帧（最多尝试5帧）
    max_attempts = min(5, total_frames)
    for attempt in range(max_attempts):
        frame_index = total_frames - 1 - attempt
        if frame_index < 0:
            break

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()

        if ret and frame is not None:
            cap.release()
            return frame

    cap.release()
    raise ValueError(f"无法读取最后一帧: {video_path} (尝试了最后{max_attempts}帧)")


def get_video_frame_data(video_path):
    """
    获取视频最后一帧的 Base64 数据和尺寸

    Returns:
        dict: {'base64': str, 'width': int, 'height': int} or raise Exception
    """
    frame = extract_last_frame(video_path)
    height, width = frame.shape[:2]

    # 将图像转换为 base64
    _, buffer = cv2.imencode('.jpg', frame)
    base64_image = base64.b64encode(buffer).decode('utf-8')

    return {
        'base64': base64_image,
        'width': width,
        'height': height
    }


def convert_points_to_pixel(points, width, height):
    """
    智能转换点坐标格式为像素坐标 [x, y]

    支持两种输入格式：
    1. [y, x] 格式，范围 0-1000（前端保存的格式）
    2. [x, y] 像素坐标（可能是旧格式或手动编辑的格式）

    通过检测点的值范围自动判断格式：
    - 如果所有点的值都 <= 1000，认为是 [y, x] 格式 (0-1000)
    - 否则认为是 [x, y] 像素坐标
    """
    if not points:
        return []

    # 检测格式：检查所有点的值是否都在 0-1000 范围内
    max_val = max(max(p[0], p[1]) for p in points)
    is_normalized = max_val <= 1000

    pixel_points = []
    for p in points:
        if is_normalized:
            # 格式1: [y, x] 归一化坐标 (0-1000) -> 转换为像素坐标 [x, y]
            norm_y = p[0] / 1000.0
            norm_x = p[1] / 1000.0
            px = int(norm_x * width)
            py = int(norm_y * height)
        else:
            # 格式2: [x, y] 像素坐标，直接使用
            px = int(p[0])
            py = int(p[1])

        pixel_points.append([px, py])

    return pixel_points


def fetch_mask_from_api(base64_image, width, height, points, point_labels=None):
    """
    调用 SAM3 API 获取 Mask
    """
    try:
        # 使用智能转换函数将点坐标转换为像素坐标 [x, y]
        pixel_points = convert_points_to_pixel(points, width, height)

        if point_labels is None:
            point_labels = [1] * len(pixel_points)

        # 调用 SAM3 API
        payload = {
            "base64_image": base64_image,
            "points": pixel_points,
            "point_labels": point_labels,
            "confidence_threshold": 0.3
        }

        headers = {"Content-Type": "application/json"}
        response = requests.post(
            SAM3_API_URL, json=payload, headers=headers, timeout=30)

        if response.status_code != 200:
            return {'success': False, 'error': f"HTTP {response.status_code}: {response.text}"}

        result = response.json()
        results = result.get('results', [])

        if not results:
            return {'success': False, 'error': "未检测到结果 (No results found)"}

        # 筛选出包含标注点的 mask
        valid_results = []

        for res in results:
            mask_base64 = res.get('mask_base64')
            if not mask_base64:
                continue

            # 解码 mask
            mask_data = base64.b64decode(mask_base64)
            mask_array = np.frombuffer(mask_data, np.uint8)
            mask = cv2.imdecode(mask_array, cv2.IMREAD_GRAYSCALE)

            if mask is None:
                continue

            # 调整尺寸
            if mask.shape[:2] != (height, width):
                mask = cv2.resize(mask, (width, height))

            # 检查标注点是否在 mask 内 (阈值 128)
            # 要求至少有一个点在 mask 内，且所有有效点中至少有一半在 mask 内
            points_in_mask_count = 0
            total_valid_points = 0

            for px, py in pixel_points:
                if 0 <= px < width and 0 <= py < height:
                    total_valid_points += 1
                    if mask[py, px] > 128:
                        points_in_mask_count += 1

            # 要求至少有一个点在 mask 内，且所有有效点中至少有一半在 mask 内
            if points_in_mask_count > 0 and (total_valid_points == 0 or points_in_mask_count >= total_valid_points / 2):
                valid_results.append({
                    'result': res,
                    'points_in_mask': points_in_mask_count,
                    'total_points': total_valid_points
                })

        if not valid_results:
            return {'success': False, 'error': "没有 Mask 包含标注点 (No mask contains annotation points)"}

        # 优先选择包含最多点的 mask，如果相同则选择 score 最高的
        best_entry = max(valid_results, key=lambda x: (
            x['points_in_mask'],  # 优先：包含的点数量
            x['result'].get('score', 0)  # 其次：置信度
        ))
        best_result = best_entry['result']

        return {
            'success': True,
            'data': {
                'mask_base64': best_result.get('mask_base64'),
                'bbox': best_result.get('bbox'),
                'score': best_result.get('score', 0),
                'point_on_mask': True
            }
        }

    except Exception as e:
        return {'success': False, 'error': str(e)}


def process_object_task(obj, video_path, frame_data):
    """
    单个对象处理任务函数（用于多线程）
    """
    obj_name = obj.get('name', 'unknown')
    points = obj.get('points', [])

    if not points:
        return {'obj': obj, 'success': False, 'error': '没有标注点'}

    # 如果没有预先提取的帧数据，尝试提取
    if not frame_data:
        try:
            frame_data = get_video_frame_data(video_path)
        except Exception as e:
            return {'obj': obj, 'success': False, 'error': f'读取视频帧失败: {e}'}

    # 调用 API
    result = fetch_mask_from_api(
        frame_data['base64'],
        frame_data['width'],
        frame_data['height'],
        points
    )

    if result['success']:
        return {
            'obj': obj,
            'success': True,
            'data': result['data'],
            'video_path': video_path,
            'obj_name': obj_name
        }
    else:
        return {
            'obj': obj,
            'success': False,
            'error': result['error'],
            'video_path': video_path,
            'obj_name': obj_name
        }


def process_annotation_file(annotation_path):
    """
    处理单个 annotations.json 文件 (多线程版)
    """
    try:
        with open(annotation_path, 'r', encoding='utf-8') as f:
            annotations = json.load(f)
    except Exception as e:
        print(f"  无法读取文件: {e}")
        return (0, 0, 0, 0)

    folder_path = os.path.dirname(annotation_path)

    # 统计数据
    stats = {
        'total': 0,
        'has_mask': 0,
        'new': 0,
        'failed': 0
    }

    # 准备任务
    tasks = []
    video_frame_cache = {}  # 缓存视频帧数据，避免重复读取

    print(f"  正在分析任务...")

    # 使用 ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []

        for annotation in annotations:
            video_name = annotation.get('video_name', '')
            object_space = annotation.get('object_space', [])

            if not video_name or not object_space:
                continue

            video_path = os.path.join(folder_path, video_name)
            if not os.path.exists(video_path):
                print(f"  ⚠ 视频文件不存在: {video_name}")
                continue

            # 筛选需要处理的对象
            objects_to_process = []
            for obj in object_space:
                obj_type = obj.get('type', 'object')
                # 只处理 type="object"
                if obj_type != 'object':
                    continue

                stats['total'] += 1

                # if 'mask' in obj and obj['mask']:
                #     stats['has_mask'] += 1
                #     continue

                objects_to_process.append(obj)

            if not objects_to_process:
                continue

            # 只有当有对象需要处理时，才读取视频帧
            if video_path not in video_frame_cache:
                try:
                    video_frame_cache[video_path] = get_video_frame_data(
                        video_path)
                except Exception as e:
                    print(f"  ✗ 无法读取视频帧 {video_name}: {e}")
                    stats['failed'] += len(objects_to_process)
                    continue

            frame_data = video_frame_cache[video_path]

            # 提交任务
            for obj in objects_to_process:
                future = executor.submit(
                    process_object_task, obj, video_path, frame_data)
                futures.append(future)

        if not futures:
            print(f"  没有需要处理的对象。")
            return (stats['total'], stats['has_mask'], stats['new'], stats['failed'])

        print(f"  提交了 {len(futures)} 个任务，正在并发处理...")

        # 处理结果
        modified = False
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            result = future.result()
            obj = result['obj']
            obj_name = result.get('obj_name', 'unknown')

            if result['success']:
                mask_data = result['data']
                obj['mask'] = mask_data
                stats['new'] += 1
                modified = True

                status = "✓" if mask_data['point_on_mask'] else "⚠"
                print(
                    f"    [{i+1}/{len(futures)}] {status} {obj_name}: 成功 (Score: {mask_data['score']:.3f})")
            else:
                stats['failed'] += 1
                print(
                    f"    [{i+1}/{len(futures)}] ✗ {obj_name}: 失败 - {result['error']}")

    # 保存修改
    if modified:
        try:
            with open(annotation_path, 'w', encoding='utf-8') as f:
                json.dump(annotations, f, ensure_ascii=False, indent=2)
            print(f"  已保存更新到文件")
        except Exception as e:
            print(f"  保存文件失败: {e}")

    return (stats['total'], stats['has_mask'], stats['new'], stats['failed'])


def main():
    """主函数：遍历所有 annotations.json 文件"""
    print("=" * 60)
    print(f"批量补充 mask 字段 (多线程并发: {MAX_WORKERS})")
    print("=" * 60)
    print(f"数据目录: {DATA_DIR}")
    print()

    if not os.path.exists(DATA_DIR):
        print(f"错误: 数据目录不存在: {DATA_DIR}")
        return

    # 查找所有 annotations.json 文件
    annotation_files = []
    for root, dirs, files in os.walk(DATA_DIR):
        if 'annotations.json' in files:
            annotation_files.append(os.path.join(root, 'annotations.json'))

    print(f"找到 {len(annotation_files)} 个标注文件")
    print()

    total_all = 0
    has_mask_all = 0
    new_all = 0
    failed_all = 0

    for i, annotation_path in enumerate(annotation_files):
        rel_path = os.path.relpath(annotation_path, DATA_DIR)
        print(f"[{i+1}/{len(annotation_files)}] {rel_path}")

        total, has_mask, new, failed = process_annotation_file(annotation_path)

        total_all += total
        has_mask_all += has_mask
        new_all += new
        failed_all += failed

        print("-" * 40)
        # 简单的垃圾回收，防止内存占用过高（虽然 Python 会自动管理，但处理大量图像数据时手动清理是个好习惯）
        import gc
        gc.collect()

    print("=" * 60)
    print("汇总统计:")
    print(f"  总对象数: {total_all}")
    print(f"  已有 mask: {has_mask_all}")
    print(f"  新增 mask: {new_all}")
    print(f"  获取失败: {failed_all}")
    print("=" * 60)


if __name__ == "__main__":
    main()
