"""
OCR服务模块
使用本地 OCR API 识别注册号
"""

import os
import logging
import re
import json
import base64
import requests
from typing import Dict, Any, Optional
from PIL import Image

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
        self.lang = config.get("lang", "ch")
        self.use_angle_cls = config.get("use_angle_cls", True)
        self.use_gpu = config.get("use_gpu", True)
        self.enabled = config.get("enabled", True)
        self.ocr = None
        self.use_new_api = False  # 是否使用 PaddleOCR 3.x 新 API

        if not self.enabled:
            logger.info("OCR is disabled")
            return

        logger.info(f"OCR API initialized (url={self.api_url})")

    def _init_ocr(self):
        """初始化 PaddleOCR"""
        # 尝试使用 PaddleOCR 3.x 新 API
        try:
            from paddleocr import PaddleOCR

            # 构建初始化参数，过滤掉不支持的参数
            ocr_init_params = {"use_angle_cls": self.use_angle_cls, "lang": self.lang}

            # 检查是否支持 use_gpu 参数
            try:
                import paddle

                if paddle.is_compiled_with_cuda() and self.use_gpu:
                    ocr_init_params["use_gpu"] = True
            except:
                pass

            # 尝试初始化
            try:
                self.ocr = PaddleOCR(**ocr_init_params)
                self.use_new_api = False
                logger.info(
                    f"PaddleOCR initialized (lang={self.lang}, params={list(ocr_init_params.keys())})"
                )
            except TypeError as e:
                # 如果参数错误，尝试仅使用基本参数
                if "use_gpu" in str(e) or "show_log" in str(e):
                    ocr_init_params = {
                        "use_angle_cls": self.use_angle_cls,
                        "lang": self.lang,
                    }
                    self.ocr = PaddleOCR(**ocr_init_params)
                    self.use_new_api = False
                    logger.info(
                        f"PaddleOCR initialized with basic params (lang={self.lang})"
                    )
                else:
                    raise

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
        if not self.enabled:
            return {
                "registration": "",
                "confidence": 0.0,
                "raw_text": "",
                "all_matches": [],
                "yolo_boxes": [],
            }

        try:
            # 获取图片尺寸
            image = Image.open(image_path)
            img_width, img_height = image.size

            # OCR识别
            # 注意：PaddleOCR 3.x 新版本不支持 cls 参数
            ocr_results = self.ocr.ocr(img_array)

                if not rec_texts:
                    return {
                        "registration": "",
                        "confidence": 0.0,
                        "raw_text": "",
                        "all_matches": [],
                        "yolo_boxes": []
                    }

            except (KeyError, IndexError) as e:
                logger.error(f"Failed to parse OCR results: {e}")
                return {
                    "registration": "",
                    "confidence": 0.0,
                    "raw_text": "",
                    "all_matches": [],
                    "yolo_boxes": [],
                }

            all_texts = []
            yolo_boxes = []

            # 处理每个识别结果
            for i, (text, score, box) in enumerate(zip(rec_texts, rec_scores, rec_boxes)):
                # box 格式: [xmin, ymin, xmax, ymax]
                xmin, ymin, xmax, ymax = box

                # 转换为YOLO格式
                x_center = (xmin + xmax) / 2.0 / img_width
                y_center = (ymin + ymax) / 2.0 / img_height
                box_width = (xmax - xmin) / img_width
                box_height = (ymax - ymin) / img_height

                all_texts.append(
                    {
                        "text": text,
                        "confidence": confidence,
                        "box": [x_center, y_center, box_width, box_height],
                    }
                )

                yolo_boxes.append(
                    {
                        "class_id": 0,
                        "x_center": round(x_center, 6),
                        "y_center": round(y_center, 6),
                        "width": round(box_width, 6),
                        "height": round(box_height, 6),
                        "text": text,
                        "confidence": float(confidence),
                    }
                )

            raw_text = " ".join(rec_texts)
            matches = self._filter_registrations(all_texts)

            if not matches:
                return {
                    "registration": "",
                    "confidence": 0.0,
                    "raw_text": raw_text,
                    "all_matches": [],
                    "yolo_boxes": yolo_boxes,
                }

            best_match = max(matches, key=lambda x: x["confidence"])
            yolo_box = best_match.get("box")

            registration_area = ""
            if yolo_box:
                registration_area = (
                    f"{yolo_box[0]} {yolo_box[1]} {yolo_box[2]} {yolo_box[3]}"
                )

            return {
                "registration": best_match["text"],
                "confidence": float(best_match["confidence"]),
                "raw_text": raw_text,
                "all_matches": matches,
                "yolo_boxes": yolo_boxes,
                "registration_area": registration_area,
            }

        except Exception as e:
            logger.error(f"OCR recognition error: {e}")
            return {
                "registration": "",
                "confidence": 0.0,
                "raw_text": "",
                "all_matches": [],
                "yolo_boxes": [],
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
                matches.append(
                    {
                        "text": registration,
                        "confidence": confidence,
                        "box": result["box"],
                    }
                )

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
        except Exception:
            pass

    def __del__(self):
        """析构时自动清理"""
        pass
