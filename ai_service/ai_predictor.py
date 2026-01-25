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
from .quality_service import QualityAssessor
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
        self.quality = QualityAssessor(self.config.get('quality_assessor', {}))
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

        # 1. 分类预测（机型和航司）
        classification_result = self.predictor.predict(image_path)

        aircraft_pred = classification_result['aircraft']
        airline_pred = classification_result['airline']

        # 2. OCR识别
        ocr_result = self.ocr.recognize(image_path)

        # 3. 质量评估
        quality_result = self.quality.assess(image_path)

        prediction_time = time.time() - start_time

        # 组合结果
        result = {
            'filename': Path(image_path).name,
            'aircraft_class': aircraft_pred['class_name'],
            'aircraft_confidence': aircraft_pred['confidence'],
            'airline_class': airline_pred['class_name'],
            'airline_confidence': airline_pred['confidence'],
            'registration': ocr_result['registration'],
            'registration_area': ocr_result.get('registration_area', ''),
            'registration_confidence': ocr_result['confidence'],
            'clarity': quality_result['clarity'],
            'block': quality_result['block'],
            'quality_confidence': quality_result['confidence'],
            'prediction_time': prediction_time,
            'classification_details': {
                'aircraft': aircraft_pred,
                'airline': airline_pred
            },
            'ocr_details': ocr_result,
            'quality_details': quality_result
        }

        return result

    def predict_batch(
        self,
        image_paths: List[str],
        detect_new_classes: bool = True
    ) -> Dict[str, Any]:
        """
        批量预测

        Args:
            image_paths: 图片路径列表
            detect_new_classes: 是否检测新类别

        Returns:
            包含所有预测结果和新类别检测结果的字典
        """
        if not self._models_loaded:
            self.load_models()

        logger.info(f"Predicting batch of {len(image_paths)} images...")

        predictions = []
        for i, image_path in enumerate(image_paths):
            try:
                result = self.predict_single(image_path)
                predictions.append(result)
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
            new_class_indices = self.hdbscan.detect_new_classes(predictions)

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
            service: 服务名称 ('ocr', 'quality', 'hdbscan')

        Returns:
            是否启用
        """
        service_map = {
            'ocr': self.ocr,
            'quality': self.quality,
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
