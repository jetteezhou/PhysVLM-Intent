#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from pathlib import Path

# 获取项目根目录路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 导入ASR相关模块
from pipeline.video_preprocessor import extract_audio_and_video
from pipeline.audio_processor import audio_to_words_with_timestamps
from config.settings import DASHSCOPE_API_KEY

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 临时文件存储目录
TEMP_DIR = os.path.join(PROJECT_ROOT, 'temp')
os.makedirs(TEMP_DIR, exist_ok=True)


def extract_last_frame(video_path: str) -> str:
    """
    提取视频的最后一帧并保存为临时图片
    优先使用ffmpeg，如果失败则回退到OpenCV
    
    Args:
        video_path: 视频文件路径
    
    Returns:
        临时图片文件路径
    """
    # 生成临时文件名
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    temp_filename = f"{video_name}_last_frame.jpg"
    temp_path = os.path.join(TEMP_DIR, temp_filename)
    
    # 方法1: 尝试使用ffmpeg提取最后一帧（更可靠，特别是在Windows上）
    try:
        logger.info(f"[提取最后一帧] 尝试使用ffmpeg提取: {video_path}")
        
        # 首先获取视频时长
        probe_result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ], capture_output=True, text=True, timeout=10)
        
        if probe_result.returncode == 0:
            try:
                duration = float(probe_result.stdout.strip())
                logger.info(f"[提取最后一帧] 视频时长: {duration}秒")
                
                # 方法1: 从倒数0.5秒开始提取（确保能获取到最后一帧）
                start_time = max(0, duration - 0.5)
                
                extract_result = subprocess.run([
                    "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-i", video_path,
                    "-vframes", "1",
                    "-q:v", "2",
                    temp_path
                ], capture_output=True, text=True, timeout=30)
                
                if extract_result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    logger.info(f"[提取最后一帧] ffmpeg提取成功: {temp_path}")
                    return temp_path
                else:
                    logger.warning(f"[提取最后一帧] ffmpeg方法1失败，错误: {extract_result.stderr}")
                    
                    # 方法2: 尝试使用-sseof参数（从文件末尾开始）
                    extract_result2 = subprocess.run([
                        "ffmpeg", "-y",
                        "-sseof", "-0.5",  # 从文件末尾倒数0.5秒开始
                        "-i", video_path,
                        "-vframes", "1",
                        "-q:v", "2",
                        temp_path
                    ], capture_output=True, text=True, timeout=30)
                    
                    if extract_result2.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                        logger.info(f"[提取最后一帧] ffmpeg方法2提取成功: {temp_path}")
                        return temp_path
                    else:
                        logger.warning(f"[提取最后一帧] ffmpeg方法2也失败，错误: {extract_result2.stderr}")
                        
            except (ValueError, subprocess.TimeoutExpired) as e:
                logger.warning(f"[提取最后一帧] 获取视频时长失败: {e}")
        else:
            logger.warning(f"[提取最后一帧] ffprobe失败: {probe_result.stderr}")
        
        raise ValueError("ffmpeg提取失败")
            
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
        logger.info(f"[提取最后一帧] OpenCV提取成功: {temp_path}")
        return temp_path
        
    except Exception as e:
        logger.error(f"[提取最后一帧] 所有方法都失败: {e}")
        raise ValueError(f"无法提取视频的最后一帧: {str(e)}")


