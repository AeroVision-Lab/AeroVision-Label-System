"""
AI分类器预测服务
集成机型和航司分类器
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union
from ultralytics import YOLO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ModelPredictor:
    """YOLOv8分类器和检测器预测器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化分类器和检测器

        Args:
            config: 配置字典，包含模型路径和参数
        """
        self.aircraft_model_path = config['aircraft']['path']
        self.airline_model_path = config['airline']['path']
        self.device = config['aircraft'].get('device', 'cuda')
        self.image_size = config['aircraft'].get('image_size', 640)

        # Detection 配置
        detection_config = config.get('detection', {})
        self.detection_model_path = detection_config.get('path', '')
        self.detection_conf = detection_config.get('conf_threshold', 0.25)
        self.detection_iou = detection_config.get('iou_threshold', 0.45)
        self.detection_enabled = bool(self.detection_model_path)

        self._aircraft_model: Optional[YOLO] = None
        self._airline_model: Optional[YOLO] = None
        self._detection_model: Optional[YOLO] = None

        logger.info(f"ModelPredictor initialized with device={self.device}, imgsz={self.image_size}, detection_enabled={self.detection_enabled}")

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

    @property
    def detection_model(self) -> Optional[YOLO]:
        """获取或加载检测模型"""
        if not self.detection_enabled:
            return None
        if self._detection_model is None:
            self._load_detection_model()
        return self._detection_model

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

    def _load_detection_model(self):
        """加载目标检测模型"""
        if not self.detection_enabled:
            return

        model_path = Path(self.detection_model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Detection model not found: {model_path}")

        logger.info(f"Loading detection model from: {model_path}")
        self._detection_model = YOLO(str(model_path))
        logger.info("Detection model loaded successfully")

    def load_models(self):
        """显式加载所有模型"""
        self._load_aircraft_model()
        self._load_airline_model()
        if self.detection_enabled:
            self._load_detection_model()

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

        result = {
            'aircraft': aircraft_result,
            'airline': airline_result
        }

        # 目标检测
        if self.detection_enabled:
            detection_result = self.detect(image_path)
            result['detection'] = detection_result

        return result

    def detect(self, image_path: str) -> Dict[str, Any]:
        """
        目标检测

        Args:
            image_path: 图片文件路径

        Returns:
            包含检测结果的字典
        """
        if not self.detection_enabled or self.detection_model is None:
            return {'enabled': False, 'boxes': []}

        results = self.detection_model.predict(
            image_path,
            imgsz=self.image_size,
            device=self.device,
            conf=self.detection_conf,
            iou=self.detection_iou,
            verbose=False
        )

        result = results[0]
        boxes = result.boxes
        class_names = self.detection_model.model.names

        detections = []
        for i in range(len(boxes)):
            box = boxes[i]
            # xyxy 格式的边界框
            xyxy = box.xyxy[0].tolist()
            # xywhn 格式（归一化的中心点+宽高）
            xywhn = box.xywhn[0].tolist() if box.xywhn is not None else None
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            class_name = class_names.get(class_id, f"class_{class_id}")

            detections.append({
                'class_id': class_id,
                'class_name': class_name,
                'confidence': confidence,
                'xyxy': xyxy,  # [x1, y1, x2, y2] 像素坐标
                'xywhn': xywhn,  # [x_center, y_center, width, height] 归一化坐标
            })

        return {
            'enabled': True,
            'count': len(detections),
            'boxes': detections
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

    def get_detection_class_names(self):
        """获取检测类别名称"""
        if not self.detection_enabled:
            return []
        if self._detection_model is None:
            self._load_detection_model()
        class_names = self.detection_model.model.names
        return [class_names.get(i, f"class_{i}") for i in range(len(class_names))]

    def get_embeddings(self, image_paths: list) -> "np.ndarray":
        """
        获取图像的嵌入向量（使用YOLO的embed方法）

        Args:
            image_paths: 图像文件路径列表

        Returns:
            numpy数组，shape为(n_samples, embedding_dim)
        """
        import numpy as np

        if len(image_paths) == 0:
            logger.debug("Empty image paths list, returning empty array")
            return np.array([])

        logger.debug(f"Getting embeddings for {len(image_paths)} images")

        # 使用机型模型获取embeddings
        # YOLO的embed()返回一个list，每个元素是一个embedding向量
        embed_results = self.aircraft_model.embed(
            image_paths,
            imgsz=self.image_size,
            device=self.device,
            verbose=False
        )

        # embed_results是一个list，每个元素是一个tensor
        # 需要转换为numpy数组并堆叠
        embedding_list = []
        for i, embed_tensor in enumerate(embed_results):
            try:
                # 将tensor转换为numpy数组
                # embed_tensor可能需要先移到CPU
                if hasattr(embed_tensor, 'cpu'):
                    embed_array = embed_tensor.cpu().numpy()
                else:
                    embed_array = np.array(embed_tensor)

                # 确保是二维的（如果是1维的，需要reshape）
                if embed_array.ndim == 1:
                    embed_array = embed_array.reshape(1, -1)

                embedding_list.append(embed_array)
            except Exception as e:
                logger.error(f"Error processing embedding for image {i}: {e}")
                # 添加零向量作为占位符
                if len(embedding_list) > 0:
                    embedding_list.append(np.zeros_like(embedding_list[0]))
                else:
                    # If the first embedding fails, we can't determine the dimension.
                    # It's safer to return an empty array for this batch.
                    logger.error(f"Failed to process embedding for image {i}; cannot determine embedding dimension.")
                    return np.array([])

        # 堆叠成二维数组
        embeddings = np.vstack(embedding_list) if len(embedding_list) > 0 else np.array([])

        logger.info(f"Generated embeddings: shape={embeddings.shape}, dtype={embeddings.dtype}")
        return embeddings

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

        if self._detection_model is not None:
            del self._detection_model
            self._detection_model = None
            logger.info("Detection model unloaded")

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
