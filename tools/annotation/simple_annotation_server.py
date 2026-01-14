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

# 获取项目根目录绝对路径
PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, PROJECT_ROOT)

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
CACHE_MAX_SIZE_MB = 500
CACHE_MAX_AGE_HOURS = 24
CACHE_CLEANUP_INTERVAL = 3600

_cache_lock = Lock()
_file_access_times = OrderedDict()
_folder_contents_cache = {}
_path_resolution_cache = {}


def get_file_hash(file_path: str) -> str:
    """计算文件的MD5哈希值（用于缓存键）"""
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            chunk = f.read(1024 * 1024)
            hash_md5.update(chunk)
            stat = os.stat(file_path)
            hash_md5.update(str(stat.st_size).encode())
            hash_md5.update(str(int(stat.st_mtime)).encode())
        return hash_md5.hexdigest()
    except Exception as e:
        logger.warning(f"计算文件hash失败: {e}")
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
        if len(_file_access_times) > 1000:
            _file_access_times.popitem(last=False)


def cleanup_temp_files(max_age_hours: int = CACHE_MAX_AGE_HOURS, max_size_mb: int = CACHE_MAX_SIZE_MB):
    """清理过期或超额的临时文件"""
    try:
        temp_dirs = [TEMP_DIR]
        if platform.system() == 'Windows':
            temp_dirs.append(WINDOWS_TEMP_DIR)

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        max_size_bytes = max_size_mb * 1024 * 1024

        total_size = 0
        files_info = []

        for temp_dir in temp_dirs:
            if not os.path.exists(temp_dir):
                continue
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        stat = os.stat(file_path)
                        files_info.append({
                            'path': file_path,
                            'size': stat.st_size,
                            'age': current_time - stat.st_mtime,
                            'access_time': _file_access_times.get(file_path, stat.st_mtime)
                        })
                        total_size += stat.st_size
                    except:
                        continue

        # 按访问时间排序
        files_info.sort(key=lambda x: x['access_time'])

        deleted_count = 0
        deleted_size = 0

        # 1. 删除过期
        for info in files_info[:]:
            if info['age'] > max_age_seconds:
                try:
                    os.remove(info['path'])
                    deleted_count += 1
                    deleted_size += info['size']
                    total_size -= info['size']
                    files_info.remove(info)
                    _file_access_times.pop(info['path'], None)
                except:
                    pass

        # 2. LRU 删除超额部分
        while total_size > max_size_bytes and files_info:
            info = files_info.pop(0)
            try:
                os.remove(info['path'])
                deleted_count += 1
                deleted_size += info['size']
                total_size -= info['size']
                _file_access_times.pop(info['path'], None)
            except:
                pass

        if deleted_count > 0:
            logger.info(
                f"[缓存清理] 删除了 {deleted_count} 个文件，释放 {deleted_size / 1024 / 1024:.2f} MB")
        return deleted_count, deleted_size
    except Exception as e:
        logger.error(f"[缓存清理] 失败: {e}")
        return 0, 0


def normalize_path_for_key(path):
    """
    为字典 Key 标准化路径：统一斜杠、小写化（仅限 Windows）
    """
    if not path:
        return ""
    # 统一使用正斜杠
    p = os.path.abspath(path).replace('\\', '/')
    # Windows 路径不区分大小写，统一转为小写以防匹配失败
    if platform.system() == 'Windows':
        p = p.lower()
    return os.path.normpath(p)


