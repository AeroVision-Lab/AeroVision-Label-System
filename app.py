"""
Flask 后端 API
"""
import os
import csv
import json
import shutil
import zipfile
import requests
import base64
from io import StringIO, BytesIO
from flask import Flask, jsonify, request, send_file, Response, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from database import Database
from ai_service.ai_predictor import AIPredictor

load_dotenv()

app = Flask(
    __name__,
    static_folder='./frontend/dist',
    static_url_path='/'
    )

CORS(app)

# 配置
IMAGES_DIR = os.getenv('IMAGES_DIR', './images')
LABELED_DIR = os.getenv('LABELED_DIR', './labeled')
DATABASE_PATH = os.getenv('DATABASE_PATH', './labels.db')
EXPORT_IMAGES_THRESHOLD = int(os.getenv('EXPORT_IMAGES_THRESHOLD', '100'))
AI_CONFIG_PATH = os.getenv('AI_CONFIG_PATH', './config.yaml')

# 确保目录存在
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(LABELED_DIR, exist_ok=True)

# 初始化数据库
db = Database(DATABASE_PATH)

# 加载预置数据
data_dir = os.path.join(os.path.dirname(__file__), 'data')
db.load_preset_data(data_dir)

# 初始化AI预测服务
try:
    ai_predictor = AIPredictor(AI_CONFIG_PATH)
    ai_enabled = True
except Exception as e:
    print(f"[WARNING] Failed to initialize AI predictor: {e}")
    ai_predictor = None
    ai_enabled = False

# 支持的图片格式
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}


