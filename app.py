"""
Flask 后端 API
"""
import os
import csv
import shutil
from io import StringIO
from flask import Flask, jsonify, request, send_file, Response
from flask_cors import CORS
from dotenv import load_dotenv
from database import Database

load_dotenv()

app = Flask(__name__)
CORS(app)

# 配置
IMAGES_DIR = os.getenv('IMAGES_DIR', './images')
LABELED_DIR = os.getenv('LABELED_DIR', './labeled')
DATABASE_PATH = os.getenv('DATABASE_PATH', './labels.db')

# 确保目录存在
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(LABELED_DIR, exist_ok=True)

# 初始化数据库
db = Database(DATABASE_PATH)

# 加载预置数据
data_dir = os.path.join(os.path.dirname(__file__), 'data')
db.load_preset_data(data_dir)

# 支持的图片格式
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}


def is_image_file(filename: str) -> bool:
    """检查是否是图片文件"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in IMAGE_EXTENSIONS


# ==================== 图片相关 API ====================

@app.route('/api/images', methods=['GET'])
def get_images():
    """获取待标注图片列表（排除已标注的和被他人锁定的）"""
    user_id = request.args.get('user_id', '')
    labeled_files = db.get_labeled_original_filenames()
    locked_files = db.get_locked_filenames()

    images = []
    if os.path.exists(IMAGES_DIR):
        for filename in os.listdir(IMAGES_DIR):
            if is_image_file(filename) and filename not in labeled_files:
                # 检查是否被锁定（排除自己锁定的）
                lock_info = db.get_lock_info(filename)
                is_locked_by_others = lock_info and lock_info['user_id'] != user_id

                images.append({
                    'filename': filename,
                    'path': f'/api/images/{filename}',
                    'locked': is_locked_by_others,
                    'locked_by': lock_info['user_id'] if is_locked_by_others else None
                })

    # 按文件名排序
    images.sort(key=lambda x: x['filename'])

    return jsonify({
        'total': len(images),
        'items': images
    })


@app.route('/api/images/<filename>', methods=['GET'])
def get_image(filename: str):
    """获取图片文件"""
    file_path = os.path.join(IMAGES_DIR, filename)
    if os.path.exists(file_path) and is_image_file(filename):
        return send_file(file_path)
    return jsonify({'error': '图片不存在'}), 404


@app.route('/api/labeled-images/<filename>', methods=['GET'])
def get_labeled_image(filename: str):
    """获取已标注的图片文件"""
    file_path = os.path.join(LABELED_DIR, filename)
    if os.path.exists(file_path) and is_image_file(filename):
        return send_file(file_path)
    return jsonify({'error': '图片不存在'}), 404


# ==================== 标注相关 API ====================

@app.route('/api/labels', methods=['GET'])
def get_labels():
    """获取已标注列表（分页）"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    result = db.get_labels(page, per_page)
    return jsonify(result)


@app.route('/api/labels/<int:label_id>', methods=['GET'])
def get_label(label_id: int):
    """获取单个标注记录"""
    label = db.get_label_by_id(label_id)
    if label:
        return jsonify(label)
    return jsonify({'error': '标注记录不存在'}), 404


@app.route('/api/labels', methods=['POST'])
def create_label():
    """创建标注记录"""
    data = request.get_json()

    # 验证必填字段
    required_fields = ['original_file_name', 'type_id', 'type_name',
                       'airline_id', 'airline_name', 'clarity', 'block',
                       'registration', 'airplane_area', 'registration_area']

    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'缺少必填字段: {field}'}), 400

    # 生成新文件名
    type_id = data['type_id']
    seq = db.get_next_sequence(type_id)
    original_ext = os.path.splitext(data['original_file_name'])[1]
    new_filename = f"{type_id}-{seq:04d}{original_ext}"

    # 移动并重命名图片
    src_path = os.path.join(IMAGES_DIR, data['original_file_name'])
    dst_path = os.path.join(LABELED_DIR, new_filename)

    if not os.path.exists(src_path):
        return jsonify({'error': '原始图片不存在'}), 404

    try:
        shutil.move(src_path, dst_path)
    except Exception as e:
        return jsonify({'error': f'移动图片失败: {str(e)}'}), 500

    # 保存到数据库
    data['file_name'] = new_filename
    try:
        result = db.add_label(data)
        return jsonify(result), 201
    except Exception as e:
        # 如果数据库保存失败，尝试恢复图片
        try:
            shutil.move(dst_path, src_path)
        except:
            pass
        return jsonify({'error': f'保存标注失败: {str(e)}'}), 500


@app.route('/api/labels/<int:label_id>', methods=['PUT'])
def update_label(label_id: int):
    """更新标注记录"""
    data = request.get_json()

    # 验证必填字段
    required_fields = ['type_id', 'type_name', 'airline_id', 'airline_name',
                       'clarity', 'block', 'registration',
                       'airplane_area', 'registration_area']

    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'缺少必填字段: {field}'}), 400

    success = db.update_label(label_id, data)
    if success:
        return jsonify({'message': '更新成功'})
    return jsonify({'error': '标注记录不存在'}), 404


