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
import logging
import traceback
from io import StringIO, BytesIO
from flask import Flask, jsonify, request, send_file, Response, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from database import Database
from ai_service.ai_predictor import AIPredictor

load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    logger.warning(f"Failed to initialize AI predictor: {e}")
    logger.warning(traceback.format_exc())
    ai_predictor = None
    ai_enabled = False

# 初始化训练管理器（需要指定Aerovision-V1路径）
AERO_V1_PATH = os.getenv('AERO_V1_PATH', './AeroVision-V1')
TEMP_DIR = os.getenv('TEMP_DIR', './temp_training')
MODELS_DIR = os.getenv('MODELS_DIR', './models')

try:
    from training_manager import TrainingManager
    from scheduler import TrainingScheduler

    training_manager = TrainingManager(
        db=db,
        aero_v1_path=AERO_V1_PATH,
        labeled_dir=LABELED_DIR,
        temp_dir=TEMP_DIR,
        models_dir=MODELS_DIR
    )

    # 启动训练管理器
    training_manager.start()

    # 初始化并启动调度器
    scheduler = TrainingScheduler(
        training_manager=training_manager,
        db=db,
        schedule_hour=int(os.getenv('TRAINING_SCHEDULE_HOUR', '2'))
    )
    scheduler.start()

    training_enabled = True
    logger.info("Training manager and scheduler initialized")
except Exception as e:
    logger.warning(f"Failed to initialize training manager: {e}")
    logger.warning(traceback.format_exc())
    training_manager = None
    scheduler = None
    training_enabled = False

# 支持的图片格式
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}


