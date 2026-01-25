"""
质量评估服务
使用VLM进行图像质量评估
"""

import logging
from typing import Dict, Any, Optional
from PIL import Image
import io
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QualityAssessor:
    """质量评估器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化质量评估器

        Args:
            config: 质量评估配置
        """
        self.enabled = config.get('enabled', True)
        self.api_key = config.get('api_key') or os.getenv('GLM_API_KEY')
        self.api_url = config.get('api_url', 'https://open.bigmodel.cn/api/paas/v4/chat/completions')
        self.model = config.get('model', 'glm-4.6v')

        if not self.enabled:
            logger.info("Quality assessment is disabled")
            self.client = None
            return

        if not self.api_key:
            logger.warning("GLM API key not configured. Quality assessment will be disabled.")
            self.enabled = False
            self.client = None
            return

        # 尝试导入GLM客户端
        try:
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=self.api_key)
            logger.info(f"QualityAssessor initialized with model: {self.model}")
        except ImportError:
            logger.warning("zhipuai package not found. Install with: pip install zhipuai")
            self.client = None
            self.enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize GLM client: {e}")
            self.client = None
            self.enabled = False

    def assess(self, image_path: str) -> Dict[str, Any]:
        """
        评估图像质量

        Args:
            image_path: 图片文件路径

        Returns:
            包含质量评估结果的字典
        """
        if not self.enabled or self.client is None:
            # 返回默认值
            return {
                "clarity": 0.8,
                "block": 0.2,
                "confidence": 0.0,
                "reasoning": "Quality assessment disabled"
            }

        try:
            # 加载图片
            image = Image.open(image_path)

            # 转换为字节流
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG")
            buffer.seek(0)
            image_bytes = buffer.read()

            # 构造API请求
            system_prompt = """你是一个专业的图像质量评估专家。你的任务是对提供的飞机图片进行质量评估。

评估要求：
1. 清晰度评分（clarity）：评估图片的整体清晰度，范围0.0-1.0
2. 遮挡程度评分（block）：评估飞机被遮挡的程度，范围0.0-1.0
3. 给出评估结果的置信度（0-1之间的数值，1表示完全确定）

清晰度评分标准：
- 0.9-1.0：非常清晰（细节锐利，可看清小字）
- 0.7-0.9：清晰（整体清晰，细节略有模糊）
- 0.5-0.7：一般（能辨认机型，但不够锐利）
- 0.3-0.5：模糊（勉强能辨认）
- 0.0-0.3：非常模糊（几乎无法辨认）

遮挡程度评分标准：
- 0.0：无遮挡（飞机完全可见）
- 0.1-0.3：轻微遮挡（一小部分被遮挡）
- 0.3-0.5：部分遮挡（约1/3被遮挡）
- 0.5-0.7：明显遮挡（约一半被遮挡）
- 0.7-1.0：严重遮挡（大部分被遮挡）

请严格按照以下JSON格式输出，不要包含任何其他内容：
{"clarity": 0.85, "block": 0.17, "confidence": 0.66, "reasoning": "评估理由简述"}"""

            user_prompt = "请对这张飞机图片进行质量评估。"

            # 调用API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{self._image_to_base64(image_bytes)}"}}
                    ]}
                ],
                temperature=0.1,
                max_tokens=512
            )

            # 解析响应
            content = response.choices[0].message.content

            # 尝试提取JSON
            import json
            try:
                # 查找JSON部分
                start = content.find('{')
                end = content.rfind('}') + 1
                json_str = content[start:end]
                parsed = json.loads(json_str)

                # 验证数据
                required_fields = ["clarity", "block", "confidence"]
                for field in required_fields:
                    if field not in parsed:
                        raise ValueError(f"Missing required field: {field}")

                clarity = float(parsed["clarity"])
                block = float(parsed["block"])
                confidence = float(parsed["confidence"])

                if not (0.0 <= clarity <= 1.0):
                    raise ValueError(f"Clarity out of range: {clarity}")
                if not (0.0 <= block <= 1.0):
                    raise ValueError(f"Block out of range: {block}")

                return {
                    "clarity": clarity,
                    "block": block,
                    "confidence": confidence,
                    "reasoning": parsed.get("reasoning", "")
                }

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.warning(f"Failed to parse GLM response: {e}, content: {content}")
                return {
                    "clarity": 0.8,
                    "block": 0.2,
                    "confidence": 0.0,
                    "reasoning": f"Failed to parse response: {str(e)}"
                }

        except Exception as e:
            logger.error(f"Quality assessment error: {e}")
            return {
                "clarity": 0.8,
                "block": 0.2,
                "confidence": 0.0,
                "reasoning": f"Error: {str(e)}"
            }

    def _image_to_base64(self, image_bytes: bytes) -> str:
        """将图片字节流转换为base64"""
        import base64
        return base64.b64encode(image_bytes).decode('utf-8')

    def cleanup(self):
        """清理质量评估器资源"""
        if self.client is not None:
            del self.client
            self.client = None
            logger.info("QualityAssessor resources cleaned up")

    def __del__(self):
        """析构时自动清理"""
        self.cleanup()
