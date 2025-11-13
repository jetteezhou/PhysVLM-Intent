#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import os
import sys
import logging
from datetime import datetime
import shutil
from pathlib import Path

# 获取项目根目录路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 配置文件路径（位于 tools/data_collection/task_config）
TASK_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'task_config')
TEMPLATES_FILE = os.path.join(TASK_CONFIG_DIR, 'templates.json')
SCENES_FILE = os.path.join(TASK_CONFIG_DIR, 'scenes.json')
COLLECTIONS_FILE = os.path.join(TASK_CONFIG_DIR, 'collections.json')
# 采集数据存储目录（位于 tools/data_collection/datas）
COLLECTION_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'datas')
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collection_tool.html')

# 支持的视频格式
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.m4v', '.webm'}

# 确保目录存在
for directory in [TASK_CONFIG_DIR, COLLECTION_BASE_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)
        logger.info(f"创建目录: {directory}")

# 初始化数据文件
def init_data_files():
    """初始化数据文件"""
    if not os.path.exists(TEMPLATES_FILE):
        with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    
    if not os.path.exists(SCENES_FILE):
        with open(SCENES_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    
    if not os.path.exists(COLLECTIONS_FILE):
        with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)

init_data_files()

@app.route('/')
def index():
    """返回数据采集工具页面"""
    return send_file(HTML_FILE)

