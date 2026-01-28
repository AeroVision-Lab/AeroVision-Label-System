"""
API单元测试
测试各个API端点，使用mock隔离依赖
"""

import pytest
import os
import sys
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from database import Database


@pytest.fixture
def temp_db():
    """创建临时数据库"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db = Database(db_path)

    # 添加一些测试数据
    db.add_airline("CCA", "中国国航")
    db.add_airline("CSN", "中国南方航空")
    db.add_aircraft_type("A320", "空客A320")
    db.add_aircraft_type("B738", "波音737-800")

    yield db, db_path

    # 清理
    os.unlink(db_path)


@pytest.fixture
def client(temp_db):
    """创建测试客户端"""
    db, db_path = temp_db

    app.config["TESTING"] = True
    app.config["DATABASE_PATH"] = db_path

    # 创建临时目录
    images_dir = tempfile.mkdtemp()
    labeled_dir = tempfile.mkdtemp()

    # 更新全局变量（app.py 使用的）
    import app as app_module

    original_images_dir = app_module.IMAGES_DIR
    original_labeled_dir = app_module.LABELED_DIR
    original_db_path = app_module.DATABASE_PATH

    app_module.IMAGES_DIR = images_dir
    app_module.LABELED_DIR = labeled_dir
    app_module.DATABASE_PATH = db_path

    # 更新 app.py 中的 db 实例
    original_app_db = app_module.db
    app_module.db = db

    yield app.test_client(), db, images_dir, labeled_dir

    # 恢复原始设置
    app_module.IMAGES_DIR = original_images_dir
    app_module.LABELED_DIR = original_labeled_dir
    app_module.DATABASE_PATH = original_db_path
    app_module.db = original_app_db

    # 清理临时目录
    import shutil

    shutil.rmtree(images_dir, ignore_errors=True)
    shutil.rmtree(labeled_dir, ignore_errors=True)


class TestAPI:
    """API端点测试"""

    def test_get_airlines(self, client):
        """测试获取航司列表"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.get("/api/airlines")
        assert response.status_code == 200

        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_add_airline(self, client):
        """测试添加航司"""
        test_client, db, images_dir, labeled_dir = client

        # 使用不存在的航司代码
        new_airline = {"code": "TEST01", "name": "测试航司01"}

        response = test_client.post(
            "/api/airlines", json=new_airline, content_type="application/json"
        )
        assert response.status_code == 201

        data = response.get_json()
        assert data["code"] == "TEST01"
        assert data["name"] == "测试航司01"

    def test_add_airline_missing_fields(self, client):
        """测试添加航司缺少必填字段"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.post(
            "/api/airlines", json={"code": "TEST"}, content_type="application/json"
        )
        assert response.status_code == 400

    def test_get_aircraft_types(self, client):
        """测试获取机型列表"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.get("/api/aircraft-types")
        assert response.status_code == 200

        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_add_aircraft_type(self, client):
        """测试添加机型"""
        test_client, db, images_dir, labeled_dir = client

        # 使用不存在的机型代码
        new_type = {"code": "TEST01", "name": "测试机型01"}

        response = test_client.post(
            "/api/aircraft-types", json=new_type, content_type="application/json"
        )
        assert response.status_code == 201

        data = response.get_json()
        assert data["code"] == "TEST01"
        assert data["name"] == "测试机型01"

    def test_get_labels(self, client):
        """测试获取标注列表"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.get("/api/labels")
        assert response.status_code == 200

        data = response.get_json()
        assert "total" in data
        assert "items" in data
        assert "page" in data
        assert "per_page" in data

    def test_get_images(self, client):
        """测试获取图片列表"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.get("/api/images?user_id=test_user")
        assert response.status_code == 200

        data = response.get_json()
        assert "total" in data
        assert "items" in data

    def test_skip_image(self, client):
        """测试跳过图片"""
        test_client, db, images_dir, labeled_dir = client

        # 创建测试图片
        test_image_path = os.path.join(images_dir, "test.jpg")
        with open(test_image_path, "wb") as f:
            f.write(b"fake image data")

        response = test_client.post(
            "/api/images/skip",
            json={"filename": "test.jpg"},
            content_type="application/json",
        )
        assert response.status_code == 200

        # 检查是否跳过
        skipped = db.get_skipped_filenames()
        assert "test.jpg" in skipped

    def test_skip_image_not_found(self, client):
        """测试跳过不存在的图片"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.post(
            "/api/images/skip",
            json={"filename": "nonexistent.jpg"},
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_create_label(self, client):
        """测试创建标注"""
        test_client, db, images_dir, labeled_dir = client

        # 创建测试图片
        test_image_path = os.path.join(images_dir, "test.jpg")
        with open(test_image_path, "wb") as f:
            f.write(b"fake image data")

        label_data = {
            "original_file_name": "test.jpg",
            "type_id": "A320",
            "type_name": "空客A320",
            "airline_id": "CCA",
            "airline_name": "中国国航",
            "clarity": 0.9,
            "block": 0.1,
            "registration": "B-1234",
            "registration_area": "0.5 0.5 0.2 0.1",
        }

        response = test_client.post(
            "/api/labels", json=label_data, content_type="application/json"
        )
        assert response.status_code == 201

        data = response.get_json()
        assert "id" in data
        assert "file_name" in data

    def test_create_label_missing_fields(self, client):
        """测试创建标注缺少必填字段"""
        test_client, db, images_dir, labeled_dir = client

        incomplete_data = {"type_id": "A320", "type_name": "空客A320"}

        response = test_client.post(
            "/api/labels", json=incomplete_data, content_type="application/json"
        )
        assert response.status_code == 400

    def test_get_stats(self, client):
        """测试获取统计信息"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.get("/api/stats")
        assert response.status_code == 200

        data = response.get_json()
        assert "total_labeled" in data
        assert "unlabeled" in data
        assert "by_type" in data
        assert "by_airline" in data

    def test_acquire_lock(self, client):
        """测试获取图片锁"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.post(
            "/api/locks/acquire",
            json={"filename": "test.jpg", "user_id": "user1"},
            content_type="application/json",
        )
        assert response.status_code == 200

        # 检查锁是否获取成功
        lock_info = db.get_lock_info("test.jpg")
        assert lock_info is not None
        assert lock_info["user_id"] == "user1"

    def test_acquire_lock_conflict(self, client):
        """测试锁冲突"""
        test_client, db, images_dir, labeled_dir = client

        # 第一个用户获取锁
        test_client.post(
            "/api/locks/acquire",
            json={"filename": "test.jpg", "user_id": "user1"},
            content_type="application/json",
        )

        # 第二个用户尝试获取同一文件的锁
        response = test_client.post(
            "/api/locks/acquire",
            json={"filename": "test.jpg", "user_id": "user2"},
            content_type="application/json",
        )
        assert response.status_code == 409

    def test_release_lock(self, client):
        """测试释放锁"""
        test_client, db, images_dir, labeled_dir = client

        # 先获取锁
        test_client.post(
            "/api/locks/acquire",
            json={"filename": "test.jpg", "user_id": "user1"},
            content_type="application/json",
        )

        # 释放锁
        response = test_client.post(
            "/api/locks/release",
            json={"filename": "test.jpg", "user_id": "user1"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_get_lock_status(self, client):
        """测试获取锁状态"""
        test_client, db, images_dir, labeled_dir = client

        # 获取锁
        test_client.post(
            "/api/locks/acquire",
            json={"filename": "test.jpg", "user_id": "user1"},
            content_type="application/json",
        )

        # 查询锁状态
        response = test_client.get("/api/locks/status/test.jpg")
        assert response.status_code == 200

        data = response.get_json()
        assert data["locked"] is True
        assert data["user_id"] == "user1"

    def test_export_labels_csv(self, client):
        """测试导出CSV"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.get("/api/labels/export")
        assert response.status_code == 200
        assert "text/csv" in response.content_type

    def test_export_labels_yolo(self, client):
        """测试导出YOLO格式"""
        test_client, db, images_dir, labeled_dir = client

        response = test_client.get("/api/labels/export-yolo")
        assert response.status_code == 200
        assert "application/zip" in response.content_type

    def test_ai_status_when_disabled(self, client):
        """测试AI服务状态（AI禁用时）"""
        test_client, db, images_dir, labeled_dir = client

        # 模拟AI服务禁用
        import app as app_module

        original_predictor = app_module.ai_predictor
        original_enabled = app_module.ai_enabled

        app_module.ai_predictor = None
        app_module.ai_enabled = False

        response = test_client.get("/api/ai/status")

        # 恢复原始值
        app_module.ai_predictor = original_predictor
        app_module.ai_enabled = original_enabled

        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.get_json()
            assert "enabled" in data
            assert data["enabled"] is False


