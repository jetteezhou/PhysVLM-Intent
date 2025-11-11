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
BACKUP_DIR = os.path.join(PROJECT_ROOT, 'annotation_backups')
DATA_FILE = os.path.join(PROJECT_ROOT, 'pipeline/outputs/pipeline_data.json')
HISTORY_FILE = os.path.join(PROJECT_ROOT, 'pipeline/outputs/history.json')  # 历史记录文件

VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v', '.webm'}

# 确保目录存在
for directory in [TASK_CONFIG_DIR, COLLECTION_BASE_DIR, BACKUP_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

# Pipeline任务状态存储
pipeline_tasks = {}  # {task_id: {status, progress, message, result, error}}

# 并行处理配置
MAX_WORKER_THREADS = 3  # 最大并行线程数，可根据API限流调整（建议3-5个）

# 历史记录数据结构
# {
#   "collections": {
#     collection_id: {
#       "collection_id": int,
#       "collection_name": str,
#       "video_count": int,
#       "processed_count": int,
#       "status": "pending|processing|completed|failed",
#       "last_updated": str,
#       "videos": {
#         video_path: {
#           "status": "pending|processing|completed|failed",
#           "progress": int,
#           "result_file": str,
#           "processed_at": str
#         }
#       }
#     }
#   },
#   "annotations": {
#     result_file: {
#       "collection_id": int,
#       "video_path": str,
#       "created_at": str,
#       "viewed_at": str,
#       "view_count": int
#     }
#   }
# }

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
    
    # 初始化历史记录文件
    if not os.path.exists(HISTORY_FILE):
        history_data = {
            "collections": {},
            "annotations": {},
            "operation_logs": []
        }
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
    else:
        # 确保operation_logs字段存在
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            if "operation_logs" not in history_data:
                history_data["operation_logs"] = []
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(history_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"初始化操作日志字段失败: {e}")

init_data_files()

# ==================== 历史记录管理函数 ====================
def load_history():
    """加载历史记录"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
                # 确保operation_logs字段存在
                if "operation_logs" not in history:
                    history["operation_logs"] = []
                return history
    except Exception as e:
        logger.error(f"加载历史记录失败: {e}")
    return {"collections": {}, "annotations": {}, "operation_logs": []}

def save_history(history_data):
    """保存历史记录"""
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存历史记录失败: {e}")

def update_collection_history(collection_id, updates):
    """更新采集任务历史记录"""
    history = load_history()
    if "collections" not in history:
        history["collections"] = {}
    
    if collection_id not in history["collections"]:
        history["collections"][str(collection_id)] = {
            "collection_id": collection_id,
            "collection_name": "",
            "video_count": 0,
            "processed_count": 0,
            "status": "pending",
            "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "videos": {}
        }
    
    history["collections"][str(collection_id)].update(updates)
    history["collections"][str(collection_id)]["last_updated"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    save_history(history)

def update_video_history(collection_id, video_path, updates):
    """更新视频处理历史记录"""
    history = load_history()
    if "collections" not in history:
        history["collections"] = {}
    
    if str(collection_id) not in history["collections"]:
        update_collection_history(collection_id, {})
    
    if "videos" not in history["collections"][str(collection_id)]:
        history["collections"][str(collection_id)]["videos"] = {}
    
    if video_path not in history["collections"][str(collection_id)]["videos"]:
        history["collections"][str(collection_id)]["videos"][video_path] = {
            "status": "pending",
            "progress": 0,
            "result_file": None,
            "processed_at": None
        }
    
    history["collections"][str(collection_id)]["videos"][video_path].update(updates)
    save_history(history)

def record_annotation_view(result_file, collection_id=None, video_path=None):
    """记录标注查看"""
    history = load_history()
    if "annotations" not in history:
        history["annotations"] = {}
    
    if result_file not in history["annotations"]:
        history["annotations"][result_file] = {
            "collection_id": collection_id,
            "video_path": video_path,
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "viewed_at": None,
            "view_count": 0,
            "verified": False,
            "verified_at": None
        }
    
    history["annotations"][result_file]["viewed_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    history["annotations"][result_file]["view_count"] = history["annotations"][result_file].get("view_count", 0) + 1
    
    # 确保verified字段存在
    if "verified" not in history["annotations"][result_file]:
        history["annotations"][result_file]["verified"] = False
        history["annotations"][result_file]["verified_at"] = None
    
    save_history(history)
    
    # 记录操作日志（仅在首次查看时记录）
    if history["annotations"][result_file]["view_count"] == 1:
        video_name = os.path.basename(history["annotations"][result_file].get("video_path", ""))
        record_operation_log(
            'view_annotation',
            f'查看标注: {video_name}',
            {
                'result_file': result_file,
                'video_path': history["annotations"][result_file].get("video_path"),
                'video_name': video_name
            }
        )

def record_operation_log(operation_type, description, details=None):
    """记录操作日志（仅记录成功的操作）"""
    try:
        history = load_history()
        if "operation_logs" not in history:
            history["operation_logs"] = []
        
        log_entry = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "operation_type": operation_type,
            "description": description,
            "details": details or {}
        }
        
        history["operation_logs"].append(log_entry)
        
        # 限制日志数量，保留最近1000条
        if len(history["operation_logs"]) > 1000:
            history["operation_logs"] = history["operation_logs"][-1000:]
        
        save_history(history)
    except Exception as e:
        logger.error(f"记录操作日志失败: {e}")

# ==================== 工具函数 ====================
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
        required_fields = ['name', 'scene_type', 'target_count', 'description']
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
            'scene_type': data['scene_type'],
            'target_count': int(data['target_count']),
            'description': data['description'],
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
        if 'scene_type' in data:
            templates[template_index]['scene_type'] = data['scene_type']
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
        
        # 更新历史记录中的视频数量
        update_collection_history(collection_id, {
            "video_count": len(videos)
        })
        
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

# ==================== Pipeline API ====================
@app.route('/api/pipeline/collections', methods=['GET'])
def get_pipeline_collections():
    """获取可用于Pipeline的采集任务列表，包含历史记录信息"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        history = load_history()
        
        result = []
        for col in collections:
            collection_id = col.get('id')
            videos = scan_videos(col.get('folder_path', ''))
            
            # 获取历史记录
            collection_history = history.get("collections", {}).get(str(collection_id), {})
            processed_count = collection_history.get("processed_count", 0)
            status = collection_history.get("status", "pending")
            
            # 计算每个视频的处理状态
            video_statuses = {}
            if str(collection_id) in history.get("collections", {}):
                video_statuses = history["collections"][str(collection_id)].get("videos", {})
            
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
                'last_updated': collection_history.get('last_updated', col.get('created_at', ''))
            })
        
        return jsonify({'success': True, 'collections': result})
    except Exception as e:
        logger.error(f"获取采集任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pipeline/start', methods=['POST'])
def start_pipeline():
    """启动Pipeline处理 - 以采集任务文件夹为单位批量处理"""
    try:
        data = request.get_json()
        collection_id = data.get('collection_id')
        
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
        
        # 生成任务ID
        task_id = f"task_{collection_id}_{int(time.time() * 1000)}"
        
        # 初始化采集任务历史记录
        collection_name = f"{collection.get('template_name')} - {collection.get('scene_name')}"
        update_collection_history(collection_id, {
            "collection_name": collection_name,
            "video_count": len(videos),
            "processed_count": 0,
            "status": "processing"
        })
        
        # 初始化任务状态
        pipeline_tasks[task_id] = {
            'collection_id': collection_id,
            'status': 'running',
            'progress': 0,
            'current_step': '初始化',
            'message': f'准备处理 {len(videos)} 个视频...',
            'current_video': None,
            'current_video_index': 0,
            'total_videos': len(videos),
            'logs': [],
            'results': [],
            'error': None
        }
        
        # 在后台线程中批量处理视频（并行处理）
        def run_batch_pipeline():
            try:
                total_videos = len(videos)
                processed_count = 0
                failed_count = 0
                completed_lock = threading.Lock()  # 用于线程安全的计数
                
                update_pipeline_progress(task_id, '准备', 0, f'开始并行处理采集任务，共 {total_videos} 个视频（最大并行数: {MAX_WORKER_THREADS}）')
                
                # 处理单个视频的函数
                def process_single_video(video_info):
                    """处理单个视频"""
                    idx, video = video_info
                    video_path = video['path']
                    video_filename = video['filename']
                    
                    try:
                        # 更新视频历史记录 - 开始处理
                        update_video_history(collection_id, video_path, {
                            "status": "processing",
                            "progress": 10
                        })
                        
                        # 为每个视频生成独立的输出文件
                        video_name = os.path.splitext(video_filename)[0]
                        output_file = os.path.join(
                            PROJECT_ROOT, 
                            'pipeline/outputs', 
                            f'collection_{collection_id}',
                            f'{video_name}_pipeline_data.json'
                        )
                        
                        # 确保输出目录存在
                        output_dir = os.path.dirname(output_file)
                        os.makedirs(output_dir, exist_ok=True)
                        
                        # 创建Pipeline实例（每个线程独立实例，避免冲突）
                        config = Config.from_env()
                        pipeline = IntentLabelPipeline(config)
                        
                        # 处理视频
                        result = pipeline.process(video_path, output_file=output_file)
                        
                        # 更新视频历史记录 - 完成
                        update_video_history(collection_id, video_path, {
                            "status": "completed",
                            "progress": 100,
                            "result_file": output_file,
                            "processed_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        })
                        
                        # 记录标注文件
                        history = load_history()
                        if "annotations" not in history:
                            history["annotations"] = {}
                        history["annotations"][output_file] = {
                            "collection_id": collection_id,
                            "video_path": video_path,
                            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            "viewed_at": None,
                            "view_count": 0
                        }
                        save_history(history)
                        
                        # 记录操作日志
                        record_operation_log(
                            'generate_annotation',
                            f'生成标注: {video_filename}',
                            {
                                'collection_id': collection_id,
                                'video_path': video_path,
                                'video_name': video_filename,
                                'result_file': output_file
                            }
                        )
                        
                        # 线程安全地更新计数
                        with completed_lock:
                            nonlocal processed_count
                            processed_count += 1
                            update_collection_history(collection_id, {
                                "processed_count": processed_count
                            })
                        
                        return {
                            'video': video_filename,
                            'status': 'completed',
                            'result_file': output_file,
                            'index': idx
                        }
                        
                    except Exception as e:
                        error_msg = f'处理视频 {video_filename} 失败: {str(e)}'
                        logger.error(error_msg)
                        
                        update_video_history(collection_id, video_path, {
                            "status": "failed",
                            "progress": 0
                        })
                        
                        # 线程安全地更新失败计数
                        with completed_lock:
                            nonlocal failed_count
                            failed_count += 1
                        
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
                        for idx, video in enumerate(videos)
                    }
                    
                    # 处理完成的任务
                    for future in as_completed(future_to_video):
                        video_info = future_to_video[future]
                        try:
                            result = future.result()
                            
                            # 线程安全地更新结果和计数
                            with completed_lock:
                                pipeline_tasks[task_id]['results'].append(result)
                                
                                # 更新进度（使用线程安全后的计数）
                                current_total = processed_count + failed_count
                                progress = int((current_total / total_videos) * 100)
                                
                                if result['status'] == 'completed':
                                    update_pipeline_progress(task_id, '处理视频', progress,
                                                           f'视频 {current_total}/{total_videos} 处理完成 (并行处理中...)')
                                else:
                                    update_pipeline_progress(task_id, '处理视频', progress,
                                                           f'视频 {current_total}/{total_videos} 处理失败 (并行处理中...)')
                                
                        except Exception as e:
                            logger.error(f"获取任务结果失败: {e}")
                            with completed_lock:
                                failed_count += 1
                
                # 更新采集任务历史记录
                update_collection_history(collection_id, {
                    "processed_count": processed_count,
                    "status": "completed" if failed_count == 0 else "partial"
                })
                
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
                update_collection_history(collection_id, {
                    "status": "failed"
                })
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
            'total_videos': len(videos),
            'message': f'Pipeline已启动，将处理 {len(videos)} 个视频'
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

# ==================== 历史记录 API ====================
@app.route('/api/history/collections', methods=['GET'])
def get_collections_history():
    """获取采集任务历史记录（实时刷新）"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        history = load_history()
        
        result = []
        for col in collections:
            collection_id = col.get('id')
            videos = scan_videos(col.get('folder_path', ''))
            
            # 获取历史记录
            collection_history = history.get("collections", {}).get(str(collection_id), {})
            
            result.append({
                'id': collection_id,
                'name': f"{col.get('template_name')} - {col.get('scene_name')}",
                'template_name': col.get('template_name'),
                'scene_name': col.get('scene_name'),
                'video_count': len(videos),
                'processed_count': collection_history.get("processed_count", 0),
                'status': collection_history.get("status", "pending"),
                'last_updated': collection_history.get('last_updated', col.get('created_at', '')),
                'videos': [
                    {
                        **video,
                        'status': collection_history.get("videos", {}).get(video['path'], {}).get("status", "pending"),
                        'progress': collection_history.get("videos", {}).get(video['path'], {}).get("progress", 0),
                        'result_file': collection_history.get("videos", {}).get(video['path'], {}).get("result_file"),
                        'processed_at': collection_history.get("videos", {}).get(video['path'], {}).get("processed_at")
                    }
                    for video in videos
                ]
            })
        
        return jsonify({'success': True, 'collections': result})
    except Exception as e:
        logger.error(f"获取采集任务历史记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/annotations', methods=['GET'])
def get_annotations_history():
    """获取已生成的标注历史记录"""
    try:
        history = load_history()
        annotations = history.get("annotations", {})
        
        result = []
        for result_file, info in annotations.items():
            if os.path.exists(result_file):
                result.append({
                    'result_file': result_file,
                    'collection_id': info.get('collection_id'),
                    'video_path': info.get('video_path'),
                    'video_name': os.path.basename(info.get('video_path', '')),
                    'created_at': info.get('created_at'),
                    'viewed_at': info.get('viewed_at'),
                    'view_count': info.get('view_count', 0),
                    'file_exists': True
                })
            else:
                result.append({
                    'result_file': result_file,
                    'collection_id': info.get('collection_id'),
                    'video_path': info.get('video_path'),
                    'video_name': os.path.basename(info.get('video_path', '')),
                    'created_at': info.get('created_at'),
                    'viewed_at': info.get('viewed_at'),
                    'view_count': info.get('view_count', 0),
                    'file_exists': False
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
        history = load_history()
        logs = history.get("operation_logs", [])
        
        # 按时间倒序排列（最新的在前）
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # 限制返回数量，最多返回最近500条
        logs = logs[:500]
        
        return jsonify({'success': True, 'logs': logs, 'total': len(history.get("operation_logs", []))})
    except Exception as e:
        logger.error(f"获取操作日志失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/history/viewed', methods=['GET'])
def get_viewed_annotations():
    """获取已查看的标注历史记录"""
    try:
        history = load_history()
        annotations = history.get("annotations", {})
        
        result = []
        for result_file, info in annotations.items():
            if info.get('viewed_at'):
                if os.path.exists(result_file):
                    result.append({
                        'result_file': result_file,
                        'collection_id': info.get('collection_id'),
                        'video_path': info.get('video_path'),
                        'video_name': os.path.basename(info.get('video_path', '')),
                        'created_at': info.get('created_at'),
                        'viewed_at': info.get('viewed_at'),
                        'view_count': info.get('view_count', 0)
                    })
        
        # 按查看时间排序
        result.sort(key=lambda x: x.get('viewed_at', ''), reverse=True)
        
        return jsonify({'success': True, 'annotations': result})
    except Exception as e:
        logger.error(f"获取已查看标注历史记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/annotation/collections', methods=['GET'])
def get_annotation_collections():
    """获取可用于标注检验的采集任务列表（包含标注文件）"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        history = load_history()
        annotations = history.get("annotations", {})
        
        result = []
        for col in collections:
            collection_id = col.get('id')
            
            # 获取该采集任务的所有标注文件
            collection_annotations = [
                {
                    'result_file': result_file,
                    'video_path': info.get('video_path'),
                    'video_name': os.path.basename(info.get('video_path', '')),
                    'created_at': info.get('created_at'),
                    'viewed_at': info.get('viewed_at'),
                    'view_count': info.get('view_count', 0),
                    'verified': info.get('verified', False),
                    'verified_at': info.get('verified_at'),
                    'file_exists': os.path.exists(result_file)
                }
                for result_file, info in annotations.items()
                if info.get('collection_id') == collection_id and os.path.exists(result_file)
            ]
            
            # 统计验证进度
            total_count = len(collection_annotations)
            verified_count = sum(1 for ann in collection_annotations if ann.get('verified', False))
            
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
        
        if not result_file:
            return jsonify({'success': False, 'error': '缺少result_file参数'}), 400
        
        history = load_history()
        if "annotations" not in history:
            history["annotations"] = {}
        
        if result_file not in history["annotations"]:
            return jsonify({'success': False, 'error': '标注文件不存在于历史记录中'}), 404
        
        history["annotations"][result_file]["verified"] = True
        history["annotations"][result_file]["verified_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        save_history(history)
        
        # 记录操作日志
        video_name = os.path.basename(history["annotations"][result_file].get("video_path", ""))
        record_operation_log(
            'verify_annotation',
            f'验证标注: {video_name}',
            {
                'result_file': result_file,
                'video_path': history["annotations"][result_file].get("video_path"),
                'video_name': video_name
            }
        )
        
        return jsonify({'success': True, 'message': '标注已标记为已验证'})
    except Exception as e:
        logger.error(f"标记标注验证失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== 标注工具 API ====================
@app.route('/pipeline_data.json')
def get_pipeline_data():
    """获取管道数据（记录查看历史）"""
    try:
        # 检查是否有指定文件
        result_file = request.args.get('file', DATA_FILE)
        
        if not os.path.exists(result_file):
            return jsonify({'error': '数据文件不存在'}), 404
        
        # 记录查看历史
        record_annotation_view(result_file)
        
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        logger.error(f"加载数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/save_annotations', methods=['POST'])
def save_annotations():
    """保存标注结果"""
    try:
        request_data = request.get_json()
        if not request_data:
            return jsonify({'error': '没有接收到数据'}), 400
        
        # 兼容新旧两种格式：新格式包含 data 和 target_file，旧格式直接是数据
        if isinstance(request_data, dict) and 'data' in request_data:
            # 新格式：包含目标文件路径
            data = request_data['data']
            target_file = request_data.get('target_file')
        else:
            # 旧格式：直接是数据，保存到默认文件
            data = request_data
            target_file = None
        
        # 确定保存的目标文件路径
        if target_file:
            # 如果指定了文件路径，保存到该文件
            # 处理相对路径和绝对路径
            if os.path.isabs(target_file):
                save_file = target_file
            else:
                # 相对路径，从项目根目录开始
                save_file = os.path.join(PROJECT_ROOT, target_file)
        else:
            # 没有指定文件，保存到默认文件
            save_file = DATA_FILE
        
        # 确保目录存在
        save_dir = os.path.dirname(save_file)
        if save_dir and not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)
        
        # 创建备份（如果文件存在）
        if os.path.exists(save_file):
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(BACKUP_DIR, f'pipeline_data_backup_{timestamp}.json')
            shutil.copy2(save_file, backup_file)
            logger.info(f"创建备份文件: {backup_file}")
        
        # 保存到目标文件
        with open(save_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"标注数据保存成功: {save_file}")
        
        # 同时保存一份带时间戳的副本到备份目录
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        annotated_file = os.path.join(BACKUP_DIR, f'annotated_data_{timestamp}.json')
        with open(annotated_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 记录操作日志
        video_name = os.path.basename(save_file)
        record_operation_log(
            'save_annotation',
            f'保存标注: {video_name}',
            {
                'saved_file': save_file,
                'backup_file': annotated_file
            }
        )
        
        return jsonify({
            'success': True,
            'message': '标注结果保存成功',
            'saved_file': save_file,
            'backup_file': annotated_file
        })
    except Exception as e:
        logger.error(f"保存标注数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/load_annotation/<filename>')
def load_annotation(filename):
    """加载指定的标注文件"""
    try:
        filepath = os.path.join(BACKUP_DIR, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': '文件不存在'}), 404
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
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