def scan_video_files(folder_path: str) -> list:
    """
    扫描文件夹下的所有视频文件
    
    Args:
        folder_path: 文件夹路径
    
    Returns:
        视频文件列表，每个元素包含 name 和 path
    """
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
                    videos.append({
                        'name': file,
                        'path': file_path
                    })
        
        logger.info(f"扫描到 {len(videos)} 个视频文件")
        return videos
        
    except Exception as e:
        logger.error(f"扫描视频文件失败: {e}")
        raise


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
    html_file = os.path.join(PROJECT_ROOT, 'web_html', 'simple_annotation_tool.html')
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
        
        videos = scan_video_files(folder_path)
        
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
        
        # 查找视频文件
        video_path = None
        searched_paths = []
        for root, dirs, files in os.walk(folder_path):
            searched_paths.append(root)
            if video_name in files:
                video_path = os.path.join(root, video_name)
                break
        
        if not video_path:
            logger.error(f"[标注交互] 视频文件不存在: {video_name}, 搜索路径: {folder_path}")
            logger.error(f"[标注交互] 已搜索的目录: {searched_paths}")
            return jsonify({
                'error': f'视频文件不存在: {video_name}',
                'searched_folder': folder_path
            }), 404
        
        if not os.path.exists(video_path):
            logger.error(f"[标注交互] 视频文件路径无效: {video_path}")
            return jsonify({
                'error': f'视频文件路径无效: {video_path}'
            }), 404
        
        logger.info(f"[标注交互] 找到视频文件: {video_path}")
        
        # 提取最后一帧
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
        video_dir = os.path.dirname(video_path)
        video_url = f'/api/simple_annotation/video/{urllib.parse.quote(os.path.basename(video_path))}?path={urllib.parse.quote(video_dir)}'
        last_frame_url = f'/api/simple_annotation/image/{urllib.parse.quote(os.path.basename(last_frame_path))}'
        
        logger.info(f"[标注交互] 视频信息获取成功")
        
        return jsonify({
            'success': True,
            'video_url': video_url,
            'last_frame_url': last_frame_url,
            'video_path': video_path
        })
        
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
        
        if not folder_path:
            return jsonify({'error': '缺少路径参数'}), 400
        
        video_path = os.path.join(folder_path, filename)
        
        if not os.path.exists(video_path):
            return jsonify({'error': '视频文件不存在'}), 404
        
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
        
        # 查找视频文件
        video_path = None
        for root, dirs, files in os.walk(folder_path):
            if video_name in files:
                video_path = os.path.join(root, video_name)
                break
        
        if not video_path or not os.path.exists(video_path):
            logger.error(f"[ASR识别] 视频文件不存在: {video_name}")
            return jsonify({'error': '视频文件不存在'}), 404
        
        logger.info(f"[ASR识别] 找到视频文件: {video_path}")
        
        # 提取音频
        logger.info(f"[ASR识别] 开始提取音频...")
        audio_path, _ = extract_audio_and_video(
            video_path,
            output_dir=TEMP_DIR
        )
        
        if not audio_path or not os.path.exists(audio_path):
            logger.error(f"[ASR识别] 音频提取失败")
            return jsonify({'error': '音频提取失败'}), 500
        
        logger.info(f"[ASR识别] 音频提取成功: {audio_path}")
        
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
                recognition_text = ' '.join([sent.get('text', '') for sent in sentences_list])
            elif words_list:
                # 如果没有句子信息，使用词汇列表构建文本
                recognition_text = ' '.join([word.get('text', '') for word in words_list])
            
            # 如果没有获取到句子信息，至少构建一个句子
            if not sentences_list and words_list:
                sentences_list = [{
                    'text': recognition_text,
                    'begin_time': words_list[0].get('begin_time', 0) if words_list else 0,
                    'end_time': words_list[-1].get('end_time', 0) if words_list else 0
                }]
            
            logger.info(f"[ASR识别] ASR识别成功，识别到 {len(sentences_list)} 个句子，识别文本: {recognition_text}")
            
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
                recognition_text = ' '.join([word.get('text', '') for word in words_list])
            
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


@app.route('/api/simple_annotation/load_annotations', methods=['POST'])
def load_annotations():
    """加载标注数据"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()
        
        if not folder_path:
            return jsonify({'error': '文件夹路径不能为空'}), 400
        
        logger.info(f"[标注交互] 加载标注数据: {folder_path}")
        
        annotations_file = get_annotations_file_path(folder_path)
        
        if not os.path.exists(annotations_file):
            logger.info(f"[标注交互] 标注文件不存在，返回空数据")
            return jsonify({
                'success': True,
                'annotations': {}
            })
        
        with open(annotations_file, 'r', encoding='utf-8') as f:
            annotations_data = json.load(f)
        
        # 转换为字典格式，key为 "folder|video_name"
        annotations_dict = {}
        if isinstance(annotations_data, list):
            for ann in annotations_data:
                key = f"{ann.get('folder', folder_path)}|{ann.get('video_name', '')}"
                annotations_dict[key] = ann
        elif isinstance(annotations_data, dict):
            annotations_dict = annotations_data
        
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
                    logger.info(f"          点 {pidx + 1}: [{point[0]}, {point[1]}]")
        
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


if __name__ == '__main__':
    print("🚀 启动简易标注工具服务器...")
    print("📋 访问地址: http://localhost:5002")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5002, debug=True)