def is_image_file(filename: str) -> bool:
    """检查是否是图片文件"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in IMAGE_EXTENSIONS


def run_startup_ai_prediction():
    """启动时对未标注图片进行 AI 预测"""
    logger.info("="*60)
    logger.info("run_startup_ai_prediction START")
    logger.info(f"ai_enabled={ai_enabled}, ai_predictor={ai_predictor}")
    logger.info(f"IMAGES_DIR={IMAGES_DIR}")
    logger.info(f"IMAGES_DIR exists: {os.path.exists(IMAGES_DIR)}")
    logger.info("="*60)
    
    if not ai_enabled or ai_predictor is None:
        logger.info("AI predictor not enabled, skipping startup prediction")
        return

    try:
        logger.info("Starting to collect images for prediction...")
        # 获取已标注和已跳过的文件
        labeled_files = db.get_labeled_original_filenames()
        logger.info(f"Labeled files: {len(labeled_files)}")
        
        skipped_files = db.get_skipped_filenames()
        logger.info(f"Skipped files: {len(skipped_files)}")

        # 获取已有 AI 预测的文件
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT filename FROM ai_predictions')
        predicted_files = {row[0] for row in cursor.fetchall()}
        conn.close()
        logger.info(f"Already predicted files: {len(predicted_files)}")

        # 找出需要预测的图片
        image_paths = []
        logger.info(f"IMAGES_DIR exists check: {os.path.exists(IMAGES_DIR)}")
        
        if os.path.exists(IMAGES_DIR):
            all_files = os.listdir(IMAGES_DIR)
            logger.info(f"Total files in IMAGES_DIR: {len(all_files)}")
            
            for filename in all_files:
                is_img = is_image_file(filename)
                not_labeled = filename not in labeled_files
                not_skipped = filename not in skipped_files
                not_predicted = filename not in predicted_files
                
                if is_img and not_labeled and not_skipped and not_predicted:
                    image_paths.append(os.path.join(IMAGES_DIR, filename))

        logger.info(f"Found {len(image_paths)} images to predict")

        if not image_paths:
            logger.info("No new images to predict at startup")
            return

        logger.info(f"Starting AI prediction for {len(image_paths)} images...")

        # 实时数据库写入回调
        success_count = 0
        error_count = 0
        
        def save_to_db(index, result):
            nonlocal success_count, error_count
            try:
                resp = db.add_ai_prediction(result)
                if isinstance(resp, dict) and resp.get('error'):
                    logger.warning(f"Prediction already exists, skip save: {result.get('filename')}")
                else:
                    success_count += 1
                    logger.info(f"Saved prediction {success_count} to DB: {result.get('filename')}")
            except Exception as e:
                error_count += 1
                logger.error(f"Failed to save prediction to DB: {result.get('filename')}: {e}")

        # 批量预测（使用流式回调）
        batch_result = ai_predictor.predict_batch(image_paths, detect_new_classes=True, on_prediction_callback=save_to_db)
        logger.info(f"predict_batch returned with {len(batch_result['predictions'])} results")

        # 处理新类别检测（需要在所有预测完成后执行）
        new_class_count = batch_result['statistics'].get('new_class_count', 0)
        if new_class_count > 0:
            logger.info(f"Detected {new_class_count} new classes, updating their is_new_class flag")
            for idx in batch_result['new_class_indices']:
                if idx < len(batch_result['predictions']):
                    pred = batch_result['predictions'][idx]
                    # 更新数据库中的is_new_class标记
                    try:
                        db.update_ai_prediction_new_class_flag(pred['filename'], 1, pred.get('outlier_score', 0.0))
                    except Exception as e:
                        logger.error(f"Failed to update new_class flag for {pred['filename']}: {e}")

        logger.info(f"Startup AI prediction: {success_count} succeeded, {error_count} failed")
        logger.info(f"Statistics: {batch_result['statistics']}")

    except Exception as e:
        logger.error(f"Startup AI prediction FAILED: {e}")
        logger.error(traceback.format_exc())


# ==================== 图片相关 API ====================

@app.route('/api/images', methods=['GET'])
def get_images():
    """获取待标注图片列表（包含 AI 预测结果）"""
    user_id = request.args.get('user_id', '')
    labeled_files = db.get_labeled_original_filenames()
    skipped_files = db.get_skipped_filenames()

    images = []
    if os.path.exists(IMAGES_DIR):
        for filename in os.listdir(IMAGES_DIR):
            if is_image_file(filename) and filename not in labeled_files and filename not in skipped_files:
                # 检查是否被锁定（排除自己锁定的）
                lock_info = db.get_lock_info(filename)
                is_locked_by_others = lock_info and lock_info['user_id'] != user_id

                # 获取 AI 预测结果
                ai_prediction = db.get_ai_prediction(filename)

                image_info = {
                    'filename': filename,
                    'path': f'/api/images/{filename}',
                    'locked': is_locked_by_others,
                    'locked_by': lock_info['user_id'] if is_locked_by_others else None,
                    'has_ai_prediction': ai_prediction is not None
                }

                # 如果有 AI 预测，添加预测信息
                if ai_prediction:
                    image_info['ai_prediction'] = {
                        'aircraft_class': ai_prediction['aircraft_class'],
                        'aircraft_confidence': ai_prediction['aircraft_confidence'],
                        'airline_class': ai_prediction['airline_class'],
                        'airline_confidence': ai_prediction['airline_confidence'],
                        'registration': ai_prediction['registration'],
                        'registration_area': ai_prediction['registration_area'],
                        'registration_confidence': ai_prediction['registration_confidence'],
                        'clarity': ai_prediction['clarity'],
                        'block': ai_prediction['block'],
                        'is_new_class': ai_prediction['is_new_class'],
                        'quality_pass': ai_prediction.get('quality_pass', True)
                    }

                images.append(image_info)

    # 按文件名排序
    images.sort(key=lambda x: x['filename'])

    return jsonify({
        'total': len(images),
        'items': images
    })


# # ==================== 模型推理相关 API ====================

# @app.route('/api/inference/predict', methods=['POST'])
# def predict_image():
#     """调用推理服务获取YOLOv8-cls预测结果"""
#     try:
#         data = request.get_json()
#         image_base64 = data.get('image_base64')
#         image_path = data.get('image_path')

#         if not image_base64 and not image_path:
#             return jsonify({'error': '请提供 image_base64 或 image_path'}), 400

#         # 如果提供了图片路径，读取并转换为base64
#         if image_path:
#             full_path = os.path.join(IMAGES_DIR, image_path)
#             if not os.path.exists(full_path):
#                 return jsonify({'error': '图片不存在'}), 404

#             with open(full_path, 'rb') as f:
#                 image_data = base64.b64encode(f.read()).decode('utf-8')
#         else:
#             image_data = image_base64

#         # 调用推理服务
#         try:
#             response = requests.post(
#                 f'{INFERENCE_SERVICE_URL}/api/v1/predict',
#                 json={'image_base64': image_data},
#                 timeout=30
#             )
#             response.raise_for_status()
#             return jsonify(response.json())
#         except requests.RequestException as e:
#             logger.error(f'推理服务调用失败: {str(e)}')
#             return jsonify({'error': f'推理服务调用失败: {str(e)}'}), 503

#     except Exception as e:
#         logger.error(f'预测错误: {str(e)}')
#         return jsonify({'error': f'预测错误: {str(e)}'}), 500


# @app.route('/api/inference/ocr', methods=['POST'])
# def ocr_image():
#     """调用推理服务获取PaddleOCR识别结果"""
#     try:
#         data = request.get_json()
#         image_base64 = data.get('image_base64')
#         image_path = data.get('image_path')
#         crop_area = data.get('crop_area')  # [x1, y1, x2, y2]

#         if not image_base64 and not image_path:
#             return jsonify({'error': '请提供 image_base64 或 image_path'}), 400

#         # 如果提供了图片路径，读取并转换为base64
#         if image_path:
#             full_path = os.path.join(IMAGES_DIR, image_path)
#             if not os.path.exists(full_path):
#                 return jsonify({'error': '图片不存在'}), 404

#             with open(full_path, 'rb') as f:
#                 image_data = base64.b64encode(f.read()).decode('utf-8')
#         else:
#             image_data = image_base64

#         # 调用推理服务
#         try:
#             response = requests.post(
#                 f'{INFERENCE_SERVICE_URL}/api/v1/ocr',
#                 json={'image_base64': image_data},
#                 timeout=30
#             )
#             response.raise_for_status()
#             return jsonify(response.json())
#         except requests.RequestException as e:
#             logger.error(f'OCR服务调用失败: {str(e)}')
#             return jsonify({'error': f'OCR服务调用失败: {str(e)}'}), 503

#     except Exception as e:
#         logger.error(f'OCR错误: {str(e)}')
#         return jsonify({'error': f'OCR错误: {str(e)}'}), 500


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
        logger.error(f"Skip image error: {str(e)}")
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
        logger.warning(f"以下文件未找到: {', '.join(missing_files)}")

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
        logger.error(f"AI prediction error: {str(e)}")
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

        # 实时保存回调
        saved = 0
        def save_to_db(index, result):
            nonlocal saved
            resp = db.add_ai_prediction(result)
            if not (isinstance(resp, dict) and resp.get('error')):
                saved += 1

        # 批量预测（使用流式回调）
        batch_result = ai_predictor.predict_batch(image_paths, detect_new_classes=True, on_prediction_callback=save_to_db)

        # 预测结束后，更新新类别标记
        if batch_result.get('new_class_indices'):
            for idx in batch_result['new_class_indices']:
                if idx < len(batch_result['predictions']):
                    pred = batch_result['predictions'][idx]
                    db.update_ai_prediction_new_class_flag(pred['filename'], 1, pred.get('outlier_score', 0.0))

        return jsonify({
            'message': f'AI prediction completed for {len(batch_result["predictions"])} images',
            'total': len(batch_result['predictions']),
            'saved': saved,
            'statistics': batch_result['statistics']
        })

    except Exception as e:
        logger.error(f"Batch AI prediction error: {str(e)}")
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
        logger.error(f"Approve prediction error: {str(e)}")
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
        logger.error(f"Reject prediction error: {str(e)}")
        return jsonify({'error': f'Failed to reject prediction: {str(e)}'}), 500


@app.route('/api/ai/stats', methods=['GET'])
def get_ai_stats():
    """获取AI复审统计信息"""
    stats = db.get_review_stats()
    return jsonify(stats)

# ==================== 训练相关 API ====================

@app.route('/api/training/status', methods=['GET'])
def get_training_status():
    """获取训练系统状态"""
    if not training_enabled:
        return jsonify({
            'enabled': False,
            'message': 'Training not enabled'
        })

    try:
        # 获取队列状态
        queue_status = training_manager.get_queue_status()

        # 获取当前运行的任务
        running_job = db.get_running_training_job()

        # 获取调度器状态
        scheduler_status = scheduler.get_status()

        # 获取资源状态
        resources_ok, resource_info = training_manager.check_resources()

        return jsonify({
            'enabled': True,
            'queue': queue_status,
            'running_job': running_job,
            'scheduler': scheduler_status,
            'resources': {
                'ok': resources_ok,
                'info': resource_info
            }
        })
    except Exception as e:
        logger.error(f"Failed to get training status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/training/jobs', methods=['GET'])
def get_training_jobs():
    """获取训练任务列表"""
    if not training_enabled:
        return jsonify({'error': 'Training not enabled'}), 503

    status = request.args.get('status')
    limit = request.args.get('limit', type=int)

    try:
        jobs = db.get_training_jobs(status=status, limit=limit)
        return jsonify({
            'total': len(jobs),
            'items': jobs
        })
    except Exception as e:
        logger.error(f"Failed to get training jobs: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/training/jobs/<int:job_id>', methods=['GET'])
def get_training_job(job_id: int):
    """获取单个训练任务详情"""
    if not training_enabled:
        return jsonify({'error': 'Training not enabled'}), 503

    try:
        job = db.get_training_job(job_id)
        if not job:
            return jsonify({'error': 'Training job not found'}), 404

        # 获取评估结果
        result = db.get_training_result(job_id)

        # 获取模型版本
        versions = db.get_model_versions(training_job_id=job_id)

        return jsonify({
            'job': job,
            'result': result,
            'model_versions': versions
        })
    except Exception as e:
        logger.error(f"Failed to get training job {job_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/training/trigger', methods=['POST'])
def trigger_training():
    """手动触发训练"""
    if not training_enabled:
        return jsonify({'error': 'Training not enabled'}), 503

    data = request.get_json()
    task_type = data.get('task_type', 'aircraft')

    if task_type not in ['aircraft', 'airline']:
        return jsonify({'error': 'Invalid task_type, must be aircraft or airline'}), 400

    try:
        result = training_manager.trigger_training(task_type=task_type, triggered_by='manual')
        return jsonify(result)
    except Exception as e:
        logger.error(f"Failed to trigger training: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/api/training/jobs/<int:job_id>/cancel', methods=['POST'])
def cancel_training_job(job_id: int):
    """取消训练任务"""
    if not training_enabled:
        return jsonify({'error': 'Training not enabled'}), 503

    try:
        job = db.get_training_job(job_id)
        if not job:
            return jsonify({'error': 'Training job not found'}), 404

        if job['status'] not in ['pending', 'queued']:
            return jsonify({'error': 'Cannot cancel job in current status'}), 400

        db.update_training_job_status(job_id, 'cancelled', error_message='Cancelled by user')

        return jsonify({'message': 'Training job cancelled'})
    except Exception as e:
        logger.error(f"Failed to cancel training job {job_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/training/models', methods=['GET'])
def get_model_versions():
    """获取模型版本列表"""
    if not training_enabled:
        return jsonify({'error': 'Training not enabled'}), 503

    model_type = request.args.get('type')
    active_only = request.args.get('active_only', 'false').lower() == 'true'

    try:
        versions = db.get_model_versions(model_type=model_type, active_only=active_only)
        return jsonify({
            'total': len(versions),
            'items': versions
        })
    except Exception as e:
        logger.error(f"Failed to get model versions: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/training/models/<int:version_id>/activate', methods=['POST'])
def activate_model_version(version_id: int):
    """激活指定模型版本"""
    if not training_enabled:
        return jsonify({'error': 'Training not enabled'}), 503

    try:
        success = db.set_active_model(version_id)
        if not success:
            return jsonify({'error': 'Model version not found'}), 404

        return jsonify({'message': 'Model version activated'})
    except Exception as e:
        logger.error(f"Failed to activate model version {version_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/training/results/<int:job_id>', methods=['GET'])
def get_training_result(job_id: int):
    """获取训练结果"""
    if not training_enabled:
        return jsonify({'error': 'Training not enabled'}), 503

    try:
        result = db.get_training_result(job_id)
        if not result:
            return jsonify({'error': 'Training result not found'}), 404

        return jsonify(result)
    except Exception as e:
        logger.error(f"Failed to get training result {job_id}: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== 前端静态资源服务 ====================

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    """提供前端静态资源和 SPA 路由支持"""
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')


# 在应用启动时运行 AI 预测（全局作用域，gunicorn 会执行）
logger.info("="*80)
logger.info("Flask app initialized, starting AI prediction...")
logger.info("="*80)
run_startup_ai_prediction()
logger.info("="*80)
logger.info("Flask app startup complete")
logger.info("="*80)


if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