def resolve_folder_path(annotation_folder: str, current_folder_path: str = None) -> str:
    """
    智能解析文件夹路径，解决跨系统不兼容问题。
    """
    if not annotation_folder:
        return current_folder_path or ''

    # 标准化输入
    clean = annotation_folder.replace('\\', '/').strip()
    if clean.startswith('./'):
        clean = clean[2:]
    norm_in = os.path.normpath(clean)

    cache_key = f"{norm_in}|{current_folder_path}"
    with _cache_lock:
        if cache_key in _path_resolution_cache:
            return _path_resolution_cache[cache_key]

    def _do_resolve():
        data_root = os.path.abspath(os.path.join(PROJECT_ROOT, 'data'))
        candidates = []

        # A. 提取相对路径部分
        parts = norm_in.split(os.sep)
        if 'data' in parts:
            rel = os.path.join(*parts[parts.index('data')+1:])
            candidates.append(os.path.join(data_root, rel))

        # B. 直接作为相对路径
        candidates.append(os.path.join(data_root, norm_in))

        # C. 绝对路径尝试
        if os.path.isabs(norm_in) or (len(norm_in) >= 2 and norm_in[1] == ':'):
            candidates.append(norm_in)
            # D. 退化探测
            for i in range(1, min(len(parts) + 1, 4)):
                candidates.append(os.path.join(data_root, *parts[-i:]))

        # E. 上下文探测
        if current_folder_path:
            ctx_abs = os.path.abspath(current_folder_path)
            base = ctx_abs if os.path.isdir(
                ctx_abs) else os.path.dirname(ctx_abs)
            candidates.append(os.path.join(base, norm_in))

        seen = set()
        for cand in candidates:
            try:
                abs_p = os.path.abspath(os.path.normpath(cand))
                if abs_p in seen:
                    continue
                seen.add(abs_p)
                if os.path.exists(abs_p):
                    logger.info(
                        f"[路径解析] 命中物理路径: {annotation_folder} -> {abs_p}")
                    return abs_p
            except:
                continue

        fallback = os.path.abspath(os.path.join(data_root, norm_in))
        logger.warning(f"[路径解析] 物理路径未命中，退化使用: {fallback}")
        return fallback

    res = _do_resolve()
    with _cache_lock:
        _path_resolution_cache[cache_key] = res
        if len(_path_resolution_cache) > 2000:
            _path_resolution_cache.clear()
    return res


def get_annotations_file_path(folder_path: str) -> str:
    """获取标注文件路径"""
    return os.path.join(folder_path, 'annotations.json')


def extract_last_frame(video_path: str) -> str:
    """提取视频最后一帧并缓存"""
    file_hash = get_file_hash(video_path)
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    temp_filename = f"{video_name}_{file_hash[:8]}_last_frame.jpg"
    temp_path = os.path.join(TEMP_DIR, temp_filename)

    if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
        update_file_access_time(temp_path)
        return temp_path

    try:
        # ffmpeg -sseof 优化
        result = subprocess.run([
            "ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path,
            "-update", "1", "-vframes", "1", "-q:v", "2", temp_path
        ], capture_output=True, text=True, timeout=15)

        if result.returncode == 0 and os.path.exists(temp_path):
            update_file_access_time(temp_path)
            return temp_path
    except:
        pass

    # OpenCV 回退
    cap = cv2.VideoCapture(video_path)
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, total - 1)
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(temp_path, frame)
                update_file_access_time(temp_path)
                return temp_path
    finally:
        cap.release()

    raise ValueError(f"无法从视频提取最后一帧: {video_path}")

# ... (保持 scan_video_files, check_video_codec_compatible, convert_video_for_browser 等原有逻辑不变)
# 这里由于篇幅限制，实际重写时我将包含这些完整函数。


def scan_video_files(folder_path: str) -> list:
    with _cache_lock:
        if folder_path in _folder_contents_cache:
            cache = _folder_contents_cache[folder_path]
            try:
                if os.path.getmtime(folder_path) <= cache['mtime']:
                    return cache['videos']
            except:
                pass

    exts = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v'}
    videos = []
    try:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if os.path.splitext(file)[1].lower() in exts:
                    full_p = os.path.join(root, file)
                    if platform.system() == 'Windows' and file.startswith('._'):
                        continue
                    if os.path.getsize(full_p) < 1024:
                        continue
                    videos.append({'name': file, 'path': full_p})

        with _cache_lock:
            _folder_contents_cache[folder_path] = {
                'videos': videos, 'mtime': time.time()}
        return videos
    except Exception as e:
        logger.error(f"扫描视频失败: {e}")
        return []


def check_video_codec_compatible(video_path: str) -> bool:
    try:
        res = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ], capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return res.stdout.strip().lower() in {'h264', 'avc1', 'avc', 'vp8', 'vp9', 'av1'}
    except:
        pass
    return True


