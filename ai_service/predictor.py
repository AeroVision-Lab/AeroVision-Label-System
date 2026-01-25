"""
AI分类器预测服务
集成机型和航司分类器
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional
from ultralytics import YOLO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ModelPredictor:
    """YOLOv8分类器预测器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化分类器

        Args:
            config: 配置字典，包含模型路径和参数
        """
        self.aircraft_model_path = config['aircraft']['path']
        self.airline_model_path = config['airline']['path']
        self.device = config['aircraft'].get('device', 'cuda')
        self.image_size = config['aircraft'].get('image_size', 640)

        self._aircraft_model: Optional[YOLO] = None
        self._airline_model: Optional[YOLO] = None

        logger.info(f"ModelPredictor initialized with device={self.device}, imgsz={self.image_size}")

    @property
    def aircraft_model(self) -> YOLO:
        """获取或加载机型模型"""
        if self._aircraft_model is None:
            self._load_aircraft_model()
        return self._aircraft_model

    @property
    def airline_model(self) -> YOLO:
        """获取或加载航司模型"""
        if self._airline_model is None:
            self._load_airline_model()
        return self._airline_model

    def _load_aircraft_model(self):
        """加载机型分类模型"""
        model_path = Path(self.aircraft_model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Aircraft model not found: {model_path}")

        logger.info(f"Loading aircraft model from: {model_path}")
        self._aircraft_model = YOLO(str(model_path))
        logger.info("Aircraft model loaded successfully")

    def _load_airline_model(self):
        """加载航司分类模型"""
        model_path = Path(self.airline_model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Airline model not found: {model_path}")

        logger.info(f"Loading airline model from: {model_path}")
        self._airline_model = YOLO(str(model_path))
        logger.info("Airline model loaded successfully")

    def load_models(self):
        """显式加载所有模型"""
        self._load_aircraft_model()
        self._load_airline_model()

    def predict(self, image_path: str) -> Dict[str, Any]:
        """
        预测单个图片的机型和航司

        Args:
            image_path: 图片文件路径

        Returns:
            包含预测结果的字典
        """
        # 预测机型
        aircraft_result = self._predict_single(self.aircraft_model, image_path, "aircraft")

        # 预测航司
        airline_result = self._predict_single(self.airline_model, image_path, "airline")

        return {
            'aircraft': aircraft_result,
            'airline': airline_result
        }

    def _predict_single(self, model: YOLO, image_path: str, model_name: str) -> Dict[str, Any]:
        """使用单个模型进行预测"""
        results = model.predict(
            image_path,
            imgsz=self.image_size,
            device=self.device,
            verbose=False
        )

        result = results[0]
        probs = result.probs

        class_id = int(probs.top1)
        confidence = float(probs.data[class_id])

        class_names = model.model.names
        class_name = class_names.get(class_id, "Unknown")

        # Top-5
        top5_indices = probs.top5
        top5_probs = probs.data[top5_indices].tolist()
        top5 = [
            {
                "id": int(idx),
                "name": class_names.get(int(idx), "Unknown"),
                "prob": float(prob)
            }
            for idx, prob in zip(top5_indices, top5_probs)
        ]

        return {
            "class_id": class_id,
            "class_name": class_name,
            "confidence": confidence,
            "top5": top5
        }

    def get_aircraft_class_names(self):
        """获取机型类别名称"""
        if self._aircraft_model is None:
            self._load_aircraft_model()
        class_names = self.aircraft_model.model.names
        return [class_names.get(i, f"class_{i}") for i in range(len(class_names))]

    def get_airline_class_names(self):
        """获取航司类别名称"""
        if self._airline_model is None:
            self._load_airline_model()
        class_names = self.airline_model.model.names
        return [class_names.get(i, f"class_{i}") for i in range(len(class_names))]

    def unload_models(self):
        """卸载模型并释放内存"""
        if self._aircraft_model is not None:
            del self._aircraft_model
            self._aircraft_model = None
            logger.info("Aircraft model unloaded")

        if self._airline_model is not None:
            del self._airline_model
            self._airline_model = None
            logger.info("Airline model unloaded")

        # 清理 PyTorch 缓存
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("CUDA cache cleared")
        except ImportError:
            pass

    def __del__(self):
        """析构时自动清理模型"""
        self.unload_models()
