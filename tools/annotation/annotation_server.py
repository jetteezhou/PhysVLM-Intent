#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import json
import os
import sys
import logging
from datetime import datetime
import shutil

# 获取项目根目录路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 配置文件路径（相对于项目根目录）
DATA_FILE = os.path.join(PROJECT_ROOT, 'pipeline/outputs/pipeline_data.json')
BACKUP_DIR = os.path.join(PROJECT_ROOT, 'annotation_backups')
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'annotation_tool.html')

# 确保备份目录存在
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

@app.route('/')
def index():
    """返回标注工具页面"""
    return send_file(HTML_FILE)

@app.route('/pipeline_data.json')
def get_pipeline_data():
    """获取管道数据"""
    try:
        if not os.path.exists(DATA_FILE):
            return jsonify({'error': '数据文件不存在'}), 404
        
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info("成功加载管道数据")
        return jsonify(data)
    except Exception as e:
        logger.error(f"加载数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/save_annotations', methods=['POST'])
def save_annotations():
    """保存标注结果"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': '没有接收到数据'}), 400
        
        # 创建备份
        if os.path.exists(DATA_FILE):
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(BACKUP_DIR, f'pipeline_data_backup_{timestamp}.json')
            shutil.copy2(DATA_FILE, backup_file)
            logger.info(f"创建备份文件: {backup_file}")
        
        # 保存新数据
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 同时保存一份带时间戳的副本
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        annotated_file = os.path.join(BACKUP_DIR, f'annotated_data_{timestamp}.json')
        with open(annotated_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info("标注数据保存成功")
        return jsonify({
            'success': True, 
            'message': '标注结果保存成功',
            'backup_file': annotated_file
        })
        
    except Exception as e:
        logger.error(f"保存标注数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_annotations_history')
def get_annotations_history():
    """获取标注历史记录"""
    try:
        history = []
        if os.path.exists(BACKUP_DIR):
            for filename in os.listdir(BACKUP_DIR):
                if filename.startswith('annotated_data_') and filename.endswith('.json'):
                    filepath = os.path.join(BACKUP_DIR, filename)
                    stat = os.stat(filepath)
                    history.append({
                        'filename': filename,
                        'filepath': filepath,
                        'size': stat.st_size,
                        'modified_time': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })
        
        # 按修改时间排序
        history.sort(key=lambda x: x['modified_time'], reverse=True)
        
        return jsonify({'history': history})
        
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}")
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
        
        logger.info(f"成功加载标注文件: {filename}")
        return jsonify(data)
        
    except Exception as e:
        logger.error(f"加载标注文件失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export_annotations')
def export_annotations():
    """导出当前标注数据"""
    try:
        if not os.path.exists(DATA_FILE):
            return jsonify({'error': '数据文件不存在'}), 404
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        export_filename = f'exported_annotations_{timestamp}.json'
        
        return send_file(
            DATA_FILE,
            as_attachment=True,
            download_name=export_filename,
            mimetype='application/json'
        )
        
    except Exception as e:
        logger.error(f"导出标注数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset_annotations', methods=['POST'])
def reset_annotations():
    """重置标注数据到原始状态"""
    try:
        # 查找最早的备份文件
        backup_files = []
        if os.path.exists(BACKUP_DIR):
            for filename in os.listdir(BACKUP_DIR):
                if filename.startswith('pipeline_data_backup_') and filename.endswith('.json'):
                    filepath = os.path.join(BACKUP_DIR, filename)
                    stat = os.stat(filepath)
                    backup_files.append((filepath, stat.st_mtime))
        
        if not backup_files:
            return jsonify({'error': '没有找到备份文件'}), 404
        
        # 选择最早的备份文件
        backup_files.sort(key=lambda x: x[1])
        original_backup = backup_files[0][0]
        
        # 恢复原始数据
        shutil.copy2(original_backup, DATA_FILE)
        
        logger.info(f"从备份文件恢复数据: {original_backup}")
        return jsonify({
            'success': True,
            'message': '已重置到原始状态',
            'restored_from': original_backup
        })
        
    except Exception as e:
        logger.error(f"重置标注数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/images/<path:filename>')
def serve_image(filename):
    """提供图像文件服务"""
    try:
        # 支持多种可能的图像路径（相对于项目根目录）
        possible_paths = [
            PROJECT_ROOT,  # 项目根目录
            os.path.join(PROJECT_ROOT, 'pipeline/outputs'),  # 输出目录
            os.path.join(PROJECT_ROOT, 'test_data'),  # 测试数据目录
        ]
        
        for path in possible_paths:
            full_path = os.path.join(path, filename)
            if os.path.exists(full_path):
                return send_file(full_path)
        
        # 如果文件名包含路径，直接尝试访问
        if os.path.exists(filename):
            return send_file(filename)
        
        return jsonify({'error': '图像文件不存在'}), 404
        
    except Exception as e:
        logger.error(f"提供图像文件失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/validate_data')
def validate_data():
    """验证数据完整性"""
    try:
        if not os.path.exists(DATA_FILE):
            return jsonify({'valid': False, 'error': '数据文件不存在'})
        
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 检查必要字段
        required_fields = ['video_path', 'last_image_path', 'objects', 'image_dimensions']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            return jsonify({
                'valid': False, 
                'error': f'缺少必要字段: {", ".join(missing_fields)}'
            })
        
        # 检查图像文件是否存在
        image_exists = os.path.exists(data['last_image_path'])
        
        # 检查物品数据
        objects_valid = True
        object_errors = []
        
        for i, obj in enumerate(data['objects']):
            if 'pixel_coords' not in obj or 'description' not in obj:
                objects_valid = False
                object_errors.append(f'物品 {i+1} 缺少必要字段')
        
        return jsonify({
            'valid': missing_fields == [] and objects_valid,
            'image_exists': image_exists,
            'objects_count': len(data['objects']),
            'errors': object_errors,
            'image_path': data['last_image_path']
        })
        
    except Exception as e:
        logger.error(f"验证数据失败: {e}")
        return jsonify({'valid': False, 'error': str(e)})

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '页面不存在'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': '服务器内部错误'}), 500

if __name__ == '__main__':
    print("🚀 启动标注工具服务器...")
    print("📋 访问地址: http://localhost:5000")
    print("💾 数据文件: pipeline_data.json")
    print("📁 备份目录: annotation_backups/")
    print("=" * 50)
    
    # 检查数据文件是否存在
    if os.path.exists(DATA_FILE):
        print(f"✅ 找到数据文件: {DATA_FILE}")
    else:
        print(f"⚠️  数据文件不存在: {DATA_FILE}")
        print("   请先运行 asr_test.py 生成数据文件")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