def convert_video_for_browser(video_path: str, force_convert: bool = False) -> str:
    ext = os.path.splitext(video_path)[1].lower()
    file_hash = get_file_hash(video_path)
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    out_name = f"{video_name}_{file_hash[:8]}_converted.mp4"
    out_path = os.path.join(
        WINDOWS_TEMP_DIR if platform.system() == 'Windows' else TEMP_DIR, out_name)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        update_file_access_time(out_path)
        return out_path

    if ext == '.mp4' and not force_convert:
        if platform.system() != 'Windows' or check_video_codec_compatible(video_path):
            return video_path

    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-c:v", "libx264", "-preset", "fast",
            "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-pix_fmt", "yuv420p", out_path
        ], capture_output=True, text=True, timeout=300)
        if os.path.exists(out_path):
            update_file_access_time(out_path)
            return out_path
    except:
        pass
    return video_path

# --- API Routes ---


@app.route('/')
def index():
    return send_file(os.path.join(PROJECT_ROOT, 'web_html', 'simple_annotation_tool.html'))


@app.route('/api/simple_annotation/scan_videos', methods=['POST'])
def scan_videos():
    try:
        path = request.get_json().get('folder_path', '').strip()
        if not path:
            return jsonify({'error': '路径不能为空'}), 400
        res_path = resolve_folder_path(path, path)
        videos = scan_video_files(res_path)

        # 标准化视频路径，供前端构建 Key 使用
        for v in videos:
            v['folder_key'] = normalize_path_for_key(
                os.path.dirname(v['path']))

        return jsonify({'success': True, 'videos': videos})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/get_video_info', methods=['POST'])