# ==================== 管理员模式 API ====================

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
        
        # 检查名称是否重复
        if any(t.get('name') == data['name'] for t in templates):
            return jsonify({'success': False, 'error': '任务模板名称已存在'}), 400
        
        # 添加ID和时间戳
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
        
        logger.info(f"创建任务模板: {data['name']}")
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
        
        # 更新字段
        if 'name' in data:
            templates[template_index]['name'] = data['name']
        if 'target_count' in data:
            templates[template_index]['target_count'] = int(data['target_count'])
        if 'description' in data:
            templates[template_index]['description'] = data['description']
        
        templates[template_index]['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
        
        logger.info(f"更新任务模板: {template_id}")
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
        
        logger.info(f"删除任务模板: {template_id}")
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
        
        # 检查名称是否重复
        if any(s.get('name') == data['name'] for s in scenes):
            return jsonify({'success': False, 'error': '场景类型名称已存在'}), 400
        
        # 添加ID和时间戳
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
        
        logger.info(f"创建场景类型: {data['name']}")
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
        
        # 更新字段
        if 'name' in data:
            scenes[scene_index]['name'] = data['name']
        if 'description' in data:
            scenes[scene_index]['description'] = data['description']
        
        scenes[scene_index]['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(SCENES_FILE, 'w', encoding='utf-8') as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)
        
        logger.info(f"更新场景类型: {scene_id}")
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
        
        logger.info(f"删除场景类型: {scene_id}")
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"删除场景类型失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== 采集模式 API ====================

@app.route('/api/collection/create', methods=['POST'])
def create_collection():
    """创建采集任务"""
    try:
        data = request.get_json()
        
        if 'template_id' not in data or 'scene_id' not in data:
            return jsonify({'success': False, 'error': '缺少必要字段: template_id 或 scene_id'}), 400
        
        # 读取模板和场景信息
        with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            templates = json.load(f)
        
        with open(SCENES_FILE, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        
        template = next((t for t in templates if t.get('id') == data['template_id']), None)
        scene = next((s for s in scenes if s.get('id') == data['scene_id']), None)
        
        if not template:
            return jsonify({'success': False, 'error': '任务模板不存在'}), 404
        if not scene:
            return jsonify({'success': False, 'error': '场景类型不存在'}), 404
        
        # 生成采集文件夹路径并创建文件夹
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        folder_name = f"{template['name']}_{scene['name']}_{timestamp}"
        collection_dir = os.path.join(COLLECTION_BASE_DIR, folder_name)
        
        # 如果文件夹已存在，返回错误
        if os.path.exists(collection_dir):
            return jsonify({'success': False, 'error': '采集文件夹已存在'}), 400
        
        # 创建采集文件夹
        try:
            os.makedirs(collection_dir)
            logger.info(f"创建采集文件夹: {collection_dir}")
        except Exception as e:
            logger.error(f"创建采集文件夹失败: {e}")
            return jsonify({'success': False, 'error': f'创建文件夹失败: {str(e)}'}), 500
        
        # 创建采集任务记录
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
        
        logger.info(f"创建采集任务: {folder_name}")
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
        
        # 更新每个任务的视频统计
        for collection in collections:
            collection_dir = collection.get('folder_path')
            if collection_dir and os.path.exists(collection_dir):
                videos = scan_videos(collection_dir)
                collection['current_count'] = len(videos)
                collection['videos'] = videos
        
        # 保存更新后的数据
        with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(collections, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'collections': collections})
        
    except Exception as e:
        logger.error(f"获取采集任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/collection/<int:collection_id>/scan', methods=['POST'])
def scan_collection(collection_id):
    """扫描采集文件夹中的视频文件"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        collection = next((c for c in collections if c.get('id') == collection_id), None)
        if not collection:
            return jsonify({'success': False, 'error': '采集任务不存在'}), 404
        
        collection_dir = collection.get('folder_path')
        if not collection_dir:
            return jsonify({'success': False, 'error': '采集文件夹路径不存在'}), 404
        
        # 如果文件夹不存在，返回空列表
        if not os.path.exists(collection_dir):
            videos = []
        else:
            videos = scan_videos(collection_dir)
        
        # 更新采集任务
        collection['current_count'] = len(videos)
        collection['videos'] = videos
        
        # 保存更新
        collection_index = next((i for i, c in enumerate(collections) if c.get('id') == collection_id), None)
        if collection_index is not None:
            collections[collection_index] = collection
            with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(collections, f, ensure_ascii=False, indent=2)
        
        logger.info(f"扫描采集任务 {collection_id}: 找到 {len(videos)} 个视频文件")
        return jsonify({
            'success': True,
            'videos': videos,
            'count': len(videos),
            'target_count': collection.get('target_count', 0)
        })
        
    except Exception as e:
        logger.error(f"扫描采集文件夹失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/collection/<int:collection_id>', methods=['GET'])
def get_collection(collection_id):
    """获取采集任务详情"""
    try:
        with open(COLLECTIONS_FILE, 'r', encoding='utf-8') as f:
            collections = json.load(f)
        
        collection = next((c for c in collections if c.get('id') == collection_id), None)
        if not collection:
            return jsonify({'success': False, 'error': '采集任务不存在'}), 404
        
        # 扫描视频文件（如果文件夹存在）
        collection_dir = collection.get('folder_path')
        if collection_dir and os.path.exists(collection_dir):
            videos = scan_videos(collection_dir)
            collection['current_count'] = len(videos)
            collection['videos'] = videos
        else:
            collection['current_count'] = 0
            collection['videos'] = []
        
        return jsonify({'success': True, 'collection': collection})
        
    except Exception as e:
        logger.error(f"获取采集任务详情失败: {e}")
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
        
        logger.info(f"完成采集任务: {collection_id}")
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
        folder_existed = False
        
        # 删除文件夹（如果存在）
        if folder_path and os.path.exists(folder_path):
            folder_existed = True
            try:
                shutil.rmtree(folder_path)
                logger.info(f"删除采集文件夹: {folder_path}")
            except Exception as e:
                logger.warning(f"删除文件夹失败: {e}，继续删除任务记录")
        
        # 从列表中删除任务记录
        collections.pop(collection_index)
        
        # 保存更新后的列表
        with open(COLLECTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(collections, f, ensure_ascii=False, indent=2)
        
        logger.info(f"删除采集任务: {collection_id}")
        return jsonify({
            'success': True,
            'message': '采集任务及相关数据已删除',
            'deleted_folder': folder_path if folder_existed else None
        })
        
    except Exception as e:
        logger.error(f"删除采集任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/videos/<path:filename>')
def serve_video(filename):
    """提供视频文件服务"""
    try:
        # filename可能是相对路径（如：folder_name/video.mp4）或纯文件名
        # 先尝试作为相对路径查找
        file_path = os.path.join(COLLECTION_BASE_DIR, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return send_file(file_path)
        
        # 如果没找到，遍历所有子目录查找同名文件
        for root, dirs, files in os.walk(COLLECTION_BASE_DIR):
            # 只匹配文件名部分
            base_filename = os.path.basename(filename)
            if base_filename in files:
                full_path = os.path.join(root, base_filename)
                if os.path.exists(full_path):
                    return send_file(full_path)
        
        return jsonify({'error': '视频文件不存在'}), 404
        
    except Exception as e:
        logger.error(f"提供视频文件失败: {e}")
        return jsonify({'error': str(e)}), 500

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
    
    # 按文件名排序
    videos.sort(key=lambda x: x['filename'])
    return videos

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '页面不存在'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': '服务器内部错误'}), 500

if __name__ == '__main__':
    print("🚀 启动数据采集工具服务器...")
    print("📋 访问地址: http://localhost:5001")
    print("📁 配置目录: tools/data_collection/task_config/")
    print("📁 采集目录: tools/data_collection/datas/")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5001, debug=True)