def is_image_file(filename: str) -> bool:
    """检查是否是图片文件"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in IMAGE_EXTENSIONS


# ==================== 图片相关 API ====================

@app.route('/api/images', methods=['GET'])
def get_images():
    """获取待标注图片列表（排除已标注的、被跳过的和被他人锁定的）"""
    user_id = request.args.get('user_id', '')
    labeled_files = db.get_labeled_original_filenames()
    skipped_files = db.get_skipped_filenames()
    locked_files = db.get_locked_filenames()

    images = []
    if os.path.exists(IMAGES_DIR):
        for filename in os.listdir(IMAGES_DIR):
            if is_image_file(filename) and filename not in labeled_files and filename not in skipped_files:
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


def send_from_directory(path):
    """获取图片文件"""
    pass


# ==================== 模型推理相关 API ====================

@app.route('/api/inference/predict', methods=['POST'])
def predict_image():
    """调用推理服务获取YOLOv8-cls预测结果"""
    try:
        data = request.get_json()
        image_base64 = data.get('image_base64')
        image_path = data.get('image_path')

        if not image_base64 and not image_path:
            return jsonify({'error': '请提供 image_base64 或 image_path'}), 400

        # 如果提供了图片路径，读取并转换为base64
        if image_path:
            full_path = os.path.join(IMAGES_DIR, image_path)
            if not os.path.exists(full_path):
                return jsonify({'error': '图片不存在'}), 404

            with open(full_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
        else:
            image_data = image_base64

        # 调用推理服务
        try:
            response = requests.post(
                f'{INFERENCE_SERVICE_URL}/api/v1/predict',
                json={'image_base64': image_data},
                timeout=30
            )
            response.raise_for_status()
            return jsonify(response.json())
        except requests.RequestException as e:
            print(f'[ERROR] 推理服务调用失败: {str(e)}')
            return jsonify({'error': f'推理服务调用失败: {str(e)}'}), 503

    except Exception as e:
        print(f'[ERROR] 预测错误: {str(e)}')
        return jsonify({'error': f'预测错误: {str(e)}'}), 500


@app.route('/api/inference/ocr', methods=['POST'])
def ocr_image():
    """调用推理服务获取PaddleOCR识别结果"""
    try:
        data = request.get_json()
        image_base64 = data.get('image_base64')
        image_path = data.get('image_path')
        crop_area = data.get('crop_area')  # [x1, y1, x2, y2]

        if not image_base64 and not image_path:
            return jsonify({'error': '请提供 image_base64 或 image_path'}), 400

        # 如果提供了图片路径，读取并转换为base64
        if image_path:
            full_path = os.path.join(IMAGES_DIR, image_path)
            if not os.path.exists(full_path):
                return jsonify({'error': '图片不存在'}), 404

            with open(full_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
        else:
            image_data = image_base64

        # 调用推理服务
        try:
            response = requests.post(
                f'{INFERENCE_SERVICE_URL}/api/v1/ocr',
                json={'image_base64': image_data},
                timeout=30
            )
            response.raise_for_status()
            return jsonify(response.json())
        except requests.RequestException as e:
            print(f'[ERROR] OCR服务调用失败: {str(e)}')
            return jsonify({'error': f'OCR服务调用失败: {str(e)}'}), 503

    except Exception as e:
        print(f'[ERROR] OCR错误: {str(e)}')
        return jsonify({'error': f'OCR错误: {str(e)}'}), 500


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


@app.route('/api/images/skip', methods=['POST'])
def skip_image_handler():
    """将图片标记为废图（跳过）"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': '请求数据为空'}), 400

        filename = data.get('filename')

        if not filename:
            return jsonify({'error': '缺少 filename 参数'}), 400

        # 检查图片是否存在
        file_path = os.path.join(IMAGES_DIR, filename)

        if not os.path.exists(file_path):
            return jsonify({'error': '图片不存在'}), 404

        success = db.skip_image(filename)

        # 无论是新标记还是已经标记过，都返回成功（幂等性）
        if success:
            return jsonify({'message': '已标记为废图', 'filename': filename})
        else:
            # 图片已经被标记过，这也是成功的操作
            return jsonify({'message': '图片已标记为废图', 'filename': filename, 'already_skipped': True})
    except Exception as e:
        print(f"[ERROR] Skip image error: {str(e)}")
        return jsonify({'error': f'服务器错误: {str(e)}'}), 500


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
    """创建标注记录（支持模型预测辅助）"""
    data = request.get_json()

    # 获取模型预测信息
    model_prediction_type = data.get('model_prediction_type')
    model_prediction_airline = data.get('model_prediction_airline')
    model_confidence = data.get('model_confidence')
    model_ocr_text = data.get('model_ocr_text')

    # 获取用户输入
    user_type_id = data.get('type_id')
    user_airline_id = data.get('airline_id')
    user_registration = data.get('registration')

    # 获取是否使用模型预测的标记
    use_model_type = data.get('use_model_type', False)
    use_model_airline = data.get('use_model_airline', False)
    use_model_ocr = data.get('use_model_ocr', False)

    # 数据验证逻辑：输入框 > 模型预测 > 不给通过
    if use_model_type and model_prediction_type:
        # 如果选择使用模型预测，且模型有预测结果，使用预测值
        final_type_id = model_prediction_type
        final_type_name = model_prediction_type  # 简化处理，实际应该查询名称
    elif user_type_id:
        # 如果用户输入了值，使用用户输入
        final_type_id = user_type_id
        final_type_name = data.get('type_name', user_type_id)
    else:
        # 都没有，返回错误
        return jsonify({'error': '必须输入机型或选择使用模型预测'}), 400

    if use_model_airline and model_prediction_airline:
        final_airline_id = model_prediction_airline
        final_airline_name = model_prediction_airline
    elif user_airline_id:
        final_airline_id = user_airline_id
        final_airline_name = data.get('airline_name', user_airline_id)
    else:
        return jsonify({'error': '必须输入航司或选择使用模型预测'}), 400

    if use_model_ocr and model_ocr_text:
        final_registration = model_ocr_text
    elif user_registration:
        final_registration = user_registration
    else:
        return jsonify({'error': '必须输入注册号或选择使用OCR识别'}), 400

    # 更新数据中的值
    data['type_id'] = final_type_id
    data['type_name'] = final_type_name
    data['airline_id'] = final_airline_id
    data['airline_name'] = final_airline_name
    data['registration'] = final_registration

    # 验证必填字段
    required_fields = ['original_file_name', 'type_id', 'type_name',
                       'airline_id', 'airline_name', 'clarity', 'block',
                       'registration', 'registration_area']

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
                       'registration_area']

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
    """导出标注数据为 CSV，支持ID范围筛选"""
    start_id = request.args.get('start_id', type=int)
    end_id = request.args.get('end_id', type=int)

    labels = db.get_all_labels_for_export(start_id, end_id)

    # 获取所有机型和航司的映射（code -> id）
    aircraft_types = {t['code']: t['id'] for t in db.get_aircraft_types()}
    airlines = {a['code']: a['id'] for a in db.get_airlines()}

    # 创建 CSV（使用 UTF-8 BOM 以支持 Excel 中文显示）
    output = StringIO()
    # 写入 UTF-8 BOM
    output.write('\ufeff')
    writer = csv.writer(output)

    # 写入表头
    writer.writerow(['filename', 'typeid', 'typename', 'airlineid',
                     'airlinename', 'clarity', 'block', 'registration'])

    # 写入数据
    # typeid/airlineid 使用数据库数字id，typename/airlinename 使用 code
    for label in labels:
        type_code = label['type_id']  # 当前存储的是code
        airline_code = label['airline_id']  # 当前存储的是code
        writer.writerow([
            label['file_name'],
            aircraft_types.get(type_code, type_code),  # 数字id
            type_code,  # code 作为 typename
            airlines.get(airline_code, airline_code),  # 数字id
            airline_code,  # code 作为 airlinename
            label['clarity'],
            label['block'],
            label['registration']
        ])

    output.seek(0)

    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv; charset=utf-8-sig',
        headers={'Content-Disposition': 'attachment; filename=labels.csv'}
    )


