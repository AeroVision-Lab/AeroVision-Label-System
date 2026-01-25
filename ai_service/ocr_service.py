"""
OCR服务模块
使用PaddleOCR识别注册号
"""

import logging
import re
from typing import Dict, Any, Optional
import numpy as np
from PIL import Image

# 延迟导入PaddleOCR以避免初始化问题
_PaddleOCR = None


def get_paddleocr():
    """延迟导入PaddleOCR"""
    global _PaddleOCR
    if _PaddleOCR is None:
        from paddleocr import PaddleOCR
        _PaddleOCR = PaddleOCR
    return _PaddleOCR


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 注册号正则表达式
REGISTRATION_PATTERN = re.compile(
    r"\b([A-Z]{1,2})[- ]?([A-HJ-NP-Z0-9][A-HJ-NP-Z0-9]{0,4})\b"
)


class RegistrationOCR:
    """注册号OCR识别器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化OCR识别器

        Args:
            config: OCR配置
        """
        self.lang = config.get('lang', 'ch')
        self.use_angle_cls = config.get('use_angle_cls', True)
        self.enabled = config.get('enabled', True)

        if not self.enabled:
            logger.info("OCR is disabled")
            self.ocr = None
            return

        try:
            PaddleOCR = get_paddleocr()
            self.ocr = PaddleOCR(
                use_angle_cls=self.use_angle_cls,
                lang=self.lang,
                show_log=False
            )
            logger.info(f"PaddleOCR initialized (lang={self.lang})")
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            self.ocr = None

    def recognize(self, image_path: str) -> Dict[str, Any]:
        """
        识别注册号

        Args:
            image_path: 图片文件路径

        Returns:
            包含识别结果的字典
        """
        if not self.enabled or self.ocr is None:
            return {
                "registration": "",
                "confidence": 0.0,
                "raw_text": "",
                "all_matches": [],
                "yolo_boxes": []
            }

        try:
            # 加载图片
            image = Image.open(image_path)
            img_array = np.array(image)
            img_width, img_height = image.size

            # OCR识别
            ocr_results = self.ocr.ocr(img_array, cls=True)

            if not ocr_results or not ocr_results[0]:
                return {
                    "registration": "",
                    "confidence": 0.0,
                    "raw_text": "",
                    "all_matches": [],
                    "yolo_boxes": []
                }

            all_texts = []
            yolo_boxes = []

            for result in ocr_results[0]:
                if not result or len(result) < 2:
                    continue

                box_points = result[0]
                text_info = result[1]

                if not box_points or not text_info:
                    continue

                text = text_info[0]
                confidence = text_info[1]

                # 提取边界框
                xmin = min(point[0] for point in box_points)
                ymin = min(point[1] for point in box_points)
                xmax = max(point[0] for point in box_points)
                ymax = max(point[1] for point in box_points)

                # 转换为YOLO格式
                x_center = (xmin + xmax) / 2.0 / img_width
                y_center = (ymin + ymax) / 2.0 / img_height
                box_width = (xmax - xmin) / img_width
                box_height = (ymax - ymin) / img_height

                all_texts.append({
                    "text": text,
                    "confidence": confidence,
                    "box": [x_center, y_center, box_width, box_height]
                })

                yolo_boxes.append({
                    "class_id": 0,
                    "x_center": round(x_center, 6),
                    "y_center": round(y_center, 6),
                    "width": round(box_width, 6),
                    "height": round(box_height, 6),
                    "text": text,
                    "confidence": float(confidence)
                })

            raw_text = " ".join([t["text"] for t in all_texts])
            matches = self._filter_registrations(all_texts)

            if not matches:
                return {
                    "registration": "",
                    "confidence": 0.0,
                    "raw_text": raw_text,
                    "all_matches": [],
                    "yolo_boxes": yolo_boxes
                }

            best_match = max(matches, key=lambda x: x["confidence"])
            yolo_box = best_match.get("box")

            registration_area = ""
            if yolo_box:
                registration_area = f"{yolo_box[0]} {yolo_box[1]} {yolo_box[2]} {yolo_box[3]}"

            return {
                "registration": best_match["text"],
                "confidence": float(best_match["confidence"]),
                "raw_text": raw_text,
                "all_matches": matches,
                "yolo_boxes": yolo_boxes,
                "registration_area": registration_area
            }

        except Exception as e:
            logger.error(f"OCR recognition error: {e}")
            return {
                "registration": "",
                "confidence": 0.0,
                "raw_text": "",
                "all_matches": [],
                "yolo_boxes": []
            }

    def _filter_registrations(self, ocr_results: list) -> list:
        """使用正则表达式过滤注册号"""
        matches = []

        for result in ocr_results:
            text = result["text"]
            confidence = result["confidence"]

            match = REGISTRATION_PATTERN.search(text)
            if match:
                registration = match.group(0)
                matches.append({
                    "text": registration,
                    "confidence": confidence,
                    "box": result["box"]
                })

        return matches

    def cleanup(self):
        """清理OCR资源，释放内存"""
        if self.ocr is not None:
            del self.ocr
            self.ocr = None
            logger.info("PaddleOCR resources cleaned up")

        # 清理 CUDA 缓存（如果使用了 GPU）
        try:
            import paddle
            if paddle.is_compiled_with_cuda():
                paddle.device.cuda.empty_cache()
                logger.info("Paddle CUDA cache cleared")
        except ImportError:
            pass

    def __del__(self):
        """析构时自动清理"""
        self.cleanup()
