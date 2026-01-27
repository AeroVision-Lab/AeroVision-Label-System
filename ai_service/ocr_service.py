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
        # 从环境变量读取 OCR API URL（优先级：环境变量 > 默认值）
        self.api_url = os.getenv('OCR_API_URL', 'http://localhost:8000/v2/models/ocr/infer')
        self.enabled = config.get('enabled', True)
        self.timeout = config.get('timeout', 30)

        if not self.enabled:
            logger.info("OCR is disabled")
            return

        logger.info(f"OCR API initialized (url={self.api_url})")

    def _call_ocr_api(self, image_path: str) -> Optional[Dict]:
        """
        调用 OCR API

        Args:
            image_path: 图片文件路径

        Returns:
            API 响应数据
        """
        try:
            # 读取图片并转换为 base64 编码
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
                image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # 构建请求数据，使用 base64 编码的图片
            payload = {
                "inputs": [
                    {
                        "name": "input",
                        "shape": [1, 1],
                        "datatype": "BYTES",
                        "data": [
                            json.dumps({
                                "file": f"data:image/jpeg;base64,{image_base64}",
                                "visualize": False
                            })
                        ]
                    }
                ],
                "outputs": [
                    {
                        "name": "output"
                    }
                ]
            }

            # 发送请求
            response = requests.post(
                self.api_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=self.timeout
            )
            response.raise_for_status()

            # 解析响应（兼容 BYTES 嵌套 JSON 与多重转义）
            result = response.json()
            if not result.get('outputs'):
                logger.error("No outputs in API response")
                return None

            outputs = result.get('outputs', [])
            # 优先按名称找到名为 output 的输出
            output_obj = None
            for out in outputs:
                if out.get('name') == 'output':
                    output_obj = out
                    break
            if output_obj is None and outputs:
                output_obj = outputs[0]

            data_list = output_obj.get('data') or []
            if not data_list:
                logger.error("Empty 'data' in OCR API response output")
                return None

            raw_val = data_list[0]

            def _to_text(val: Any) -> Optional[str]:
                if val is None:
                    return None
                if isinstance(val, bytes):
                    try:
                        return val.decode('utf-8', errors='replace')
                    except Exception:
                        return None
                if isinstance(val, str):
                    return val
                # Triton 有时会返回 {"b64": "..."}
                if isinstance(val, dict):
                    b64 = val.get('b64') or val.get('base64')
                    if b64:
                        try:
                            decoded = base64.b64decode(b64)
                            return decoded.decode('utf-8', errors='replace')
                        except Exception as e:
                            logger.error(f"Failed to base64-decode OCR output: {e}")
                            return None
                return None

            text = _to_text(raw_val)
            if text is None:
                logger.error("Unsupported OCR output value type; cannot convert to text")
                return None

            # 有些后端会把 JSON 再次转义，需要尝试多次反序列化
            parsed: Any = text
            for _ in range(2):
                try:
                    parsed = json.loads(parsed)
                except Exception:
                    break
                # 如果仍是字符串且看起来像 JSON，则再解一层
                if isinstance(parsed, str) and (parsed.strip().startswith('{') or parsed.strip().startswith('[')):
                    continue
                else:
                    break

            if isinstance(parsed, str):
                # 最终还是字符串且不是 JSON，无法解析
                logger.error("OCR output is not valid JSON after unescaping")
                return None

            if not isinstance(parsed, dict):
                logger.error("OCR output JSON is not an object")
                return None

            return parsed

        except FileNotFoundError as e:
            logger.error(f"Image file not found: {image_path}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"OCR API request failed: {e}")
            return None
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Failed to parse OCR API response: {e}")
            return None

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
                "yolo_boxes": []
            }

        try:
            # 获取图片尺寸
            image = Image.open(image_path)
            img_width, img_height = image.size

            # 调用 OCR API
            ocr_data = self._call_ocr_api(image_path)
            if not ocr_data:
                return {
                    "registration": "",
                    "confidence": 0.0,
                    "raw_text": "",
                    "all_matches": [],
                    "yolo_boxes": []
                }

            # 解析 OCR 结果
            try:
                pruned_result = ocr_data['result']['ocrResults'][0]['prunedResult']
                rec_texts = pruned_result.get('rec_texts', [])
                rec_scores = pruned_result.get('rec_scores', [])
                rec_boxes = pruned_result.get('rec_boxes', [])
                # 如果没有提供矩形框，尝试从多边形转换
                if (not rec_boxes) and pruned_result.get('rec_polys'):
                    rec_boxes = []
                    for poly in pruned_result['rec_polys']:
                        # poly: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                        xs = [p[0] for p in poly]
                        ys = [p[1] for p in poly]
                        xmin, xmax = min(xs), max(xs)
                        ymin, ymax = min(ys), max(ys)
                        rec_boxes.append([xmin, ymin, xmax, ymax])

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
                    "yolo_boxes": []
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

                all_texts.append({
                    "text": text,
                    "confidence": score,
                    "box": [x_center, y_center, box_width, box_height]
                })

                yolo_boxes.append({
                    "class_id": 0,
                    "x_center": round(x_center, 6),
                    "y_center": round(y_center, 6),
                    "width": round(box_width, 6),
                    "height": round(box_height, 6),
                    "text": text,
                    "confidence": float(score)
                })

            raw_text = " ".join(rec_texts)
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

            return {
                "registration": best_match["text"],
                "confidence": float(best_match["confidence"]),
                "raw_text": raw_text,
                "all_matches": matches,
                "yolo_boxes": yolo_boxes
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
        logger.info("OCR API client cleanup (no resources to release)")

    def __del__(self):
        """析构时自动清理"""
        pass