@app.route('/api/labels/export-yolo', methods=['GET'])
def export_yolo_labels():
    """导出 YOLO 格式标注文件（zip 包含所有 txt 文件），支持ID范围筛选"""
    start_id = request.args.get('start_id', type=int)
    end_id = request.args.get('end_id', type=int)

    labels = db.get_all_labels_with_area(start_id, end_id)

    # 创建内存中的 zip 文件
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for label in labels:
            # 生成 txt 文件名（与图片同名）
            img_name = os.path.splitext(label['file_name'])[0]
            txt_filename = f"{img_name}.txt"

            # YOLO 格式: class_id x_center y_center width height
            # registration_area 已经是 "x_center y_center width height" 格式
            if label['registration_area']:
                content = f"0 {label['registration_area']}"
            else:
                content = ""

            zip_file.writestr(txt_filename, content)

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='yolo_labels.zip'
    )


@app.route('/api/labels/export-images', methods=['GET'])
def export_images():
    """导出已标注的照片（zip 包含所有图片），支持ID范围筛选

    如果照片数量超过阈值，返回错误提示
    """
    start_id = request.args.get('start_id', type=int)
    end_id = request.args.get('end_id', type=int)

    labels = db.get_all_labels_for_export(start_id, end_id)

    # 检查照片数量
    if len(labels) > EXPORT_IMAGES_THRESHOLD:
        return jsonify({
            'error': f'照片数量({len(labels)})超过限制({EXPORT_IMAGES_THRESHOLD})，无法打包下载',
            'count': len(labels),
            'threshold': EXPORT_IMAGES_THRESHOLD
        }), 400

    # 创建内存中的 zip 文件
    zip_buffer = BytesIO()
    missing_files = []

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for label in labels:
            # 查找图片文件
            img_path = os.path.join(LABELED_DIR, label['file_name'])

            if os.path.exists(img_path):
                # 读取图片文件并添加到ZIP
                zip_file.write(img_path, arcname=label['file_name'])
            else:
                missing_files.append(label['file_name'])

    # 如果有缺失的文件，记录警告
    if missing_files:
        print(f"警告: 以下文件未找到: {', '.join(missing_files)}")

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='labeled_images.zip'
    )


# ==================== 航司相关 API ====================

@app.route('/api/airlines', methods=['GET'])
def get_airlines():
    """获取航司列表"""
    airlines = db.get_airlines()
    return jsonify(airlines)


@app.route('/api/airlines/export', methods=['GET'])
def export_airlines():
    """导出航司数据为 JSON（id + code）"""
    airlines = db.get_airlines()
    # 只保留 id 和 code
    export_data = [{'id': a['id'], 'code': a['code']} for a in airlines]
    return Response(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=airlines.json'}
    )


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


@app.route('/api/aircraft-types/export', methods=['GET'])
def export_aircraft_types():
    """导出机型数据为 JSON（id + code）"""
    types = db.get_aircraft_types()
    # 只保留 id 和 code
    export_data = [{'id': t['id'], 'code': t['code']} for t in types]
    return Response(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=aircraft_types.json'}
    )


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

    # 添加未标注数量（排除废图）
    labeled_files = db.get_labeled_original_filenames()
    skipped_files = db.get_skipped_filenames()
    unlabeled_count = 0
    if os.path.exists(IMAGES_DIR):
        for filename in os.listdir(IMAGES_DIR):
            if is_image_file(filename) and filename not in labeled_files and filename not in skipped_files:
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


# ==================== AI预测相关 API ====================

@app.route('/api/ai/status', methods=['GET'])
def get_ai_status():
    """获取AI服务状态"""
    if not ai_enabled:
        return jsonify({
            'enabled': False,
            'message': 'AI predictor not initialized'
        })

    try:
        config = ai_predictor.get_config()
        services = {
            'ocr': ai_predictor.is_enabled('ocr'),
            'quality': ai_predictor.is_enabled('quality'),
            'hdbscan': ai_predictor.is_enabled('hdbscan')
        }

        return jsonify({
            'enabled': True,
            'config': config,
            'services': services
        })
    except Exception as e:
        return jsonify({
            'enabled': False,
            'message': str(e)
        }), 500