class TestAIAPI:
    """AI相关API测试"""

    @patch("app.ai_predictor")
    def test_ai_status_when_enabled(self, mock_predictor, client):
        """测试AI服务状态（AI启用时）"""
        test_client, db, images_dir, labeled_dir = client

        # 模拟AI服务启用
        import app as app_module

        mock_predictor.get_config.return_value = {}
        mock_predictor.is_enabled.return_value = True
        original_predictor = app_module.ai_predictor
        original_enabled = app_module.ai_enabled

        app_module.ai_predictor = mock_predictor
        app_module.ai_enabled = True

        response = test_client.get("/api/ai/status")

        # 恢复原始值
        app_module.ai_predictor = original_predictor
        app_module.ai_enabled = original_enabled

        assert response.status_code == 200

        data = response.get_json()
        assert data["enabled"] is True

    @patch("app.ai_predictor")
    def test_ai_predict_single(self, mock_predictor, client):
        """测试单张图片AI预测"""
        test_client, db, images_dir, labeled_dir = client

        # 创建测试图片
        test_image_path = os.path.join(images_dir, "test.jpg")
        with open(test_image_path, "wb") as f:
            f.write(b"fake image data")

        # 模拟预测结果
        mock_predictor.predict_single.return_value = {
            "filename": "test.jpg",
            "aircraft_class": "A320",
            "aircraft_confidence": 0.95,
            "airline_class": "CCA",
            "airline_confidence": 0.93,
            "registration": "B-1234",
            "registration_area": "0.5 0.5 0.2 0.1",
            "clarity": 0.85,
            "block": 0.15,
            "quality_score": 0.9,
            "prediction_time": 1.5,
        }

        import app as app_module

        original_predictor = app_module.ai_predictor
        original_enabled = app_module.ai_enabled

        app_module.ai_predictor = mock_predictor
        app_module.ai_enabled = True

        response = test_client.post(
            "/api/ai/predict",
            json={"filename": "test.jpg"},
            content_type="application/json",
        )

        # 恢复原始值
        app_module.ai_predictor = original_predictor
        app_module.ai_enabled = original_enabled

        assert response.status_code == 200

        # 验证调用
        mock_predictor.predict_single.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
