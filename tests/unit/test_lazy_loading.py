"""
AI模型懒加载测试 - TDD
测试模型应该在需要时才加载，避免启动时立即加载所有模型
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_service.ai_predictor import AIPredictor
from ai_service.predictor import ModelPredictor


@pytest.fixture
def sample_config():
    """示例配置"""
    return {
        "models": {
            "aircraft": {
                "path": "/fake/path/aircraft.pt",
                "device": "cpu",
                "image_size": 640,
            },
            "airline": {
                "path": "/fake/path/airline.pt",
                "device": "cpu",
                "image_size": 640,
            },
        },
        "ocr": {"enabled": True, "timeout": 30},
        "quality": {"enabled": True},
        "hdbscan": {"enabled": True, "min_cluster_size": 5, "min_samples": 3},
    }


@pytest.fixture
def temp_config_file(sample_config):
    """创建临时配置文件"""
    import tempfile
    import yaml

    fd, config_path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)

    with open(config_path, "w") as f:
        yaml.dump(sample_config, f)

    yield config_path

    if os.path.exists(config_path):
        os.unlink(config_path)


class TestModelPredictorLazyLoading:
    """ModelPredictor 懒加载测试"""

    @patch("ai_service.predictor.YOLO")
    @patch("ai_service.predictor.Path")
    def test_init_should_not_load_models(self, mock_path, mock_yolo, sample_config):
        """测试：初始化时不应该加载模型"""
        mock_path.exists.return_value = True
        mock_path.return_value = MagicMock()

        # 初始化 ModelPredictor
        predictor = ModelPredictor(sample_config["models"])

        # 验证：YOLO 构造函数没有被调用（模型未加载）
        assert not mock_yolo.called, "初始化时不应该加载模型"
        assert predictor._aircraft_model is None
        assert predictor._airline_model is None

    @patch("ai_service.predictor.YOLO")
    @patch("ai_service.predictor.Path")
    def test_property_access_triggers_loading(self, mock_path, mock_yolo, sample_config):
        """测试：访问 property 时才加载对应模型"""
        mock_path.exists.return_value = True
        mock_path.return_value = MagicMock()

        mock_aircraft_model = MagicMock()
        mock_aircraft_model.predict.return_value = []
        mock_airline_model = MagicMock()
        mock_airline_model.predict.return_value = []
        mock_yolo.side_effect = [mock_aircraft_model, mock_airline_model]

        predictor = ModelPredictor(sample_config["models"])

        # 验证：初始化后模型未加载
        assert predictor._aircraft_model is None

        # 访问 aircraft_model property
        aircraft_model = predictor.aircraft_model

        # 验证：YOLO 被调用一次（只加载了 aircraft model）
        assert mock_yolo.call_count == 1
        assert aircraft_model is not None

    @patch("ai_service.predictor.YOLO")
    @patch("ai_service.predictor.Path")
    def test_predict_lazy_loads_aircraft_and_airline(self, mock_path, mock_yolo, sample_config):
        """测试：predict() 方法按需加载机型和航司模型"""
        import numpy as np

        mock_path.exists.return_value = True
        mock_path.return_value = MagicMock()

        # 模拟模型 - 使用正确的数据类型
        mock_aircraft_model = MagicMock()
        mock_result_aircraft = MagicMock()
        mock_result_aircraft.probs = MagicMock()
        # 使用 numpy 数组模拟 probs.data
        mock_result_aircraft.probs.data = np.array([0.1, 0.9])
        mock_result_aircraft.probs.top1 = 1
        mock_result_aircraft.probs.top5 = [0, 1]
        mock_aircraft_model.predict.return_value = [mock_result_aircraft]
        mock_aircraft_model.names = {0: "A320", 1: "B738"}

        mock_airline_model = MagicMock()
        mock_result_airline = MagicMock()
        mock_result_airline.probs = MagicMock()
        # 使用 numpy 数组模拟 probs.data
        mock_result_airline.probs.data = np.array([0.2, 0.8])
        mock_result_airline.probs.top1 = 1
        mock_result_airline.probs.top5 = [0, 1]
        mock_airline_model.predict.return_value = [mock_result_airline]
        mock_airline_model.names = {0: "CCA", 1: "CSN"}

        mock_yolo.side_effect = [mock_aircraft_model, mock_airline_model]

        predictor = ModelPredictor(sample_config["models"])

        # 创建测试图片
        import tempfile
        fd, test_image = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)

        try:
            # 调用 predict
            result = predictor.predict(test_image)

            # 验证：两个模型都被加载了（predict需要它们）
            assert mock_yolo.call_count >= 2
            assert predictor._aircraft_model is not None
            assert predictor._airline_model is not None
            assert "aircraft" in result
            assert "airline" in result
        finally:
            os.unlink(test_image)

    @patch("ai_service.predictor.YOLO")
    @patch("ai_service.predictor.Path")
    def test_predict_only_loads_needed_model(self, mock_path, mock_yolo, sample_config):
        """测试：只加载需要的模型（例如只需要机型分类）"""
        mock_path.exists.return_value = True
        mock_path.return_value = MagicMock()

        mock_aircraft_model = MagicMock()
        mock_result = MagicMock()
        mock_result.probs = MagicMock()
        mock_result.probs.data = [0.1, 0.9]
        mock_result.probs.top1 = 1
        mock_result.probs.top5 = [0, 1]
        mock_aircraft_model.predict.return_value = [mock_result]
        mock_aircraft_model.names = {0: "A320", 1: "B738"}
        mock_yolo.return_value = mock_aircraft_model

        predictor = ModelPredictor(sample_config["models"])

        # 只访问 aircraft_model
        _ = predictor.aircraft_model

        # 验证：只加载了一个模型
        assert mock_yolo.call_count == 1
        assert predictor._aircraft_model is not None
        assert predictor._airline_model is None


class TestAIPredictorLazyLoading:
    """AIPredictor 懒加载测试"""

    @patch("ai_service.ai_predictor.ModelPredictor")
    @patch("ai_service.ai_predictor.RegistrationOCR")
    @patch("ai_service.ai_predictor.ImageQualityAssessor")
    @patch("ai_service.ai_predictor.HDBSCANNewClassDetector")
    @patch("ai_service.ai_predictor.yaml.safe_load")
    def test_init_should_not_load_models(
        self, mock_yaml_load, mock_hdbscan, mock_quality, mock_ocr, mock_predictor, temp_config_file
    ):
        """测试：AIPredictor 初始化时不应该加载模型"""
        # Mock yaml 加载
        mock_yaml_load.return_value = {
            "models": {"aircraft": {"path": "/fake/aircraft.pt", "device": "cpu"},
                      "airline": {"path": "/fake/airline.pt", "device": "cpu"}},
            "ocr": {"enabled": True},
            "quality": {"enabled": True},
            "hdbscan": {"enabled": True},
        }

        # 初始化 AIPredictor
        predictor = AIPredictor(temp_config_file)

        # 验证：模型未加载
        assert predictor._models_loaded is False

    @patch("ai_service.ai_predictor.ModelPredictor")
    @patch("ai_service.ai_predictor.RegistrationOCR")
    @patch("ai_service.ai_predictor.ImageQualityAssessor")
    @patch("ai_service.ai_predictor.HDBSCANNewClassDetector")
    @patch("ai_service.ai_predictor.yaml.safe_load")
    def test_predict_batch_does_not_preload_models(
        self, mock_yaml_load, mock_hdbscan, mock_quality, mock_ocr, mock_predictor, temp_config_file
    ):
        """测试：predict_batch 不应该提前加载所有模型"""
        # Mock yaml 加载
        mock_yaml_load.return_value = {
            "models": {"aircraft": {"path": "/fake/aircraft.pt", "device": "cpu"},
                      "airline": {"path": "/fake/airline.pt", "device": "cpu"}},
            "ocr": {"enabled": True},
            "quality": {"enabled": True},
            "hdbscan": {"enabled": True},
        }

        # 模拟 ModelPredictor
        mock_predictor_instance = MagicMock()
        mock_predictor_instance.predict.return_value = {
            "aircraft": {"class_name": "B738", "confidence": 0.95, "class_id": 1, "top5": []},
            "airline": {"class_name": "CSN", "confidence": 0.93, "class_id": 1, "top5": []},
        }
        mock_predictor_instance.get_embeddings.return_value = None
        mock_predictor_instance.load_models = MagicMock()
        mock_predictor.return_value = mock_predictor_instance

        # 模拟其他组件
        mock_ocr_instance = MagicMock()
        mock_ocr_instance.recognize.return_value = {"registration": "B-1234", "confidence": 0.9}
        mock_ocr.return_value = mock_ocr_instance

        mock_quality_instance = MagicMock()
        mock_quality_instance.assess.return_value = {"score": 0.85}
        mock_quality.return_value = mock_quality_instance

        mock_hdbscan_instance = MagicMock()
        mock_hdbscan_instance.detect_new_classes.return_value = []
        mock_hdbscan_instance.get_outlier_scores.return_value = []
        mock_hdbscan.return_value = mock_hdbscan_instance

        predictor = AIPredictor(temp_config_file)

        # 创建测试图片
        import tempfile
        test_images = []
        for i in range(2):
            fd, path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            test_images.append(path)

        try:
            # 调用 predict_batch
            result = predictor.predict_batch(test_images, detect_new_classes=False)

            # 关键断言：load_models 不应该在开始时被调用
            assert not mock_predictor_instance.load_models.called, \
                "predict_batch 不应该在开始时调用 load_models"

            # 验证：predict 被调用（这会触发懒加载）
            assert mock_predictor_instance.predict.call_count == 2
        finally:
            for path in test_images:
                if os.path.exists(path):
                    os.unlink(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