def get_video_info():
    try:
        data = request.get_json()
        f_path, v_name = data.get('folder_path', '').strip(
        ), data.get('video_name', '').strip()
        res_f_path = resolve_folder_path(f_path, f_path)

        videos = scan_video_files(res_f_path)
        video_path = next((v['path']
                          for v in videos if v['name'] == v_name), None)
        if not video_path:
            return jsonify({'error': '视频不存在'}), 404

        converted_path = convert_video_for_browser(video_path)
        last_frame = extract_last_frame(video_path)

        import urllib.parse
        v_url = f"/api/simple_annotation/video/{urllib.parse.quote(os.path.basename(converted_path))}?path={urllib.parse.quote(os.path.dirname(converted_path))}"
        img_url = f"/api/simple_annotation/image/{urllib.parse.quote(os.path.basename(last_frame))}"

        # 加载标注
        ann_file = get_annotations_file_path(res_f_path)
        annotation = None
        if os.path.exists(ann_file):
            with open(ann_file, 'r', encoding='utf-8') as f:
                anns = json.load(f)
                items = anns if isinstance(anns, list) else anns.values()
                # 匹配当前视频
                for ann in items:
                    if ann.get('video_name') == v_name:
                        annotation = ann
                        break

        return jsonify({
            'success': True, 'video_url': v_url, 'last_frame_url': img_url,
            'video_path': video_path, 'annotation': annotation
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/load_annotations', methods=['POST'])
def load_annotations():
    try:
        f_path = request.get_json().get('folder_path', '').strip()
        res_f_path = resolve_folder_path(f_path, f_path)
        ann_file = get_annotations_file_path(res_f_path)

        # 退化加载逻辑
        if not os.path.exists(ann_file):
            logger.info(f"[加载标注] 物理路径未找到，尝试在 data 目录下匹配相对路径...")
            parts = f_path.replace('\\', '/').split('/')
            rel = os.path.join(
                *parts[parts.index('data')+1:]) if 'data' in parts else f_path
            degraded_path = os.path.abspath(
                os.path.join(PROJECT_ROOT, 'data', rel))
            degraded_file = get_annotations_file_path(degraded_path)
            if os.path.exists(degraded_file):
                logger.info(f"[加载标注] 命中退化路径: {degraded_file}")
                res_f_path, ann_file = degraded_path, degraded_file

        if not os.path.exists(ann_file):
            return jsonify({'success': True, 'annotations': {}})

        with open(ann_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        res_dict = {}
        items = data if isinstance(data, list) else data.values()

        # 预先生成当前请求路径的标准化版本
        current_req_folder_key = normalize_path_for_key(res_f_path)

        for ann in items:
            if not isinstance(ann, dict):
                continue
            ann_folder = ann.get('folder', res_f_path)
            phys_f = resolve_folder_path(ann_folder, res_f_path)

            # 1. 物理路径 Key (最准确)
            phys_key = f"{normalize_path_for_key(phys_f)}|{ann.get('video_name', '')}"
            res_dict[phys_key] = ann

            # 2. 兼容性 Key: 如果这个标注属于当前请求的文件夹，
            # 那么也允许用前端传来的原始 folder_path 构建 Key
            if normalize_path_for_key(phys_f) == current_req_folder_key:
                compat_key = f"{f_path}|{ann.get('video_name', '')}"
                res_dict[compat_key] = ann

        return jsonify({'success': True, 'annotations': res_dict})
    except Exception as e:
        logger.error(f"[加载标注] 失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/save_annotations', methods=['POST'])
def save_annotations():
    try:
        data = request.get_json()
        f_path, anns_dict = data.get(
            'folder_path', '').strip(), data.get('annotations', {})
        res_f_path = resolve_folder_path(f_path, f_path)
        ann_file = get_annotations_file_path(res_f_path)

        os.makedirs(os.path.dirname(ann_file), exist_ok=True)

        anns_list = list(anns_dict.values())
        # 保存前：将所有 folder 路径转为相对项目根目录的路径，确保跨平台通用
        for ann in anns_list:
            abs_folder = resolve_folder_path(
                ann.get('folder', res_f_path), res_f_path)
            try:
                rel = os.path.relpath(abs_folder, PROJECT_ROOT)
                if not rel.startswith('..'):
                    ann['folder'] = rel
            except:
                pass

        with open(ann_file, 'w', encoding='utf-8') as f:
            json.dump(anns_list, f, ensure_ascii=False, indent=2)

        logger.info(f"[保存标注] 成功: {ann_file} ({len(anns_list)} 条记录)")
        return jsonify({'success': True, 'file': ann_file})
    except Exception as e:
        logger.error(f"[保存标注] 失败: {e}")
        return jsonify({'error': str(e)}), 500

# ... (保持其他服务如 serve_video, serve_image, asr_recognition, sam_segment 逻辑一致，仅统一日志格式)


@app.route('/api/simple_annotation/video/<filename>')
def serve_video(filename):
    try:
        import urllib.parse
        f_path = urllib.parse.unquote(request.args.get('path', ''))
        res_f_path = resolve_folder_path(f_path, f_path)
        video_p = os.path.join(res_f_path, urllib.parse.unquote(filename))

        if not os.path.exists(video_p):
            return jsonify({'error': '文件不存在'}), 404
        update_file_access_time(video_p)
        return send_file(video_p)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/image/<filename>')
def serve_image(filename):
    try:
        import urllib.parse
        p = os.path.join(TEMP_DIR, urllib.parse.unquote(filename))
        if not os.path.exists(p):
            return jsonify({'error': '文件不存在'}), 404
        update_file_access_time(p)
        return send_file(p)
    except Exception as e:
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

        logger.info(f"[ASR识别] 开始处理: {video_name}")
        res_folder = resolve_folder_path(folder_path, folder_path)

        # 查找视频文件
        videos = scan_video_files(res_folder)
        video_path = next((v['path']
                          for v in videos if v['name'] == video_name), None)
        if not video_path:
            return jsonify({'error': '未找到视频文件'}), 404

        # 提取音频
        file_hash = get_file_hash(video_path)
        audio_filename = f"{os.path.splitext(video_name)[0]}_{file_hash[:8]}.mp3"
        audio_path = os.path.join(TEMP_DIR, audio_filename)

        if not os.path.exists(audio_path):
            audio_path_extracted, _ = extract_audio_and_video(
                video_path, output_dir=TEMP_DIR, audio_filename=audio_filename
            )
            if not audio_path_extracted:
                return jsonify({'error': '音频提取失败'}), 500
            audio_path = audio_path_extracted

        update_file_access_time(audio_path)

        # ASR 识别核心逻辑
        from pipeline.audio_processor import convert_to_mono
        import dashscope
        from dashscope.audio.asr import Recognition
        from http import HTTPStatus
        from config.settings import ASR_MODEL, AUDIO_FORMAT, AUDIO_SAMPLE_RATE

        success, words_list, error_msg = audio_to_words_with_timestamps(
            audio_path, api_key=DASHSCOPE_API_KEY
        )
        if not success:
            return jsonify({'error': f"ASR识别失败: {error_msg}"}), 500

        # 获取句子级信息
        dashscope.api_key = DASHSCOPE_API_KEY
        mono_audio = convert_to_mono(audio_path)
        sentences = []
        if mono_audio:
            recognition = Recognition(
                model=ASR_MODEL, format=AUDIO_FORMAT, sample_rate=AUDIO_SAMPLE_RATE)
            result = recognition.call(mono_audio)
            if result.status_code == HTTPStatus.OK:
                sentence_data = result.get_sentence()
                if sentence_data:
                    for sent in sentence_data:
                        sentences.append({
                            'text': sent.get('text', ''),
                            'begin_time': sent.get('begin_time', 0),
                            'end_time': sent.get('end_time', 0)
                        })
            if os.path.exists(mono_audio):
                os.remove(mono_audio)

        full_text = ' '.join([s['text'] for s in sentences]) if sentences else ' '.join(
            [w['text'] for w in words_list])

        return jsonify({
            'success': True,
            'text': full_text,
            'sentences': sentences or [{'text': full_text, 'begin_time': 0, 'end_time': 0}],
            'words': words_list
        })
    except Exception as e:
        logger.error(f"[ASR识别] 异常: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/simple_annotation/sam_segment', methods=['POST'])
def sam_segment():
    """调用 SAM3 API 进行图像分割"""
    try:
        import urllib.parse
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()
        video_name = data.get('video_name', '').strip()
        points = data.get('points', [])
        point_labels = data.get('point_labels', [1] * len(points))

        if not folder_path or not video_name or not points:
            return jsonify({'error': '参数不完整'}), 400

        logger.info(f"[SAM3分割] 开始处理: {video_name}")
        res_folder = resolve_folder_path(folder_path, folder_path)

        # 查找视频并提取最后一帧
        videos = scan_video_files(res_folder)
        video_path = next((v['path']
                          for v in videos if v['name'] == video_name), None)
        if not video_path:
            return jsonify({'error': '未找到视频文件'}), 404

        last_frame_path = extract_last_frame(video_path)

        # 读取图像获取尺寸并转换坐标
        img = cv2.imread(last_frame_path)
        if img is None:
            return jsonify({'error': '无法读取图像帧'}), 500
        h, w = img.shape[:2]
        pixel_points = normalize_to_pixel(points, w, h)

        # 调用分割工具
        video_basename = os.path.splitext(video_name)[0]
        mask_out_name = f"{video_basename}_sam_mask.png"
        mask_out_path = os.path.join(TEMP_DIR, mask_out_name)

        result = sam3_segment_with_points(
            image_path=last_frame_path,
            points=pixel_points,
            point_labels=point_labels,
            output_path=mask_out_path,
            confidence_threshold=0.3
        )

        if not result.get('success'):
            return jsonify({'error': result.get('error', '分割失败')}), 500

        mask_data = None
        if result.get('results') and len(result['results']) > 0:
            best = result['results'][0]
            mask_data = {
                'mask_base64': best.get('mask_base64'),
                'bbox': best.get('bbox'),
                'score': best.get('score', 0),
                'point_on_mask': True
            }

        return jsonify({
            'success': True,
            'mask_image_url': f'/api/simple_annotation/image/{urllib.parse.quote(mask_out_name)}',
            'mask': mask_data,
            'results_count': result.get('results_count', 0)
        })
    except Exception as e:
        logger.error(f"[SAM3分割] 异常: {e}")
        return jsonify({'error': str(e)}), 500

# 清理与异常处理保持


@app.errorhandler(404)
def not_found(error): return jsonify({'error': '页面不存在'}), 404


@app.errorhandler(500)
def internal_error(error): return jsonify({'error': '服务器内部错误'}), 500


_last_cleanup = 0


def periodic_cleanup():
    global _last_cleanup
    if time.time() - _last_cleanup > CACHE_CLEANUP_INTERVAL:
        cleanup_temp_files()
        _last_cleanup = time.time()


@app.before_request
def before_req(): periodic_cleanup()


@app.route('/api/simple_annotation/cleanup_cache', methods=['POST'])
def manual_cleanup():
    c, s = cleanup_temp_files()
    return jsonify({'success': True, 'count': c, 'size_mb': round(s/1024/1024, 2)})


if __name__ == '__main__':
    print("🚀 标注服务器已启动: http://localhost:5001")
    app.run(host='0.0.0.0', port=5001, debug=True)