@app.route('/api/labels/<int:label_id>', methods=['DELETE'])
def delete_label(label_id: int):
    """删除标注记录"""
    # 获取标注记录
    label = db.get_label_by_id(label_id)
    if not label:
        return jsonify({'error': '标注记录不存在'}), 404

    # 可选：删除已标注的图片文件
    # file_path = os.path.join(LABELED_DIR, label['file_name'])
    # if os.path.exists(file_path):
    #     os.remove(file_path)

    success = db.delete_label(label_id)
    if success:
        return jsonify({'message': '删除成功'})
    return jsonify({'error': '删除失败'}), 500


@app.route('/api/labels/export', methods=['GET'])
def export_labels():
    """导出标注数据为 CSV"""
    labels = db.get_all_labels_for_export()

    # 创建 CSV
    output = StringIO()
    writer = csv.writer(output)

    # 写入表头
    writer.writerow(['filename', 'typeid', 'typename', 'airlineid',
                     'airlinename', 'clarity', 'block', 'registration'])

    # 写入数据
    for label in labels:
        writer.writerow([
            label['file_name'],
            label['type_id'],
            label['type_name'],
            label['airline_id'],
            label['airline_name'],
            label['clarity'],
            label['block'],
            label['registration']
        ])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=labels.csv'}
    )


# ==================== 航司相关 API ====================

@app.route('/api/airlines', methods=['GET'])
def get_airlines():
    """获取航司列表"""
    airlines = db.get_airlines()
    return jsonify(airlines)


@app.route('/api/airlines', methods=['POST'])
def create_airline():
    """新增航司"""
    data = request.get_json()

    if not data.get('code') or not data.get('name'):
        return jsonify({'error': '缺少必填字段: code, name'}), 400

    try:
        airline_id = db.add_airline(data['code'], data['name'])
        return jsonify({'id': airline_id, 'code': data['code'], 'name': data['name']}), 201
    except Exception as e:
        return jsonify({'error': f'添加航司失败: {str(e)}'}), 400


# ==================== 机型相关 API ====================

@app.route('/api/aircraft-types', methods=['GET'])
def get_aircraft_types():
    """获取机型列表"""
    types = db.get_aircraft_types()
    return jsonify(types)


@app.route('/api/aircraft-types', methods=['POST'])
def create_aircraft_type():
    """新增机型"""
    data = request.get_json()

    if not data.get('code') or not data.get('name'):
        return jsonify({'error': '缺少必填字段: code, name'}), 400

    try:
        type_id = db.add_aircraft_type(data['code'], data['name'])
        return jsonify({'id': type_id, 'code': data['code'], 'name': data['name']}), 201
    except Exception as e:
        return jsonify({'error': f'添加机型失败: {str(e)}'}), 400


# ==================== 统计相关 API ====================

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取统计信息"""
    stats = db.get_stats()

    # 添加未标注数量
    labeled_files = db.get_labeled_original_filenames()
    unlabeled_count = 0
    if os.path.exists(IMAGES_DIR):
        for filename in os.listdir(IMAGES_DIR):
            if is_image_file(filename) and filename not in labeled_files:
                unlabeled_count += 1

    stats['unlabeled'] = unlabeled_count

    return jsonify(stats)


# ==================== 图片锁相关 API ====================

@app.route('/api/locks/acquire', methods=['POST'])
def acquire_lock():
    """获取图片锁"""
    data = request.get_json()
    filename = data.get('filename')
    user_id = data.get('user_id')

    if not filename or not user_id:
        return jsonify({'error': '缺少 filename 或 user_id'}), 400

    success = db.acquire_lock(filename, user_id)
    if success:
        return jsonify({'message': '锁定成功', 'filename': filename})
    else:
        lock_info = db.get_lock_info(filename)
        return jsonify({
            'error': '图片已被他人锁定',
            'locked_by': lock_info['user_id'] if lock_info else None
        }), 409


@app.route('/api/locks/release', methods=['POST'])
def release_lock():
    """释放图片锁"""
    data = request.get_json()
    filename = data.get('filename')
    user_id = data.get('user_id')

    if not filename or not user_id:
        return jsonify({'error': '缺少 filename 或 user_id'}), 400

    success = db.release_lock(filename, user_id)
    return jsonify({'message': '释放成功' if success else '无需释放', 'filename': filename})


@app.route('/api/locks/release-all', methods=['POST'])
def release_all_locks():
    """释放用户的所有锁（用于用户离开页面时）"""
    data = request.get_json()
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'error': '缺少 user_id'}), 400

    count = db.release_all_user_locks(user_id)
    return jsonify({'message': f'已释放 {count} 个锁', 'count': count})


@app.route('/api/locks/heartbeat', methods=['POST'])
def heartbeat():
    """心跳请求，刷新锁的过期时间"""
    data = request.get_json()
    filename = data.get('filename')
    user_id = data.get('user_id')

    if not filename or not user_id:
        return jsonify({'error': '缺少 filename 或 user_id'}), 400

    # acquire_lock 会自动更新锁定时间
    success = db.acquire_lock(filename, user_id)
    if success:
        return jsonify({'message': '心跳成功'})
    else:
        return jsonify({'error': '锁已被他人占用'}), 409


@app.route('/api/locks/status/<filename>', methods=['GET'])
def get_lock_status(filename: str):
    """获取图片锁状态"""
    lock_info = db.get_lock_info(filename)
    if lock_info:
        return jsonify({
            'locked': True,
            'user_id': lock_info['user_id'],
            'locked_at': lock_info['locked_at']
        })
    return jsonify({'locked': False})


if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
