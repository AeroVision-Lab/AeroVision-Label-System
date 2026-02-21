"""
训练管理器单元测试

测试内容：
1. 资源检查（显存和内存）
2. 队列管理（添加任务、获取任务、完成任务）
3. 并发控制（多个任务同时添加）
4. 错误处理（无效任务、队列满等）
"""

import os
import pytest
import tempfile
import shutil
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training_manager import TrainingManager, TrainingQueue, ResourceManager
from database import Database


class TestResourceManager:
    """资源管理器测试"""

    def test_check_gpu_memory_with_mock(self):
        """测试GPU显存检查（使用mock）"""
        with patch('training_manager.GPUtil') as mock_gpu:
            # 创建模拟GPU
            mock_gpu_obj = Mock()
            mock_gpu_obj.id = 0
            mock_gpu_obj.memoryFree = 12 * 1024  # 12GB

            mock_gpu.getGPUs.return_value = [mock_gpu_obj]

            # 测试足够的显存
            enough, vram = ResourceManager.check_gpu_memory(min_vram_gb=10.0)
            assert enough is True
            assert vram == 12.0

            # 测试不足的显存
            enough, vram = ResourceManager.check_gpu_memory(min_vram_gb=15.0)
            assert enough is False
            assert vram == 12.0

    def test_check_gpu_memory_no_gpu(self):
        """测试没有GPU的情况"""
        with patch('training_manager.GPUtil') as mock_gpu:
            mock_gpu.getGPUs.return_value = []

            enough, vram = ResourceManager.check_gpu_memory()
            assert enough is False
            assert vram == 0.0

    def test_check_gpu_memory_exception(self):
        """测试GPU检查异常"""
        with patch('training_manager.GPUtil') as mock_gpu:
            mock_gpu.getGPUs.side_effect = Exception("GPU error")

            enough, vram = ResourceManager.check_gpu_memory()
            assert enough is False
            assert vram == 0.0

    def test_check_system_memory(self):
        """测试系统内存检查"""
        try:
            enough, ram = ResourceManager.check_system_memory(min_ram_gb=1.0)
            # 只要不抛异常即可
            assert isinstance(enough, bool)
            assert isinstance(ram, float)
        except ImportError:
            pytest.skip("psutil not available")


class TestTrainingQueue:
    """训练队列测试"""

    def test_add_and_get_job(self):
        """测试添加和获取任务"""
        queue = TrainingQueue(max_size=5)

        # 添加任务
        job_id = queue.add_job("training", {"test": "data"})

        # 获取任务
        job = queue.get_next_job()

        assert job["id"] == job_id
        assert job["type"] == "training"
        assert job["status"] == "running"

    def test_queue_full(self):
        """测试队列满的情况"""
        queue = TrainingQueue(max_size=2)

        # 添加两个任务
        queue.add_job("training", {"test": "1"})
        queue.add_job("training", {"test": "2"})

        # 第三个任务应该失败
        with pytest.raises(RuntimeError, match="Queue is full"):
            queue.add_job("training", {"test": "3"})

    def test_complete_job(self):
        """测试完成任务"""
        queue = TrainingQueue(max_size=5)

        job_id = queue.add_job("training", {"test": "data"})

        # 完成任务
        queue.complete_job(job_id, success=True)

        # 检查队列状态
        status = queue.get_queue_status()
        assert status["completed"] == 1
        assert status["failed"] == 0

    def test_complete_job_with_error(self):
        """测试任务失败"""
        queue = TrainingQueue(max_size=5)

        job_id = queue.add_job("training", {"test": "data"})

        # 完成任务（失败）
        queue.complete_job(job_id, success=False, error="Test error")

        # 检查队列状态
        status = queue.get_queue_status()
        assert status["completed"] == 0
        assert status["failed"] == 1

    def test_get_current_job(self):
        """测试获取当前运行的任务"""
        queue = TrainingQueue(max_size=5)

        # 添加任务
        job_id = queue.add_job("training", {"test": "data"})

        # 获取当前任务（会将其设为running）
        job = queue.get_next_job()

        # 检查当前任务
        current = queue.get_current_job()
        assert current is not None
        assert current["id"] == job_id
        assert current["status"] == "running"

    def test_concurrent_add_jobs(self):
        """测试并发添加任务"""
        queue = TrainingQueue(max_size=100)

        job_ids = []
        threads = []

        def add_job(index):
            try:
                job_id = queue.add_job("training", {"index": index})
                job_ids.append((index, job_id))
            except RuntimeError:
                pass

        # 创建10个线程同时添加任务
        for i in range(10):
            thread = threading.Thread(target=add_job, args=(i,))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join(timeout=5.0)

        # 验证所有任务都成功添加
        assert len(job_ids) == 10

        # 验证任务ID是唯一的
        job_id_values = [job_id for _, job_id in job_ids]
        assert len(set(job_id_values)) == 10

    def test_get_queue_status(self):
        """测试获取队列状态"""
        queue = TrainingQueue(max_size=10)

        # 添加任务
        queue.add_job("training", {"test": "1"})
        queue.add_job("inference", {"test": "2"})
        queue.add_job("training", {"test": "3"})

        # 获取状态
        status = queue.get_queue_status()

        assert status["queue_length"] == 3
        assert status["queued"] == 3
        assert status["running"] == 0
        assert status["completed"] == 0
        assert status["failed"] == 0