@app.route('/api/ai/predict', methods=['POST'])
def run_ai_predict():
    """对指定图片运行AI预测"""
    if not ai_enabled:
        return jsonify({'error': 'AI service not enabled'}), 503

    data = request.get_json()
    filename = data.get('filename')

    if not filename:
        return jsonify({'error': 'Missing filename parameter'}), 400

    # 检查图片是否存在
    file_path = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'Image not found'}), 404

    try:
        # 运行预测
        result = ai_predictor.predict_single(file_path)

        # 保存到数据库
        db.add_ai_prediction(result)

        return jsonify(result)

    except Exception as e:
        print(f"[ERROR] AI prediction error: {str(e)}")
        return jsonify({'error': f'AI prediction failed: {str(e)}'}), 500


@app.route('/api/ai/predict-batch', methods=['POST'])
def run_ai_predict_batch():
    """批量运行AI预测（用于新图片自动触发）"""
    if not ai_enabled:
        return jsonify({'error': 'AI service not enabled'}), 503

    try:
        # 获取images/文件夹下所有未标注的图片
        labeled_files = db.get_labeled_original_filenames()
        skipped_files = db.get_skipped_filenames()

        # 检查哪些图片已有AI预测
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT filename FROM ai_predictions')
        predicted_files = {row[0] for row in cursor.fetchall()}
        conn.close()

        # 获取需要预测的图片
        image_paths = []
        for filename in os.listdir(IMAGES_DIR):
            if (is_image_file(filename) and
                filename not in labeled_files and
                filename not in skipped_files and
                filename not in predicted_files):
                image_paths.append(os.path.join(IMAGES_DIR, filename))

        if not image_paths:
            return jsonify({
                'message': 'No new images to predict',
                'count': 0
            })

        # 批量预测
        batch_result = ai_predictor.predict_batch(image_paths, detect_new_classes=True)

        # 保存所有预测结果到数据库
        for pred in batch_result['predictions']:
            if 'error' not in pred:
                db.add_ai_prediction(pred)

        return jsonify({
            'message': f'AI prediction completed for {len(batch_result["predictions"])} images',
            'total': len(batch_result['predictions']),
            'statistics': batch_result['statistics']
        })

    except Exception as e:
        print(f"[ERROR] Batch AI prediction error: {str(e)}")
        return jsonify({'error': f'Batch AI prediction failed: {str(e)}'}), 500


@app.route('/api/ai/review/pending', methods=['GET'])
def get_pending_reviews():
    """获取待复审的AI预测（按优先级排序）"""
    if not ai_enabled:
        return jsonify({'error': 'AI service not enabled'}), 503

    limit = request.args.get('limit', type=int)
    predictions = db.get_unprocessed_predictions(limit)

    return jsonify({
        'total': len(predictions),
        'items': predictions
    })


@app.route('/api/ai/review/auto-approvable', methods=['GET'])
def get_auto_approvable():
    """获取可一键通过的AI预测"""
    if not ai_enabled:
        return jsonify({'error': 'AI service not enabled'}), 503

    predictions = db.get_auto_approvable_predictions()

    return jsonify({
        'total': len(predictions),
        'items': predictions
    })


@app.route('/api/ai/review/approve', methods=['POST'])
def approve_prediction():
    """批准AI预测（创建标注）"""
    if not ai_enabled:
        return jsonify({'error': 'AI service not enabled'}), 503

    data = request.get_json()
    filename = data.get('filename')
    auto_approve = data.get('auto_approve', False)

    if not filename:
        return jsonify({'error': 'Missing filename parameter'}), 400

    # 获取AI预测结果
    ai_pred = db.get_ai_prediction(filename)
    if not ai_pred:
        return jsonify({'error': 'AI prediction not found'}), 404

    # 检查图片是否存在
    file_path = os.path.join(IMAGES_DIR, filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'Image not found'}), 404

    try:
        # 生成新文件名
        type_id = ai_pred['aircraft_class']
        seq = db.get_next_sequence(type_id)
        original_ext = os.path.splitext(filename)[1]
        new_filename = f"{type_id}-{seq:04d}{original_ext}"

        # 移动并重命名图片
        dst_path = os.path.join(LABELED_DIR, new_filename)
        shutil.move(file_path, dst_path)

        # 保存标注
        label_data = {
            'file_name': new_filename,
            'original_file_name': filename,
            'type_id': ai_pred['aircraft_class'],
            'type_name': ai_pred['aircraft_class'],  # 暂时用class_name
            'airline_id': ai_pred['airline_class'],
            'airline_name': ai_pred['airline_class'],
            'clarity': ai_pred['clarity'],
            'block': ai_pred['block'],
            'registration': ai_pred['registration'] or '',
            'registration_area': ai_pred['registration_area'] or ''
        }

        result = db.add_label(label_data)

        # 更新AI预测状态
        db.mark_prediction_processed(filename)

        # 更新标注的AI相关字段
        ai_data = {
            'review_status': 'approved' if auto_approve else 'reviewed',
            'ai_approved': 1 if auto_approve else 0
        }
        db.update_label_with_ai_data(result['id'], ai_data)

        return jsonify({
            'message': 'Label created successfully',
            'id': result['id'],
            'file_name': new_filename
        })

    except Exception as e:
        print(f"[ERROR] Approve prediction error: {str(e)}")
        return jsonify({'error': f'Failed to approve prediction: {str(e)}'}), 500


