"""
数据库单元测试
测试数据库操作，使用临时数据库进行隔离
"""

import sys
import pytest
import os
import tempfile
import sqlite3
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database


@pytest.fixture
def temp_db():
    """创建临时数据库"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db = Database(db_path)
    yield db, db_path

    # 清理
    os.unlink(db_path)


@pytest.fixture
def db_with_data(temp_db):
    """创建包含测试数据的数据库"""
    db, db_path = temp_db

    # 添加测试数据
    db.add_airline("CCA", "中国国航")
    db.add_airline("CSN", "中国南方航空")
    db.add_aircraft_type("A320", "空客A320")
    db.add_aircraft_type("B738", "波音737-800")

    yield db


class TestDatabase:
    """数据库操作测试"""

    def test_database_initialization(self, temp_db):
        """测试数据库初始化"""
        db, db_path = temp_db

        # 检查表是否创建
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        required_tables = [
            "labels",
            "airlines",
            "aircraft_types",
            "image_locks",
            "skipped_images",
            "ai_predictions",
        ]
        for table in required_tables:
            assert table in tables, f"Table {table} not found"

    def test_add_airline(self, temp_db):
        """测试添加航司"""
        db, db_path = temp_db

        airline_id = db.add_airline("TEST", "测试航司")
        assert airline_id is not None

        # 检查数据是否正确插入
        airlines = db.get_airlines()
        assert len(airlines) == 1
        assert airlines[0]["code"] == "TEST"
        assert airlines[0]["name"] == "测试航司"

    def test_add_duplicate_airline(self, temp_db):
        """测试添加重复航司"""
        db, db_path = temp_db

        db.add_airline("TEST", "测试航司")

        # 添加重复航司应该失败
        with pytest.raises(sqlite3.IntegrityError):
            db.add_airline("TEST", "测试航司2")

    def test_add_aircraft_type(self, temp_db):
        """测试添加机型"""
        db, db_path = temp_db

        type_id = db.add_aircraft_type("T100", "测试机型")
        assert type_id is not None

        # 检查数据是否正确插入
        types = db.get_aircraft_types()
        assert len(types) == 1
        assert types[0]["code"] == "T100"
        assert types[0]["name"] == "测试机型"

    def test_add_label(self, db_with_data):
        """测试添加标注"""
        db = db_with_data

        label_data = {
            "file_name": "A320-0001.jpg",
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

        result = db.add_label(label_data)
        assert result["id"] is not None
        assert result["file_name"] == "A320-0001.jpg"

    def test_get_next_sequence(self, db_with_data):
        """测试获取序号"""
        db = db_with_data

        # 第一个应该是1
        seq1 = db.get_next_sequence("A320")
        assert seq1 == 1

        # 添加一个标注后，序号应该是2
        db.add_label(
            {
                "file_name": "A320-0001.jpg",
                "original_file_name": "test1.jpg",
                "type_id": "A320",
                "type_name": "空客A320",
                "airline_id": "CCA",
                "airline_name": "中国国航",
                "clarity": 0.9,
                "block": 0.1,
                "registration": "B-1234",
                "registration_area": "0.5 0.5 0.2 0.1",
            }
        )

        seq2 = db.get_next_sequence("A320")
        assert seq2 == 2

    def test_acquire_lock(self, db_with_data):
        """测试获取锁"""
        db = db_with_data

        # 第一次获取锁应该成功
        success = db.acquire_lock("test.jpg", "user1")
        assert success is True

        # 第二次获取同一文件的锁应该失败
        success = db.acquire_lock("test.jpg", "user2")
        assert success is False

        # 同一用户再次获取应该成功（更新时间）
        success = db.acquire_lock("test.jpg", "user1")
        assert success is True

    def test_release_lock(self, db_with_data):
        """测试释放锁"""
        db = db_with_data

        # 获取锁
        db.acquire_lock("test.jpg", "user1")

        # 释放锁
        success = db.release_lock("test.jpg", "user1")
        assert success is True

        # 释放后应该能重新获取
        success = db.acquire_lock("test.jpg", "user2")
        assert success is True

    def test_skip_image(self, db_with_data):
        """测试跳过图片"""
        db = db_with_data

        # 跳过图片
        success = db.skip_image("test.jpg")
        assert success is True

        # 检查是否在跳过列表中
        skipped = db.get_skipped_filenames()
        assert "test.jpg" in skipped

    def test_add_ai_prediction(self, db_with_data):
        """测试添加AI预测"""
        db = db_with_data

        prediction_data = {
            "filename": "test.jpg",
            "aircraft_class": "A320",
            "aircraft_confidence": 0.95,
            "airline_class": "CCA",
            "airline_confidence": 0.93,
            "registration": "B-1234",
            "registration_area": "0.5 0.5 0.2 0.1",
            "registration_confidence": 0.9,
            "clarity": 0.85,
            "block": 0.15,
            "quality_confidence": 0.9,
            "is_new_class": 0,
            "outlier_score": 0.1,
            "prediction_time": 1.5,
        }

        result = db.add_ai_prediction(prediction_data)
        assert result["id"] is not None

        # 检查数据是否正确插入
        prediction = db.get_ai_prediction("test.jpg")
        assert prediction is not None
        assert prediction["aircraft_class"] == "A320"
        assert prediction["aircraft_confidence"] == 0.95

    def test_get_unprocessed_predictions(self, db_with_data):
        """测试获取未处理的预测"""
        db = db_with_data

        # 添加多个预测
        for i in range(3):
            prediction_data = {
                "filename": f"test{i}.jpg",
                "aircraft_class": "A320",
                "aircraft_confidence": 0.95 - i * 0.1,
                "airline_class": "CCA",
                "airline_confidence": 0.93 - i * 0.1,
                "registration": f"B-{i}234",
                "registration_area": "0.5 0.5 0.2 0.1",
                "registration_confidence": 0.9,
                "clarity": 0.85,
                "block": 0.15,
                "quality_confidence": 0.9,
                "is_new_class": 1 if i == 0 else 0,
                "outlier_score": 0.5 if i == 0 else 0.1,
                "prediction_time": 1.5,
            }
            db.add_ai_prediction(prediction_data)

        # 获取未处理的预测
        predictions = db.get_unprocessed_predictions()
        assert len(predictions) == 3

        # 检查排序：新类别在前
        assert predictions[0]["is_new_class"] == 1

        # 标记一个为已处理
        db.mark_prediction_processed("test0.jpg")

        # 再次获取应该少一个
        predictions = db.get_unprocessed_predictions()
        assert len(predictions) == 2

    def test_update_label_with_ai_data(self, db_with_data):
        """测试更新标注的AI数据"""
        db = db_with_data

        # 先添加标注
        label_data = {
            "file_name": "A320-0001.jpg",
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
        result = db.add_label(label_data)

        # 更新AI数据
        ai_data = {"review_status": "approved", "ai_approved": 1}
        success = db.update_label_with_ai_data(result["id"], ai_data)
        assert success is True

        # 检查更新结果
        label = db.get_label_by_id(result["id"])
        assert label["review_status"] == "approved"
        assert label["ai_approved"] == 1

    def test_get_stats(self, db_with_data):
        """测试获取统计信息"""
        db = db_with_data

        # 添加一些标注
        for i in range(3):
            label_data = {
                "file_name": f"A320-{i + 1:04d}.jpg",
                "original_file_name": f"test{i}.jpg",
                "type_id": "A320" if i < 2 else "B738",
                "type_name": "空客A320" if i < 2 else "波音737-800",
                "airline_id": "CCA" if i < 2 else "CSN",
                "airline_name": "中国国航" if i < 2 else "中国南方航空",
                "clarity": 0.9,
                "block": 0.1,
                "registration": f"B-{i}234",
                "registration_area": "0.5 0.5 0.2 0.1",
            }
            db.add_label(label_data)

        # 获取统计
        stats = db.get_stats()
        assert stats["total_labeled"] == 3
        assert "A320" in stats["by_type"]
        assert "B738" in stats["by_type"]
        assert stats["by_type"]["A320"] == 2
        assert stats["by_type"]["B738"] == 1

    def test_bulk_mark_processed(self, db_with_data):
        """测试批量标记已处理"""
        db = db_with_data

        # 添加预测
        filenames = ["test0.jpg", "test1.jpg", "test2.jpg"]
        for filename in filenames:
            prediction_data = {
                "filename": filename,
                "aircraft_class": "A320",
                "aircraft_confidence": 0.95,
                "airline_class": "CCA",
                "airline_confidence": 0.93,
                "registration": "B-1234",
                "registration_area": "0.5 0.5 0.2 0.1",
                "registration_confidence": 0.9,
                "clarity": 0.85,
                "block": 0.15,
                "quality_confidence": 0.9,
                "is_new_class": 0,
                "outlier_score": 0.1,
                "prediction_time": 1.5,
            }
            db.add_ai_prediction(prediction_data)

        # 批量标记
        count = db.bulk_mark_processed(filenames)
        assert count == 3

        # 检查是否都已标记
        predictions = db.get_unprocessed_predictions()
        assert len(predictions) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