class TestTrainingManager:
    """训练管理器测试"""

    @pytest.fixture
    def temp_dirs(self):
        """创建临时目录"""
        temp_root = tempfile.mkdtemp()
        aero_v1_path = Path(temp_root) / "AeroVision-V1"
        labeled_dir = Path(temp_root) / "labeled"
        temp_dir = Path(temp_root) / "temp"
        models_dir = Path(temp_root) / "models"

        aero_v1_path.mkdir()
        labeled_dir.mkdir()
        temp_dir.mkdir()
        models_dir.mkdir()

        yield {
            "aero_v1_path": str(aero_v1_path),
            "labeled_dir": str(labeled_dir),
            "temp_dir": str(temp_dir),
            "models_dir": str(models_dir),
            "temp_root": temp_root
        }

        # 清理
        shutil.rmtree(temp_root, ignore_errors=True)

    @pytest.fixture
    def temp_db(self):
        """创建临时数据库"""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        db = Database(db_path)

        # 添加测试数据
        db.add_airline("CCA", "中国国航")
        db.add_aircraft_type("A320", "空客A320")

        yield db, db_path

        # 清理
        os.unlink(db_path)

    def test_init_training_manager(self, temp_dirs, temp_db):
        """测试初始化训练管理器"""
        db, _ = temp_db

        manager = TrainingManager(
            db=db,
            aero_v1_path=temp_dirs["aero_v1_path"],
            labeled_dir=temp_dirs["labeled_dir"],
            temp_dir=temp_dirs["temp_dir"],
            models_dir=temp_dirs["models_dir"]
        )

        assert manager.db is db
        assert manager.aero_v1_path == Path(temp_dirs["aero_v1_path"])
        assert manager.labeled_dir == Path(temp_dirs["labeled_dir"])
        assert manager.temp_dir == Path(temp_dirs["temp_dir"])
        assert manager.models_dir == Path(temp_dirs["models_dir"])

    def test_check_resources(self, temp_dirs, temp_db):
        """测试资源检查"""
        db, _ = temp_db

        manager = TrainingManager(
            db=db,
            aero_v1_path=temp_dirs["aero_v1_path"],
            labeled_dir=temp_dirs["labeled_dir"],
            temp_dir=temp_dirs["temp_dir"],
            models_dir=temp_dirs["models_dir"]
        )

        # 测试资源检查
        resources_ok, info = manager.check_resources()

        assert isinstance(resources_ok, bool)
        assert isinstance(info, dict)
        assert "vram_ok" in info
        assert "ram_ok" in info

    def test_get_queue_status(self, temp_dirs, temp_db):
        """测试获取队列状态"""
        db, _ = temp_db

        manager = TrainingManager(
            db=db,
            aero_v1_path=temp_dirs["aero_v1_path"],
            labeled_dir=temp_dirs["labeled_dir"],
            temp_dir=temp_dirs["temp_dir"],
            models_dir=temp_dirs["models_dir"]
        )

        # 获取队列状态
        status = manager.get_queue_status()

        assert "queue_length" in status
        assert "queued" in status
        assert "running" in status

    @pytest.mark.skipif(os.getenv('GITHUB_ACTIONS') == 'true', reason="Skip on GitHub Actions")
    def test_trigger_training_insufficient_labels(self, temp_dirs, temp_db):
        """测试触发训练（标注不足）"""
        db, _ = temp_db

        manager = TrainingManager(
            db=db,
            aero_v1_path=temp_dirs["aero_v1_path"],
            labeled_dir=temp_dirs["labeled_dir"],
            temp_dir=temp_dirs["temp_dir"],
            models_dir=temp_dirs["models_dir"]
        )

        # 触发训练（标注不足）
        result = manager.trigger_training(task_type="aircraft", triggered_by="manual")

        assert result["status"] == "skipped"
        assert "Insufficient labels" in result["reason"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
