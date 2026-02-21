"""
AI预测服务
统一的AI预测接口，整合分类器、OCR和质量评估
"""

import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml

from .predictor import ModelPredictor
from .ocr_service import RegistrationOCR
from .quality import ImageQualityAssessor
from .hdbscan_service import HDBSCANNewClassDetector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIPredictor:
    """统一的AI预测服务"""

    def __init__(self, config_path: str = './config.yaml'):
        """
        初始化AI预测服务

        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        self.config = self._load_config(config_path)

        # 初始化子模块
        self.predictor = ModelPredictor(self.config['models'])
        self.ocr = RegistrationOCR(self.config.get('ocr', {}))
        self.quality = ImageQualityAssessor(self.config.get('quality', {}))
        self.hdbscan = HDBSCANNewClassDetector(self.config.get('hdbscan', {}))

        # 模型已加载标志
        self._models_loaded = False

        logger.info("AIPredictor initialized")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载YAML配置文件"""
        config_file = Path(config_path)
        if not config_file.exists():
            logger.warning(f"Config file not found: {config_path}, using default config")
            return self._get_default_config()

        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        logger.info(f"Config loaded from: {config_path}")
        return config

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'models': {
                'aircraft': {'path': '/home/wlx/yolo26x-cls-aircraft.pt', 'device': 'cuda', 'image_size': 640},
                'airline': {'path': '/home/wlx/yolo26x-cls-airline.pt', 'device': 'cuda', 'image_size': 640}
            },
            'ocr': {'enabled': True, 'lang': 'ch', 'use_angle_cls': True},
            'quality_assessor': {'enabled': True},
            'hdbscan': {'enabled': True, 'min_cluster_size': 5, 'min_samples': 3},
            'thresholds': {'high_confidence': 0.95, 'low_confidence': 0.80}
        }

    def load_models(self):
        """加载所有模型"""
        if self._models_loaded:
            return

        logger.info("Loading models...")
        self.predictor.load_models()
        self._models_loaded = True
        logger.info("All models loaded")

    def predict_single(self, image_path: str) -> Dict[str, Any]:
        """
        预测单个图片

        Args:
            image_path: 图片文件路径

        Returns:
            包含所有预测结果的字典
        """
        start_time = time.time()
        filename = Path(image_path).name
        logger.info(f"Predicting image: {filename}")

        try:
            # 1. 分类预测（机型和航司）
            logger.debug(f"Starting classification for {filename}")
            classification_result = self.predictor.predict(image_path)
            logger.debug(f"Classification result: {classification_result}")

            aircraft_pred = classification_result['aircraft']
            airline_pred = classification_result['airline']

            # 2. OCR识别
            logger.debug(f"Starting OCR recognition for {filename}")
            ocr_result = self.ocr.recognize(image_path)
            logger.debug(f"OCR result: {ocr_result}")

            # 3. 质量评估（使用 CV 算法）
            logger.debug(f"Starting quality assessment for {filename}")
            quality_result = self.quality.assess(image_path)
            logger.debug(f"Quality result: {quality_result}")

            # 4. 从 detection 模型获取 registration_area（检测到的文本区域）
            registration_area = ''
            detection_result = classification_result.get('detection')
            if detection_result and detection_result.get('enabled') and detection_result.get('boxes'):
                logger.debug(f"Processing detection boxes for {filename}")
                # 假设第一个检测框是注册号区域，或选择置信度最高的框
                boxes = detection_result['boxes']
                if boxes:
                    best_box = max(boxes, key=lambda x: x['confidence'])
                    # 使用归一化坐标 xywhn: [x_center, y_center, width, height]
                    if best_box.get('xywhn'):
                        xywhn = best_box['xywhn']
                        registration_area = f"{xywhn[0]:.6f} {xywhn[1]:.6f} {xywhn[2]:.6f} {xywhn[3]:.6f}"
                        logger.debug(f"Registration area extracted: {registration_area}")

            prediction_time = time.time() - start_time

            # 简化返回结果
            result = {
                'filename': Path(image_path).name,
                'aircraft_class': aircraft_pred['class_name'],
                'aircraft_confidence': aircraft_pred['confidence'],
                'airline_class': airline_pred['class_name'],
                'airline_confidence': airline_pred['confidence'],
                'registration': ocr_result['registration'],
                'registration_confidence': ocr_result.get('confidence', 0.0),
                'registration_area': registration_area,
                'quality_score': quality_result.get('score', 0.0),
                'quality_confidence': quality_result.get('score', 0.0),
                'prediction_time': prediction_time
            }

            logger.info(f"Prediction completed: {filename} | Aircraft: {aircraft_pred['class_name']}({aircraft_pred['confidence']:.3f}) | "
                        f"Airline: {airline_pred['class_name']}({airline_pred['confidence']:.3f}) | "
                        f"Registration: {ocr_result['registration']} | Quality: {quality_result.get('score', 0.0):.3f} | "
                        f"Time: {prediction_time:.2f}s")

            return result
        
        except Exception as e:
            import traceback
            logger.error(f"Error predicting {filename}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # 返回错误标记，这样 predict_batch 会捕获
            return {
                'filename': filename,
                'error': str(e)
            }

    def predict_batch(
        self,
        image_paths: List[str],
        detect_new_classes: bool = True,
        on_prediction_callback = None
    ) -> Dict[str, Any]:
        """
        批量预测（懒加载模型）

        Args:
            image_paths: 图片路径列表
            detect_new_classes: 是否检测新类别
            on_prediction_callback: 预测完成回调，接收(index, result)参数，可用于实时保存到数据库

        Returns:
            包含所有预测结果和新类别检测结果的字典
        """
        logger.info(f"predict_batch called with {len(image_paths)} images")

        # 移除提前加载模型的逻辑，让模型在 predict_single 中懒加载
        # if not self._models_loaded:
        #     logger.info("Models not loaded, loading now...")
        #     try:
        #         self.load_models()
        #     except Exception as e:
        #         logger.error(f"Failed to load models: {e}")
        #         raise

        logger.info(f"Predicting batch of {len(image_paths)} images...")

        predictions = []
        for i, image_path in enumerate(image_paths):
            try:
                logger.info(f"Processing image {i+1}/{len(image_paths)}: {image_path}")
                result = self.predict_single(image_path)
                predictions.append(result)

                # 实时回调（用于流式保存到数据库）
                if on_prediction_callback and 'error' not in result:
                    try:
                        on_prediction_callback(i, result)
                    except Exception as e:
                        logger.error(f"Error in prediction callback for {result.get('filename')}: {e}")

                if (i + 1) % 10 == 0:
                    logger.info(f"Processed {i + 1}/{len(image_paths)} images")
            except Exception as e:
                logger.error(f"Error processing {image_path}: {e}")
                # 添加错误记录
                predictions.append({
                    'filename': Path(image_path).name,
                    'error': str(e),
                    'aircraft_class': '',
                    'aircraft_confidence': 0.0,
                    'airline_class': '',
                    'airline_confidence': 0.0
                })

        # 新类别检测
        new_class_indices = []
        if detect_new_classes:
            # 获取embeddings用于HDBSCAN聚类
            embeddings = self.predictor.get_embeddings(image_paths)
            new_class_indices = self.hdbscan.detect_new_classes(predictions, embeddings=embeddings)

        # 标记新类别
        for i, idx in enumerate(new_class_indices):
            if idx < len(predictions):
                predictions[idx]['is_new_class'] = 1
                # 获取异常分数
                outlier_scores = self.hdbscan.get_outlier_scores()
                if idx < len(outlier_scores):
                    predictions[idx]['outlier_score'] = float(outlier_scores[idx])

        # 默认值
        for pred in predictions:
            pred.setdefault('is_new_class', 0)
            pred.setdefault('outlier_score', 0.0)

        # 统计信息
        high_conf_count = sum(
            1 for p in predictions
            if p.get('aircraft_confidence', 0) >= 0.95
            and p.get('airline_confidence', 0) >= 0.95
            and p.get('is_new_class', 0) == 0
        )

        stats = {
            'total': len(predictions),
            'high_confidence_count': high_conf_count,
            'new_class_count': len(new_class_indices),
            'review_required_count': len(predictions) - high_conf_count
        }

        logger.info(f"Batch prediction complete: {stats}")

        return {
            'predictions': predictions,
            'new_class_indices': new_class_indices,
            'statistics': stats
        }

    def get_config(self) -> Dict[str, Any]:
        """获取当前配置"""
        return self.config

    def is_enabled(self, service: str) -> bool:
        """
        检查特定服务是否启用

        Args:
            service: 服务名称 ('ocr', 'hdbscan')

        Returns:
            是否启用
        """
        if service == 'quality':
            # ImageQualityAssessor 总是启用的
            return True

        service_map = {
            'ocr': self.ocr,
            'hdbscan': self.hdbscan
        }

        service_obj = service_map.get(service)
        if service_obj is None:
            return False

        return getattr(service_obj, 'enabled', False)

    def unload_models(self):
        """卸载所有模型并释放内存"""
        logger.info("Unloading all AI models...")

        # 卸载分类模型
        if hasattr(self.predictor, 'unload_models'):
            self.predictor.unload_models()

        # 卸载 OCR 相关资源
        if hasattr(self.ocr, 'cleanup'):
            self.ocr.cleanup()

        # 卸载质量评估器
        if hasattr(self.quality, 'cleanup'):
            self.quality.cleanup()

        # 卸载 HDBSCAN
        if hasattr(self.hdbscan, 'cleanup'):
            self.hdbscan.cleanup()

        self._models_loaded = False
        logger.info("All AI models unloaded")

    def __del__(self):
        """析构时自动清理模型"""
        self.unload_models()
