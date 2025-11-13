#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一Web应用服务器
整合数据采集、标注生成和人工检验标注的完整流程
"""
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import json
import os
import sys
import logging
import threading
import time
from datetime import datetime
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# 获取项目根目录路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from pipeline.pipeline import IntentLabelPipeline
from config.settings import Config

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ==================== 配置路径 ====================
TASK_CONFIG_DIR = os.path.join(PROJECT_ROOT, 'tools/data_collection/task_config')
TEMPLATES_FILE = os.path.join(TASK_CONFIG_DIR, 'templates.json')
SCENES_FILE = os.path.join(TASK_CONFIG_DIR, 'scenes.json')
COLLECTIONS_FILE = os.path.join(TASK_CONFIG_DIR, 'collections.json')
COLLECTION_BASE_DIR = os.path.join(PROJECT_ROOT, 'tools/data_collection/datas')
DATA_FILE = os.path.join(PROJECT_ROOT, 'pipeline/outputs/pipeline_data.json')
OPERATION_LOG_FILE = os.path.join(PROJECT_ROOT, 'pipeline/outputs/operation_log.json')  # 操作日志文件

VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v', '.webm'}

# 确保目录存在
for directory in [TASK_CONFIG_DIR, COLLECTION_BASE_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

# Pipeline任务状态存储
pipeline_tasks = {}  # {task_id: {status, progress, message, result, error}}

# 并行处理配置
MAX_WORKER_THREADS = 3  # 最大并行线程数，可根据API限流调整（建议3-5个）

# ==================== 初始化数据文件 ====================
def init_data_files():
    """初始化数据文件"""
    for file_path, default in [
        (TEMPLATES_FILE, []),
        (SCENES_FILE, []),
        (COLLECTIONS_FILE, []),
    ]:
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
    
    # 初始化操作日志文件
    if not os.path.exists(OPERATION_LOG_FILE):
        log_data = []
        log_dir = os.path.dirname(OPERATION_LOG_FILE)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        with open(OPERATION_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

init_data_files()

# ==================== 操作日志管理函数 ====================
def load_operation_logs():
    """加载操作日志"""
    try:
        if os.path.exists(OPERATION_LOG_FILE):
            with open(OPERATION_LOG_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f)
                if not isinstance(logs, list):
                    logs = []
                return logs
    except Exception as e:
        logger.error(f"加载操作日志失败: {e}")
    return []

def save_operation_logs(logs):
    """保存操作日志"""
    try:
        # 限制日志数量，保留最近1000条
        if len(logs) > 1000:
            logs = logs[-1000:]
        with open(OPERATION_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存操作日志失败: {e}")

def record_operation_log(operation_type, description, details=None):
    """记录操作日志（仅记录成功的操作）"""
    try:
        logs = load_operation_logs()
        log_entry = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "operation_type": operation_type,
            "description": description,
            "details": details or {}
        }
        logs.append(log_entry)
        save_operation_logs(logs)
    except Exception as e:
        logger.error(f"记录操作日志失败: {e}")

# ==================== 工具函数 ====================
def normalize_path(path):
    """规范化路径（统一使用正斜杠）"""
    if not path:
        return path
    return os.path.normpath(path).replace('\\', '/')

def get_relative_path(path, project_root=None):
    """获取相对于项目根目录的路径"""
    if not path:
        return path
    if project_root is None:
        project_root = PROJECT_ROOT
    try:
        abs_path = os.path.abspath(path)
        if abs_path.startswith(project_root):
            return os.path.normpath(os.path.relpath(abs_path, project_root))
        return os.path.normpath(path)
    except:
        return path

def paths_match(path1, path2, project_root=None):
    """判断两个路径是否匹配（支持相对路径和绝对路径）"""
    if not path1 or not path2:
        return False
    
    if project_root is None:
        project_root = PROJECT_ROOT
    
    # 规范化路径
    norm_path1 = normalize_path(path1)
    norm_path2 = normalize_path(path2)
    
    # 直接比较规范化后的路径
    if norm_path1 == norm_path2:
        return True
    
    # 尝试将两个路径都转换为绝对路径后比较
    try:
        abs_path1 = os.path.abspath(path1)
        abs_path2 = os.path.abspath(path2)
        if normalize_path(abs_path1) == normalize_path(abs_path2):
            return True
    except:
        pass
    
    # 尝试将两个路径都转换为相对路径后比较
    try:
        rel_path1 = get_relative_path(path1, project_root)
        rel_path2 = get_relative_path(path2, project_root)
        if normalize_path(rel_path1) == normalize_path(rel_path2):
            return True
    except:
        pass
    
    return False

def scan_videos(directory):
    """扫描目录中的视频文件"""
    videos = []
    if not os.path.exists(directory):
        return videos
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            file_ext = Path(file).suffix.lower()
            if file_ext in VIDEO_EXTENSIONS:
                stat = os.stat(file_path)
                videos.append({
                    'filename': file,
                    'path': file_path,
                    'relative_path': os.path.relpath(file_path, directory),
                    'size': stat.st_size,
                    'size_mb': round(stat.st_size / (1024 * 1024), 2),
                    'modified_time': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
    videos.sort(key=lambda x: x['filename'])
    return videos

def update_pipeline_progress(task_id, step, progress, message):
    """更新Pipeline进度"""
    if task_id in pipeline_tasks:
        pipeline_tasks[task_id]['current_step'] = step
        pipeline_tasks[task_id]['progress'] = progress
        pipeline_tasks[task_id]['message'] = message
        
        # 添加日志条目（避免重复）
        log_entry = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'step': step,
            'message': message
        }
        # 检查最后一条日志是否相同
        if not pipeline_tasks[task_id]['logs'] or \
           pipeline_tasks[task_id]['logs'][-1]['message'] != message:
            pipeline_tasks[task_id]['logs'].append(log_entry)
        
        socketio.emit('pipeline_progress', {
            'task_id': task_id,
            'status': 'running',
            'progress': progress,
            'current_step': step,
            'message': message
        })

# ==================== 主页面 ====================
@app.route('/')
def index():
    """返回统一的主页面"""
    html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'unified_app.html')
    if os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    return "统一应用页面未找到", 404

@app.route('/tools/data_collection/collection_tool.html')
def collection_tool():
    """返回数据采集工具页面"""
    html_file = os.path.join(PROJECT_ROOT, 'web_html/collection_tool.html')
    if os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    return "数据采集工具页面未找到", 404

@app.route('/tools/pipeline/pipeline_tool.html')
def pipeline_tool():
    """返回标注生成工具页面"""
    html_file = os.path.join(PROJECT_ROOT, 'web_html/pipeline_tool.html')
    if os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    return "标注生成工具页面未找到", 404

@app.route('/tools/annotation/annotation_verification_tool.html')
def annotation_verification_tool():
    """返回标注检验工具页面"""
    html_file = os.path.join(PROJECT_ROOT, 'web_html/annotation_verification_tool.html')
    if os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    return "标注检验工具页面未找到", 404

@app.route('/tools/annotation/annotation_tool.html')
def annotation_tool():
    """返回标注工具页面"""
    html_file = os.path.join(PROJECT_ROOT, 'web_html/annotation_tool.html')
    if os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    return "标注工具页面未找到", 404

# ==================== 数据采集 API ====================
@app.route('/api/admin/templates', methods=['GET'])
def get_templates():
    """获取所有任务模板"""
    try:
        with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            templates = json.load(f)
        return jsonify({'success': True, 'templates': templates})
    except Exception as e:
        logger.error(f"获取任务模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/templates', methods=['POST'])
def create_template():
    """创建任务模板"""
    try:
        data = request.get_json()
        required_fields = ['name', 'target_count']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'缺少必要字段: {field}'}), 400
        
        with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            templates = json.load(f)
        
        if any(t.get('name') == data['name'] for t in templates):
            return jsonify({'success': False, 'error': '任务模板名称已存在'}), 400
        
        template_id = len(templates) + 1
        new_template = {
            'id': template_id,
            'name': data['name'],
            'target_count': int(data['target_count']),
            'description': data.get('description', ''),
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        templates.append(new_template)
        
        with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'template': new_template})
    except Exception as e:
        logger.error(f"创建任务模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/templates/<int:template_id>', methods=['PUT'])
def update_template(template_id):
    """更新任务模板"""
    try:
        data = request.get_json()
        with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            templates = json.load(f)
        
        template_index = None
        for i, t in enumerate(templates):
            if t.get('id') == template_id:
                template_index = i
                break
        
        if template_index is None:
            return jsonify({'success': False, 'error': '任务模板不存在'}), 404
        
        if 'name' in data:
            templates[template_index]['name'] = data['name']
        if 'target_count' in data:
            templates[template_index]['target_count'] = int(data['target_count'])
        if 'description' in data:
            templates[template_index]['description'] = data['description']
        
        templates[template_index]['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'template': templates[template_index]})
    except Exception as e:
        logger.error(f"更新任务模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/templates/<int:template_id>', methods=['DELETE'])
def delete_template(template_id):
    """删除任务模板"""
    try:
        with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            templates = json.load(f)
        templates = [t for t in templates if t.get('id') != template_id]
        with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除任务模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/scenes', methods=['GET'])
def get_scenes():
    """获取所有场景类型"""
    try:
        with open(SCENES_FILE, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        return jsonify({'success': True, 'scenes': scenes})
    except Exception as e:
        logger.error(f"获取场景类型失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/scenes', methods=['POST'])
def create_scene():
    """创建场景类型"""
    try:
        data = request.get_json()
        if 'name' not in data or 'description' not in data:
            return jsonify({'success': False, 'error': '缺少必要字段: name 或 description'}), 400
        
        with open(SCENES_FILE, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        
        if any(s.get('name') == data['name'] for s in scenes):
            return jsonify({'success': False, 'error': '场景类型名称已存在'}), 400
        
        scene_id = len(scenes) + 1
        new_scene = {
            'id': scene_id,
            'name': data['name'],
            'description': data['description'],
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        scenes.append(new_scene)
        
        with open(SCENES_FILE, 'w', encoding='utf-8') as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'scene': new_scene})
    except Exception as e:
        logger.error(f"创建场景类型失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/scenes/<int:scene_id>', methods=['PUT'])
def update_scene(scene_id):
    """更新场景类型"""
    try:
        data = request.get_json()
        with open(SCENES_FILE, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        
        scene_index = None
        for i, s in enumerate(scenes):
            if s.get('id') == scene_id:
                scene_index = i
                break
        
        if scene_index is None:
            return jsonify({'success': False, 'error': '场景类型不存在'}), 404
        
        if 'name' in data:
            scenes[scene_index]['name'] = data['name']
        if 'description' in data:
            scenes[scene_index]['description'] = data['description']
        
        scenes[scene_index]['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(SCENES_FILE, 'w', encoding='utf-8') as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'scene': scenes[scene_index]})
    except Exception as e:
        logger.error(f"更新场景类型失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/scenes/<int:scene_id>', methods=['DELETE'])
def delete_scene(scene_id):
    """删除场景类型"""
    try:
        with open(SCENES_FILE, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        scenes = [s for s in scenes if s.get('id') != scene_id]
        with open(SCENES_FILE, 'w', encoding='utf-8') as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除场景类型失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/collection/create', methods=['POST'])
def create_collection():
    """创建采集任务"""
    try:
        data = request.get_json()
        if 'template_id' not in data or 'scene_id' not in data:
            return jsonify({'success': False, 'error': '缺少必要字段: template_id 或 scene_id'}), 400
        
        with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            templates = json.load(f)
        with open(SCENES_FILE, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        
        template = next((t for t in templates if t.get('id') == data['template_id']), None)
        scene = next((s for s in scenes if s.get('id') == data['scene_id']), None)
        
        if not template or not scene:
            return jsonify({'success': False, 'error': '任务模板或场景类型不存在'}), 404
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        folder_name = f"{template['name']}_{scene['name']}_{timestamp}"
        collection_dir = os.path.join(COLLECTION_BASE_DIR, folder_name)
        
        if os.path.exists(collection_dir):
            return jsonify({'success': False, 'error': '采集文件夹已存在'}), 400
        
        os.makedirs(collection_dir)
        
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        collection_id = len(collections) + 1
        new_collection = {
            'id': collection_id,
            'template_id': data['template_id'],
            'template_name': template['name'],
            'scene_id': data['scene_id'],
            'scene_name': scene['name'],
            'folder_path': collection_dir,
            'folder_name': folder_name,
            'target_count': template['target_count'],
            'current_count': 0,
            'videos': [],
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'active'
        }
        collections.append(new_collection)
        
        with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(collections, f, ensure_ascii=False, indent=2)
        
        # 记录操作日志
        record_operation_log(
            'create_collection',
            f'创建采集任务: {template["name"]} - {scene["name"]}',
            {
                'collection_id': collection_id,
                'template_name': template['name'],
                'scene_name': scene['name'],
                'folder_name': folder_name
            }
        )
        
        return jsonify({'success': True, 'collection': new_collection})
    except Exception as e:
        logger.error(f"创建采集任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/collection/list', methods=['GET'])
def list_collections():
    """获取所有采集任务"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        for collection in collections:
            collection_dir = collection.get('folder_path')
            if collection_dir and os.path.exists(collection_dir):
                videos = scan_videos(collection_dir)
                collection['current_count'] = len(videos)
                collection['videos'] = videos
        
        with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(collections, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'collections': collections})
    except Exception as e:
        logger.error(f"获取采集任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/collection/<int:collection_id>/scan', methods=['POST'])
def scan_collection(collection_id):
    """扫描采集文件夹中的视频文件（更新历史记录）"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        collection = next((c for c in collections if c.get('id') == collection_id), None)
        if not collection:
            return jsonify({'success': False, 'error': '采集任务不存在'}), 404
        
        collection_dir = collection.get('folder_path')
        if not collection_dir:
            return jsonify({'success': False, 'error': '采集文件夹路径不存在'}), 404
        
        videos = scan_videos(collection_dir) if os.path.exists(collection_dir) else []
        
        collection['current_count'] = len(videos)
        collection['videos'] = videos
        
        # 不再需要更新历史记录，进度直接从文件系统读取
        
        collection_index = next((i for i, c in enumerate(collections) if c.get('id') == collection_id), None)
        if collection_index is not None:
            collections[collection_index] = collection
            with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            'success': True,
            'videos': videos,
            'count': len(videos),
            'target_count': collection.get('target_count', 0)
        })
    except Exception as e:
        logger.error(f"扫描采集文件夹失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/collection/<int:collection_id>/complete', methods=['POST'])
def complete_collection(collection_id):
    """完成采集任务"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        collection_index = next((i for i, c in enumerate(collections) if c.get('id') == collection_id), None)
        if collection_index is None:
            return jsonify({'success': False, 'error': '采集任务不存在'}), 404
        
        collections[collection_index]['status'] = 'completed'
        collections[collection_index]['completed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(collections, f, ensure_ascii=False, indent=2)
        
        # 记录操作日志
        collection = collections[collection_index]
        record_operation_log(
            'complete_collection',
            f'完成采集任务: {collection.get("template_name")} - {collection.get("scene_name")}',
            {
                'collection_id': collection_id,
                'template_name': collection.get('template_name'),
                'scene_name': collection.get('scene_name'),
                'video_count': collection.get('current_count', 0)
            }
        )
        
        return jsonify({'success': True, 'collection': collections[collection_index]})
    except Exception as e:
        logger.error(f"完成采集任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/collection/<int:collection_id>', methods=['DELETE'])
def delete_collection(collection_id):
    """删除采集任务及其相关数据"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        collection_index = next((i for i, c in enumerate(collections) if c.get('id') == collection_id), None)
        if collection_index is None:
            return jsonify({'success': False, 'error': '采集任务不存在'}), 404
        
        collection = collections[collection_index]
        folder_path = collection.get('folder_path')
        
        if folder_path and os.path.exists(folder_path):
            try:
                shutil.rmtree(folder_path)
            except Exception as e:
                logger.warning(f"删除文件夹失败: {e}")
        
        collections.pop(collection_index)
        
        with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(collections, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'message': '采集任务及相关数据已删除'})
    except Exception as e:
        logger.error(f"删除采集任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/videos/<path:filename>')
def serve_video(filename):
    """提供视频文件服务"""
    try:
        file_path = os.path.join(COLLECTION_BASE_DIR, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return send_file(file_path)
        for root, dirs, files in os.walk(COLLECTION_BASE_DIR):
            base_filename = os.path.basename(filename)
            if base_filename in files:
                full_path = os.path.join(root, base_filename)
                if os.path.exists(full_path):
                    return send_file(full_path)
        return jsonify({'error': '视频文件不存在'}), 404
    except Exception as e:
        logger.error(f"提供视频文件失败: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== 标注文件管理函数 ====================
def get_annotations_file_path(collection_id):
    """获取标注文件路径"""
    return os.path.join(
        PROJECT_ROOT,
        'pipeline', 'outputs',
        f'collection_{collection_id}',
        'annotations.json'
    )

def load_annotations(collection_id):
    """加载标注文件"""
    annotations_file = get_annotations_file_path(collection_id)
    if os.path.exists(annotations_file):
        try:
            with open(annotations_file, 'r', encoding='utf-8') as f:
                annotations = json.load(f)
                if not isinstance(annotations, list):
                    annotations = []
                return annotations
        except Exception as e:
            logger.error(f"加载标注文件失败: {e}")
            return []
    return []

def save_annotations_file(collection_id, annotations):
    """保存标注文件（辅助函数）"""
    annotations_file = get_annotations_file_path(collection_id)
    annotations_dir = os.path.dirname(annotations_file)
    if not os.path.exists(annotations_dir):
        os.makedirs(annotations_dir, exist_ok=True)
    
    with open(annotations_file, 'w', encoding='utf-8') as f:
        json.dump(annotations, f, ensure_ascii=False, indent=2)

def init_annotations_for_videos(collection_id, videos):
    """为视频列表初始化标注文件"""
    annotations = load_annotations(collection_id)
    
    for video in videos:
        video_path = video['path']
        rel_video_path = get_relative_path(video_path)
        
        # 检查是否已存在（使用路径匹配）
        found = False
        for ann in annotations:
            ann_video_path = ann.get('input_video_path') or ann.get('video_path', '')
            if paths_match(ann_video_path, rel_video_path) or paths_match(ann_video_path, video_path):
                # 已存在，保持不变
                found = True
                break
        
        if not found:
            # 新建条目
            annotations.append({
                "input_video_path": rel_video_path,
                "video_path": None,
                "audio_path": None,
                "last_image_path": None,
                "last_image_path_absolute": None,
                "video_description": None,
                "result_data": None,
                "objects": [],
                "image_dimensions": None,
                "verified": False
            })
    
    save_annotations_file(collection_id, annotations)
    return annotations

def update_annotation_result(collection_id, video_path, result_data):
    """更新标注结果"""
    annotations = load_annotations(collection_id)
    
    rel_video_path = get_relative_path(video_path)
    
    # 查找对应的条目
    for ann in annotations:
        ann_video_path = ann.get('input_video_path') or ann.get('video_path', '')
        if paths_match(ann_video_path, rel_video_path) or paths_match(ann_video_path, video_path):
            # 检查是否是重新生成标注（之前已有result_data）
            was_previously_processed = ann.get('result_data') is not None
            
            # 更新结果数据
            ann.update({
                "input_video_path": rel_video_path,
                "video_path": get_relative_path(result_data.get('video_path')),
                "audio_path": get_relative_path(result_data.get('audio_path')),
                "last_image_path": get_relative_path(result_data.get('last_image_path')),
                "last_image_path_absolute": result_data.get('last_image_path_absolute'),
                "video_description": result_data.get('video_description'),
                "result_data": result_data.get('result_data'),
                "objects": result_data.get('objects', []),
                "image_dimensions": result_data.get('image_dimensions'),
                "verified": False if was_previously_processed else ann.get('verified', False)  # 重新生成时重置验证状态
            })
            
            # 如果重新生成，清除验证时间戳
            if was_previously_processed:
                ann.pop('verified_at', None)
            
            save_annotations_file(collection_id, annotations)
            return True
    
    return False

# ==================== Pipeline API ====================
@app.route('/api/pipeline/collections', methods=['GET'])
def get_pipeline_collections():
    """获取可用于Pipeline的采集任务列表，从annotations.json文件判断进度"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        result = []
        for col in collections:
            collection_id = col.get('id')
            videos = scan_videos(col.get('folder_path', ''))
            
            # 加载标注文件
            annotations = load_annotations(collection_id)
            
            # 统计已处理的视频数量（result_data 不为 None）
            processed_count = sum(1 for ann in annotations if ann.get('result_data') is not None)
            
            # 计算每个视频的处理状态
            video_statuses = {}
            
            for video in videos:
                video_path = video['path']
                rel_video_path = get_relative_path(video_path)
                
                # 查找对应的标注条目
                ann_entry = None
                for ann in annotations:
                    ann_video_path = ann.get('input_video_path') or ann.get('video_path', '')
                    if paths_match(ann_video_path, rel_video_path) or paths_match(ann_video_path, video_path):
                        ann_entry = ann
                        break
                
                if ann_entry and ann_entry.get('result_data') is not None:
                    annotations_file = get_annotations_file_path(collection_id)
                    processed_at = datetime.fromtimestamp(os.path.getmtime(annotations_file)).strftime('%Y-%m-%d %H:%M:%S') if os.path.exists(annotations_file) else None
                    video_statuses[video_path] = {
                        "status": "completed",
                        "progress": 100,
                        "result_file": os.path.relpath(annotations_file, PROJECT_ROOT),
                        "processed_at": processed_at
                    }
                else:
                    video_statuses[video_path] = {
                        "status": "pending",
                        "progress": 0,
                        "result_file": None,
                        "processed_at": None
                    }
            
            # 确定状态
            if processed_count == 0:
                status = "pending"
            elif processed_count == len(videos):
                status = "completed"
            else:
                status = "partial"
            
            result.append({
                'id': collection_id,
                'name': f"{col.get('template_name')} - {col.get('scene_name')}",
                'template_name': col.get('template_name'),
                'scene_name': col.get('scene_name'),
                'video_count': len(videos),
                'processed_count': processed_count,
                'status': status,
                'videos': videos,
                'video_statuses': video_statuses,
                'last_updated': col.get('created_at', '')
            })
        
        return jsonify({'success': True, 'collections': result})
    except Exception as e:
        logger.error(f"获取采集任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pipeline/start', methods=['POST'])
def start_pipeline():
    """启动Pipeline处理 - 以采集任务文件夹为单位批量处理
    支持两种模式：
    - process_all=False: 只处理未完成的视频（默认）
    - process_all=True: 处理所有视频（重新生成所有标注）
    """
    try:
        data = request.get_json()
        collection_id = data.get('collection_id')
        process_all = data.get('process_all', False)  # 默认为False，只处理未完成的
        
        if not collection_id:
            return jsonify({'success': False, 'error': '缺少collection_id参数'}), 400
        
        # 获取采集任务信息
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        collection = next((c for c in collections if c.get('id') == collection_id), None)
        if not collection:
            return jsonify({'success': False, 'error': '采集任务不存在'}), 404
        
        folder_path = collection.get('folder_path')
        if not folder_path or not os.path.exists(folder_path):
            return jsonify({'success': False, 'error': '采集任务文件夹不存在'}), 404
        
        # 扫描文件夹中的所有视频
        videos = scan_videos(folder_path)
        if not videos:
            return jsonify({'success': False, 'error': '文件夹中没有视频文件'}), 400
        
        # 初始化标注文件
        annotations = init_annotations_for_videos(collection_id, videos)
        
        # 根据process_all参数决定处理哪些视频
        pending_videos = []
        if process_all:
            # 处理所有视频
            pending_videos = videos
        else:
            # 只处理未完成的视频（result_data 为 None）
            for video in videos:
                video_path = video['path']
                rel_video_path = get_relative_path(video_path)
                
                # 查找对应的标注条目
                ann_entry = None
                for ann in annotations:
                    ann_video_path = ann.get('input_video_path') or ann.get('video_path', '')
                    if paths_match(ann_video_path, rel_video_path) or paths_match(ann_video_path, video_path):
                        ann_entry = ann
                        break
                
                # 如果 result_data 为 None，则需要处理
                if not ann_entry or ann_entry.get('result_data') is None:
                    pending_videos.append(video)
        
        if not pending_videos:
            mode_text = '所有' if process_all else '未完成的'
            return jsonify({
                'success': True,
                'message': f'所有{mode_text}视频已完成标注，无需处理',
                'total_videos': len(videos),
                'pending_videos': 0
            })
        
        # 生成任务ID
        task_id = f"task_{collection_id}_{int(time.time() * 1000)}"
        
        # 初始化任务状态
        mode_text = '所有' if process_all else '未完成的'
        pipeline_tasks[task_id] = {
            'collection_id': collection_id,
            'status': 'running',
            'progress': 0,
            'current_step': '初始化',
            'message': f'准备处理 {len(pending_videos)} 个{mode_text}视频（共 {len(videos)} 个视频）...',
            'current_video': None,
            'current_video_index': 0,
            'total_videos': len(pending_videos),
            'total_all_videos': len(videos),
            'logs': [],
            'results': [],
            'error': None,
            'process_all': process_all
        }
        
        # 在后台线程中批量处理视频（并行处理）
        def run_batch_pipeline():
            try:
                total_videos = len(pending_videos)
                processed_count = 0
                failed_count = 0
                completed_lock = threading.Lock()  # 用于线程安全的计数
                
                mode_text = '所有' if process_all else '未完成的'
                update_pipeline_progress(task_id, '准备', 0, f'开始并行处理采集任务，共 {total_videos} 个{mode_text}视频（最大并行数: {MAX_WORKER_THREADS}）')
                
                # 处理单个视频的函数
                def process_single_video(video_info):
                    """处理单个视频"""
                    nonlocal processed_count, failed_count  # 在函数开始处声明 nonlocal
                    idx, video = video_info
                    video_path = video['path']
                    video_filename = video['filename']
                    
                    try:
                        # 创建临时输出文件（用于 pipeline.process）
                        video_name = os.path.splitext(video_filename)[0]
                        temp_output_file = os.path.join(
                            PROJECT_ROOT, 
                            'pipeline/outputs', 
                            f'collection_{collection_id}',
                            f'{video_name}_temp_pipeline_data.json'
                        )
                        
                        # 确保输出目录存在
                        output_dir = os.path.dirname(temp_output_file)
                        os.makedirs(output_dir, exist_ok=True)
                        
                        # 创建Pipeline实例（每个线程独立实例，避免冲突）
                        config = Config.from_env()
                        pipeline = IntentLabelPipeline(config)
                        
                        # 处理视频
                        result = pipeline.process(video_path, output_file=temp_output_file)
                        
                        # 更新 annotations.json 文件
                        update_annotation_result(collection_id, video_path, result)
                        
                        # 删除临时文件
                        if os.path.exists(temp_output_file):
                            try:
                                os.remove(temp_output_file)
                            except:
                                pass
                        
                        # 记录操作日志
                        record_operation_log(
                            'generate_annotation',
                            f'生成标注: {video_filename}',
                            {
                                'collection_id': collection_id,
                                'video_path': video_path,
                                'video_name': video_filename
                            }
                        )
                        
                        # 线程安全地更新计数和进度
                        with completed_lock:
                            processed_count += 1
                            current_total = processed_count + failed_count
                            progress = int((current_total / total_videos) * 100)
                            
                            update_pipeline_progress(task_id, '处理视频', progress,
                                                   f'视频 {current_total}/{total_videos} 处理完成 (并行处理中...)')
                        
                        return {
                            'video': video_filename,
                            'status': 'completed',
                            'index': idx
                        }
                        
                    except Exception as e:
                        error_msg = f'处理视频 {video_filename} 失败: {str(e)}'
                        logger.error(error_msg)
                        
                        # 线程安全地更新失败计数和进度
                        with completed_lock:
                            failed_count += 1
                            current_total = processed_count + failed_count
                            progress = int((current_total / total_videos) * 100)
                            
                            update_pipeline_progress(task_id, '处理视频', progress,
                                                   f'视频 {current_total}/{total_videos} 处理失败 (并行处理中...)')
                        
                        add_log_entry(task_id, '错误', error_msg)
                        
                        return {
                            'video': video_filename,
                            'status': 'failed',
                            'error': str(e),
                            'index': idx
                        }
                
                # 使用线程池并行处理视频
                with ThreadPoolExecutor(max_workers=MAX_WORKER_THREADS) as executor:
                    # 提交所有任务
                    future_to_video = {
                        executor.submit(process_single_video, (idx, video)): video 
                        for idx, video in enumerate(pending_videos)
                    }
                    
                    # 处理完成的任务
                    for future in as_completed(future_to_video):
                        video_info = future_to_video[future]
                        try:
                            result = future.result()
                            
                            # 线程安全地更新结果
                            with completed_lock:
                                pipeline_tasks[task_id]['results'].append(result)
                                
                        except Exception as e:
                            logger.error(f"获取任务结果失败: {e}")
                            with completed_lock:
                                failed_count += 1
                
                # 完成
                update_pipeline_progress(task_id, '完成', 100, 
                                       f'批量并行处理完成！成功: {processed_count}, 失败: {failed_count}')
                pipeline_tasks[task_id]['status'] = 'completed'
                pipeline_tasks[task_id]['progress'] = 100
                
                # 记录操作日志
                with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
                    collections = json.load(f)
                collection = next((c for c in collections if c.get('id') == collection_id), None)
                collection_name = f"{collection.get('template_name', '')} - {collection.get('scene_name', '')}" if collection else f"采集任务 {collection_id}"
                
                record_operation_log(
                    'pipeline_batch_complete',
                    f'Pipeline批量处理完成: {collection_name}',
                    {
                        'collection_id': collection_id,
                        'collection_name': collection_name,
                        'processed_count': processed_count,
                        'failed_count': failed_count,
                        'total_videos': total_videos
                    }
                )
                
                socketio.emit('pipeline_complete', {
                    'task_id': task_id,
                    'collection_id': collection_id,
                    'processed_count': processed_count,
                    'failed_count': failed_count,
                    'total_videos': total_videos
                })
                
            except Exception as e:
                pipeline_tasks[task_id]['status'] = 'failed'
                pipeline_tasks[task_id]['error'] = str(e)
                pipeline_tasks[task_id]['message'] = f'批量处理失败: {str(e)}'
                socketio.emit('pipeline_error', {
                    'task_id': task_id,
                    'error': str(e)
                })
        
        thread = threading.Thread(target=run_batch_pipeline)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'collection_id': collection_id,
            'total_videos': len(pending_videos),
            'total_all_videos': len(videos),
            'message': f'Pipeline已启动，将处理 {len(pending_videos)} 个未完成的视频（共 {len(videos)} 个视频）'
        })
        
    except Exception as e:
        logger.error(f"启动Pipeline失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def add_log_entry(task_id, step, message):
    """添加日志条目"""
    if task_id in pipeline_tasks:
        log_entry = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'step': step,
            'message': message
        }
        # 检查最后一条日志是否相同
        if not pipeline_tasks[task_id]['logs'] or \
           pipeline_tasks[task_id]['logs'][-1]['message'] != message:
            pipeline_tasks[task_id]['logs'].append(log_entry)

@app.route('/api/pipeline/status/<task_id>', methods=['GET'])
def get_pipeline_status(task_id):
    """获取Pipeline任务状态"""
    if task_id not in pipeline_tasks:
        return jsonify({'success': False, 'error': '任务不存在'}), 404
    
    return jsonify({
        'success': True,
        'task': pipeline_tasks[task_id]
    })

@app.route('/api/pipeline/progress/<int:collection_id>', methods=['GET'])
def get_pipeline_progress(collection_id):
    """获取采集任务的标注进度（实时刷新）"""
    try:
        videos = []
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        collection = next((c for c in collections if c.get('id') == collection_id), None)
        if not collection:
            return jsonify({'success': False, 'error': '采集任务不存在'}), 404
        
        folder_path = collection.get('folder_path')
        if folder_path and os.path.exists(folder_path):
            videos = scan_videos(folder_path)
        
        # 加载标注文件
        annotations = load_annotations(collection_id)
        
        # 统计进度
        total_count = len(videos)
        processed_count = sum(1 for ann in annotations if ann.get('result_data') is not None)
        verified_count = sum(1 for ann in annotations if ann.get('verified', False))
        
        return jsonify({
            'success': True,
            'collection_id': collection_id,
            'total_count': total_count,
            'processed_count': processed_count,
            'verified_count': verified_count,
            'progress': int((processed_count / total_count * 100)) if total_count > 0 else 0,
            'verified_progress': int((verified_count / total_count * 100)) if total_count > 0 else 0
        })
    except Exception as e:
        logger.error(f"获取标注进度失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== 历史记录 API ====================
@app.route('/api/history/collections', methods=['GET'])
def get_collections_history():
    """获取采集任务历史记录（实时刷新，从annotations.json读取进度）"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        result = []
        for col in collections:
            collection_id = col.get('id')
            videos = scan_videos(col.get('folder_path', ''))
            
            # 加载标注文件
            annotations = load_annotations(collection_id)
            
            # 统计已处理的视频数量（result_data 不为 None）
            processed_count = sum(1 for ann in annotations if ann.get('result_data') is not None)
            
            # 计算每个视频的处理状态
            video_list = []
            annotations_file = get_annotations_file_path(collection_id)
            file_mtime = datetime.fromtimestamp(os.path.getmtime(annotations_file)).strftime('%Y-%m-%d %H:%M:%S') if os.path.exists(annotations_file) else None
            
            for video in videos:
                video_path = video['path']
                rel_video_path = get_relative_path(video_path)
                
                # 查找对应的标注条目
                ann_entry = None
                for ann in annotations:
                    ann_video_path = ann.get('input_video_path') or ann.get('video_path', '')
                    if paths_match(ann_video_path, rel_video_path) or paths_match(ann_video_path, video_path):
                        ann_entry = ann
                        break
                
                if ann_entry and ann_entry.get('result_data') is not None:
                    video_list.append({
                        **video,
                        'status': 'completed',
                        'progress': 100,
                        'result_file': os.path.relpath(annotations_file, PROJECT_ROOT),
                        'processed_at': file_mtime,
                        'verified': ann_entry.get('verified', False)
                    })
                else:
                    video_list.append({
                        **video,
                        'status': 'pending',
                        'progress': 0,
                        'result_file': None,
                        'processed_at': None,
                        'verified': False
                    })
            
            # 确定状态
            if processed_count == 0:
                status = "pending"
            elif processed_count == len(videos):
                status = "completed"
            else:
                status = "partial"
            
            result.append({
                'id': collection_id,
                'name': f"{col.get('template_name')} - {col.get('scene_name')}",
                'template_name': col.get('template_name'),
                'scene_name': col.get('scene_name'),
                'video_count': len(videos),
                'processed_count': processed_count,
                'status': status,
                'last_updated': col.get('created_at', ''),
                'videos': video_list
            })
        
        return jsonify({'success': True, 'collections': result})
    except Exception as e:
        logger.error(f"获取采集任务历史记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/annotations', methods=['GET'])
def get_annotations_history():
    """获取已生成的标注历史记录（从annotations.json读取）"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        result = []
        for col in collections:
            collection_id = col.get('id')
            annotations = load_annotations(collection_id)
            annotations_file = get_annotations_file_path(collection_id)
            
            if os.path.exists(annotations_file):
                created_at = datetime.fromtimestamp(os.path.getmtime(annotations_file)).strftime('%Y-%m-%d %H:%M:%S')
                
                for ann in annotations:
                    if ann.get('result_data') is not None:  # 只返回已完成的标注
                        video_path = ann.get('input_video_path') or ann.get('video_path', '')
                        result.append({
                            'result_file': os.path.relpath(annotations_file, PROJECT_ROOT),
                            'collection_id': collection_id,
                            'video_path': video_path,
                            'video_name': os.path.basename(video_path) if video_path else '未知视频',
                            'created_at': created_at,
                            'viewed_at': None,
                            'view_count': 0,
                            'file_exists': True,
                            'verified': ann.get('verified', False),
                            'verified_at': ann.get('verified_at')
                        })
        
        # 按创建时间排序
        result.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return jsonify({'success': True, 'annotations': result})
    except Exception as e:
        logger.error(f"获取标注历史记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/operation_logs', methods=['GET'])
def get_operation_logs():
    """获取操作日志"""
    try:
        logs = load_operation_logs()
        
        # 按时间倒序排列（最新的在前）
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # 限制返回数量，最多返回最近500条
        logs = logs[:500]
        
        return jsonify({'success': True, 'logs': logs, 'total': len(logs)})
    except Exception as e:
        logger.error(f"获取操作日志失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/viewed', methods=['GET'])
def get_viewed_annotations():
    """获取已查看的标注历史记录（已废弃，不再跟踪查看历史）"""
    # 不再跟踪查看历史，返回空列表
    return jsonify({'success': True, 'annotations': []})

@app.route('/api/annotation/collections', methods=['GET'])
def get_annotation_collections():
    """获取可用于标注检验的采集任务列表（从annotations.json读取）"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        result = []
        for col in collections:
            collection_id = col.get('id')
            annotations = load_annotations(collection_id)
            annotations_file = get_annotations_file_path(collection_id)
            
            # 获取该采集任务的所有标注文件（只包含已完成的）
            collection_annotations = []
            for ann in annotations:
                if ann.get('result_data') is not None:  # 只包含已完成的标注
                    video_path = ann.get('input_video_path') or ann.get('video_path', '')
                    collection_annotations.append({
                        'result_file': os.path.relpath(annotations_file, PROJECT_ROOT),
                        'video_path': video_path,
                        'video_name': os.path.basename(video_path) if video_path else '未知视频',
                        'created_at': datetime.fromtimestamp(os.path.getmtime(annotations_file)).strftime('%Y-%m-%d %H:%M:%S') if os.path.exists(annotations_file) else None,
                        'verified': ann.get('verified', False),
                        'verified_at': ann.get('verified_at'),
                        'file_exists': True
                    })
            
            # 统计验证进度
            total_count = len(collection_annotations)
            verified_count = sum(1 for ann in collection_annotations if ann.get('verified', False))
            
            if total_count > 0:
                result.append({
                    'id': collection_id,
                    'name': f"{col.get('template_name')} - {col.get('scene_name')}",
                    'template_name': col.get('template_name'),
                    'scene_name': col.get('scene_name'),
                    'total_annotations': total_count,
                    'verified_count': verified_count,
                    'annotations': collection_annotations
                })
        
        return jsonify({'success': True, 'collections': result})
    except Exception as e:
        logger.error(f"获取标注任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/annotation/verify', methods=['POST'])
def verify_annotation():
    """标记标注为已验证"""
    try:
        data = request.get_json()
        result_file = data.get('result_file')
        video_path = data.get('video_path')  # 新增：视频路径参数
        
        if not result_file:
            return jsonify({'success': False, 'error': '缺少result_file参数'}), 400
        
        # 处理文件路径（支持相对路径和绝对路径）
        if os.path.isabs(result_file):
            annotations_file = result_file
        else:
            annotations_file = os.path.join(PROJECT_ROOT, result_file)
        
        # 确保路径是有效的字符串
        if not annotations_file or not isinstance(annotations_file, str):
            return jsonify({'success': False, 'error': '无效的文件路径'}), 400
        
        # 检查annotations.json文件是否存在
        if not os.path.exists(annotations_file):
            return jsonify({'success': False, 'error': f'标注文件不存在: {annotations_file}'}), 404
        
        # 从文件路径推断collection_id
        collection_id = None
        rel_path = os.path.relpath(annotations_file, PROJECT_ROOT) if not os.path.isabs(annotations_file) else annotations_file
        if 'collection_' in rel_path:
            parts = rel_path.split(os.sep)
            for part in parts:
                if part.startswith('collection_'):
                    try:
                        collection_id = int(part.replace('collection_', ''))
                        break
                    except ValueError:
                        pass
        
        if collection_id is None:
            return jsonify({'success': False, 'error': '无法确定采集任务ID'}), 400
        
        # 读取并更新annotations.json文件
        try:
            annotations = load_annotations(collection_id)
            
            # 查找对应的条目
            rel_video_path = get_relative_path(video_path) if video_path else None
            found = False
            
            for ann in annotations:
                ann_video_path = ann.get('input_video_path') or ann.get('video_path', '')
                if (video_path and (paths_match(ann_video_path, rel_video_path) or paths_match(ann_video_path, video_path))) or \
                   (not video_path and ann.get('result_data') is not None):
                    # 添加验证状态
                    verified_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    ann['verified'] = True
                    ann['verified_at'] = verified_at
                    found = True
                    break
            
            if not found:
                return jsonify({'success': False, 'error': '未找到对应的标注条目'}), 404
            
            # 保存更新后的标注文件
            save_annotations_file(collection_id, annotations)
            
            logger.info(f"已更新annotations.json验证状态: {annotations_file}")
        except Exception as e:
            logger.error(f"更新annotations.json失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': f'更新标注文件失败: {str(e)}'}), 500
        
        # 记录操作日志
        video_name = os.path.basename(video_path) if video_path else "未知视频"
        record_operation_log(
            'verify_annotation',
            f'验证标注: {video_name}',
            {
                'result_file': result_file,
                'video_path': video_path,
                'video_name': video_name
            }
        )
        
        return jsonify({'success': True, 'message': '标注已标记为已验证'})
    except Exception as e:
        logger.error(f"标记标注验证失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== 标注工具 API ====================
@app.route('/pipeline_data.json')
def get_pipeline_data():
    """获取管道数据（从annotations.json读取单个视频的标注）"""
    try:
        # 检查是否有指定文件
        result_file = request.args.get('file', DATA_FILE)
        video_path = request.args.get('video_path')  # 新增：视频路径参数
        
        # 处理文件路径（支持相对路径和绝对路径）
        if result_file and result_file != DATA_FILE:
            if os.path.isabs(result_file):
                file_path = result_file
            else:
                file_path = os.path.join(PROJECT_ROOT, result_file)
        else:
            file_path = DATA_FILE
        
        # 确保路径是有效的字符串
        if not file_path or not isinstance(file_path, str):
            return jsonify({'error': '无效的文件路径'}), 400
        
        # 检查是否是 annotations.json 文件
        if file_path.endswith('annotations.json'):
            # 从 annotations.json 读取单个视频的数据
            # 从文件路径推断collection_id
            collection_id = None
            rel_path = os.path.relpath(file_path, PROJECT_ROOT) if not os.path.isabs(file_path) else file_path
            if 'collection_' in rel_path:
                parts = rel_path.split(os.sep)
                for part in parts:
                    if part.startswith('collection_'):
                        try:
                            collection_id = int(part.replace('collection_', ''))
                            break
                        except ValueError:
                            pass
            
            if collection_id is None:
                return jsonify({'error': '无法确定采集任务ID'}), 400
            
            # 加载标注文件
            annotations = load_annotations(collection_id)
            
            if video_path:
                # 返回指定视频的标注数据
                rel_video_path = get_relative_path(video_path)
                
                # 查找对应的条目
                for ann in annotations:
                    ann_video_path = ann.get('input_video_path') or ann.get('video_path', '')
                    if paths_match(ann_video_path, rel_video_path) or paths_match(ann_video_path, video_path):
                        return jsonify(ann)
                
                return jsonify({'error': '未找到对应的标注条目'}), 404
            else:
                # 返回第一个已完成的标注数据（兼容旧格式）
                for ann in annotations:
                    if ann.get('result_data') is not None:
                        return jsonify(ann)
                
                return jsonify({'error': '没有已完成的标注'}), 404
        else:
            # 旧格式：直接读取文件
            if not os.path.exists(file_path):
                return jsonify({'error': f'数据文件不存在: {file_path}'}), 404
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
    except Exception as e:
        logger.error(f"加载数据失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/save_annotations', methods=['POST'])
def save_annotations():
    """保存标注结果（更新annotations.json中的单个条目）"""
    try:
        request_data = request.get_json()
        if not request_data:
            return jsonify({'error': '没有接收到数据'}), 400
        
        # 兼容新旧两种格式：新格式包含 data 和 target_file，旧格式直接是数据
        if isinstance(request_data, dict) and 'data' in request_data:
            # 新格式：包含目标文件路径
            data = request_data['data']
            target_file = request_data.get('target_file')
            video_path = request_data.get('video_path')  # 新增：视频路径参数
        else:
            # 旧格式：直接是数据，保存到默认文件
            data = request_data
            target_file = None
            video_path = None
        
        # 确定保存的目标文件路径
        if target_file:
            # 如果指定了文件路径，保存到该文件
            # 处理相对路径和绝对路径
            if os.path.isabs(target_file):
                annotations_file = target_file
            else:
                # 相对路径，从项目根目录开始
                annotations_file = os.path.join(PROJECT_ROOT, target_file)
        else:
            # 没有指定文件，保存到默认文件
            annotations_file = DATA_FILE
        
        # 检查是否是 annotations.json 文件
        is_annotations_file = annotations_file.endswith('annotations.json')
        
        if is_annotations_file:
            # 更新 annotations.json 中的单个条目
            # 从文件路径推断collection_id
            collection_id = None
            rel_path = os.path.relpath(annotations_file, PROJECT_ROOT) if not os.path.isabs(annotations_file) else annotations_file
            if 'collection_' in rel_path:
                parts = rel_path.split(os.sep)
                for part in parts:
                    if part.startswith('collection_'):
                        try:
                            collection_id = int(part.replace('collection_', ''))
                            break
                        except ValueError:
                            pass
            
            if collection_id is None:
                return jsonify({'error': '无法确定采集任务ID'}), 400
            
            # 加载标注文件
            annotations = load_annotations(collection_id)
            project_root = PROJECT_ROOT
            
            def get_relative_path(path):
                """获取相对于项目根目录的路径"""
                if not path:
                    return path
                try:
                    abs_path = os.path.abspath(path)
                    if abs_path.startswith(project_root):
                        return os.path.relpath(abs_path, project_root)
                    return path
                except:
                    return path
            
            # 查找对应的条目
            ann_video_path = data.get('input_video_path') or data.get('video_path', '')
            if video_path:
                ann_video_path = video_path
            
            rel_video_path = get_relative_path(ann_video_path) if ann_video_path else None
            found = False
            
            for ann in annotations:
                existing_video_path = ann.get('input_video_path') or ann.get('video_path', '')
                if (rel_video_path and (paths_match(existing_video_path, rel_video_path) or paths_match(existing_video_path, ann_video_path))) or \
                   (not rel_video_path and ann.get('result_data') is not None):
                    # 检查是否更新了result_data（核心标注数据）
                    old_result_data = ann.get('result_data')
                    new_result_data = data.get('result_data')
                    result_data_changed = (old_result_data is not None and 
                                          new_result_data is not None and 
                                          old_result_data != new_result_data)
                    
                    # 更新条目
                    ann.update({
                        "input_video_path": rel_video_path or data.get('input_video_path'),
                        "video_path": get_relative_path(data.get('video_path')),
                        "audio_path": get_relative_path(data.get('audio_path')),
                        "last_image_path": get_relative_path(data.get('last_image_path')),
                        "last_image_path_absolute": data.get('last_image_path_absolute'),
                        "video_description": data.get('video_description'),
                        "result_data": new_result_data,
                        "objects": data.get('objects', []),
                        "image_dimensions": data.get('image_dimensions'),
                        "verified": False if result_data_changed else ann.get('verified', False)  # 如果result_data被更新，重置验证状态
                    })
                    
                    # 如果result_data被更新，清除验证时间戳
                    if result_data_changed:
                        ann.pop('verified_at', None)
                    
                    found = True
                    break
            
            if not found:
                return jsonify({'error': '未找到对应的标注条目'}), 404
            
            # 保存更新后的标注文件
            save_annotations_file(collection_id, annotations)
            
            logger.info(f"标注数据保存成功: {annotations_file}")
            
            # 记录操作日志
            video_name = os.path.basename(ann_video_path) if ann_video_path else "未知视频"
            record_operation_log(
                'save_annotation',
                f'保存标注: {video_name}',
                {
                    'saved_file': annotations_file,
                    'video_path': ann_video_path
                }
            )
            
            return jsonify({
                'success': True,
                'message': '标注结果保存成功',
                'saved_file': annotations_file
            })
        else:
            # 旧格式：直接保存到文件
            # 确保目录存在
            save_dir = os.path.dirname(annotations_file)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)
            
            # 直接保存到目标文件，不创建备份
            with open(annotations_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"标注数据保存成功: {annotations_file}")
            
            # 记录操作日志
            video_name = os.path.basename(annotations_file)
            record_operation_log(
                'save_annotation',
                f'保存标注: {video_name}',
                {
                    'saved_file': annotations_file
                }
            )
            
            return jsonify({
                'success': True,
                'message': '标注结果保存成功',
                'saved_file': annotations_file
            })
    except Exception as e:
        logger.error(f"保存标注数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/load_annotation/<path:filepath>')
def load_annotation(filepath):
    """加载指定的标注文件（从annotations.json读取单个视频的标注）"""
    try:
        # 处理相对路径和绝对路径
        if os.path.isabs(filepath):
            annotations_file = filepath
        else:
            annotations_file = os.path.join(PROJECT_ROOT, filepath)
        
        if not os.path.exists(annotations_file):
            return jsonify({'error': '文件不存在'}), 404
        
        # 从文件路径推断collection_id
        collection_id = None
        rel_path = os.path.relpath(annotations_file, PROJECT_ROOT) if not os.path.isabs(annotations_file) else annotations_file
        if 'collection_' in rel_path:
            parts = rel_path.split(os.sep)
            for part in parts:
                if part.startswith('collection_'):
                    try:
                        collection_id = int(part.replace('collection_', ''))
                        break
                    except ValueError:
                        pass
        
        if collection_id is None:
            return jsonify({'error': '无法确定采集任务ID'}), 400
        
        # 检查是否有指定视频路径参数
        video_path = request.args.get('video_path')
        
        # 加载标注文件
        annotations = load_annotations(collection_id)
        
        if video_path:
            # 返回指定视频的标注数据
            rel_video_path = get_relative_path(video_path)
            
            # 查找对应的条目
            for ann in annotations:
                ann_video_path = ann.get('input_video_path') or ann.get('video_path', '')
                if paths_match(ann_video_path, rel_video_path) or paths_match(ann_video_path, video_path):
                    return jsonify(ann)
            
            return jsonify({'error': '未找到对应的标注条目'}), 404
        else:
            # 返回第一个已完成的标注数据（兼容旧格式）
            for ann in annotations:
                if ann.get('result_data') is not None:
                    return jsonify(ann)
            
            return jsonify({'error': '没有已完成的标注'}), 404
        
    except Exception as e:
        logger.error(f"加载标注文件失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/images/<path:filename>')
def serve_image(filename):
    """提供图像文件服务"""
    try:
        import urllib.parse
        filename = urllib.parse.unquote(filename)
        
        possible_paths = [
            PROJECT_ROOT,
            os.path.join(PROJECT_ROOT, 'pipeline/outputs'),
            os.path.join(PROJECT_ROOT, 'pipeline/outputs/output_frames'),
        ]
        
        for path in possible_paths:
            full_path = os.path.join(path, filename)
            if os.path.exists(full_path) and os.path.isfile(full_path):
                return send_file(full_path)
        
        if os.path.isabs(filename) and os.path.exists(filename):
            return send_file(filename)
        
        relative_path = os.path.join(PROJECT_ROOT, filename)
        if os.path.exists(relative_path) and os.path.isfile(relative_path):
            return send_file(relative_path)
        
        return jsonify({'error': f'图像文件不存在: {filename}'}), 404
    except Exception as e:
        logger.error(f"提供图像文件失败: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== WebSocket事件 ====================
@socketio.on('connect')
def handle_connect():
    logger.info('客户端已连接')

@socketio.on('disconnect')
def handle_disconnect():
    logger.info('客户端已断开')

# ==================== 错误处理 ====================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '页面不存在'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': '服务器内部错误'}), 500

if __name__ == '__main__':
    print("🚀 启动统一Web应用服务器...")
    print("📋 访问地址: http://localhost:5000")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