@app.route('/api/ai/review/bulk-approve', methods=['POST'])
def bulk_approve_predictions():
    """批量批准AI预测"""
    if not ai_enabled:
        return jsonify({'error': 'AI service not enabled'}), 503

    data = request.get_json()
    filenames = data.get('filenames', [])

    if not filenames:
        return jsonify({'error': 'No filenames provided'}), 400

    results = []
    errors = []

    for filename in filenames:
        try:
            # 获取AI预测结果
            ai_pred = db.get_ai_prediction(filename)
            if not ai_pred:
                errors.append({'filename': filename, 'error': 'AI prediction not found'})
                continue

            # 检查图片是否存在
            file_path = os.path.join(IMAGES_DIR, filename)
            if not os.path.exists(file_path):
                errors.append({'filename': filename, 'error': 'Image not found'})
                continue

            # 生成新文件名
            type_id = ai_pred['aircraft_class']
            seq = db.get_next_sequence(type_id)
            original_ext = os.path.splitext(filename)[1]
            new_filename = f"{type_id}-{seq:04d}{original_ext}"

            # 移动并重命名图片
            dst_path = os.path.join(LABELED_DIR, new_filename)
            shutil.move(file_path, dst_path)

            # 保存标注
            label_data = {
                'file_name': new_filename,
                'original_file_name': filename,
                'type_id': ai_pred['aircraft_class'],
                'type_name': ai_pred['aircraft_class'],
                'airline_id': ai_pred['airline_class'],
                'airline_name': ai_pred['airline_class'],
                'clarity': ai_pred['clarity'],
                'block': ai_pred['block'],
                'registration': ai_pred['registration'] or '',
                'registration_area': ai_pred['registration_area'] or ''
            }

            result = db.add_label(label_data)
            db.mark_prediction_processed(filename)

            # 更新标注的AI相关字段
            db.update_label_with_ai_data(result['id'], {
                'review_status': 'auto_approved',
                'ai_approved': 1
            })

            results.append({
                'filename': filename,
                'id': result['id'],
                'file_name': new_filename
            })

        except Exception as e:
            errors.append({'filename': filename, 'error': str(e)})

    return jsonify({
        'message': f'Bulk approve completed: {len(results)} succeeded, {len(errors)} failed',
        'success_count': len(results),
        'failed_count': len(errors),
        'results': results,
        'errors': errors
    })


@app.route('/api/ai/review/reject', methods=['POST'])
def reject_prediction():
    """拒绝AI预测"""
    if not ai_enabled:
        return jsonify({'error': 'AI service not enabled'}), 503

    data = request.get_json()
    filename = data.get('filename')
    skip_as_invalid = data.get('skip_as_invalid', False)

    if not filename:
        return jsonify({'error': 'Missing filename parameter'}), 400

    try:
        # 标记预测为已处理
        db.mark_prediction_processed(filename)

        # 如果选择跳过为废图，也跳过该图片
        if skip_as_invalid:
            db.skip_image(filename)

        return jsonify({
            'message': 'Prediction rejected'
        })

    except Exception as e:
        print(f"[ERROR] Reject prediction error: {str(e)}")
        return jsonify({'error': f'Failed to reject prediction: {str(e)}'}), 500


@app.route('/api/ai/stats', methods=['GET'])
def get_ai_stats():
    """获取AI复审统计信息"""
    stats = db.get_review_stats()
    return jsonify(stats)

# ==================== 前端静态资源服务 ====================

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    """提供前端静态资源和 SPA 路由支持"""
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
