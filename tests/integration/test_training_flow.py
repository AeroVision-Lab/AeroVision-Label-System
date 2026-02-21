"""
训练流程集成测试

测试完整的AI预测-人工标注-模型训练/评估循环：

1. 新图片上传 -> AI预测
2. 人工标注 -> 数据库保存
3. 定时触发训练 -> 数据集准备
4. 训练执行 -> 模型评估
5. 模型版本管理

注意：这些测试需要真实的GPU和训练环境，可能耗时较长
"""

import os
import pytest
import tempfile
import shutil
import time
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database import Database
from training_manager import TrainingManager
from scheduler import TrainingScheduler


class TestTrainingFlowIntegration:
    """训练流程集成测试"""

    @pytest.fixture
    def integration_env(self):
        """
        创建集成测试环境（每个测试独立）
        """
        # 创建临时根目录
        temp_root = tempfile.mkdtemp(prefix="training_integration_")

        # 创建目录结构
        aero_v1_path = Path(temp_root) / "AeroVision-V1"
        labeled_dir = Path(temp_root) / "labeled"
        images_dir = Path(temp_root) / "images"
        temp_dir = Path(temp_root) / "temp_training"
        models_dir = Path(temp_root) / "models"

        for d in [aero_v1_path, labeled_dir, images_dir, temp_dir, models_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 创建临时数据库（使用temp_root确保唯一性）
        fd, db_path = tempfile.mkstemp(suffix=".db", dir=temp_root)
        os.close(fd)

        db = Database(db_path)

        # 添加测试数据
        db.add_airline("CCA", "中国国航")
        db.add_airline("CSN", "中国南方航空")
        db.add_aircraft_type("A320", "空客A320")
        db.add_aircraft_type("B738", "波音737-800")

        # 创建测试图片（使用PIL生成）
        try:
            from PIL import Image
            import numpy as np

            # 为每个机型创建几张测试图片
            test_images = []
            for i in range(5):
                # A320 图片
                img_name = f"test_a320_{i}.jpg"
                img_path = labeled_dir / img_name
                img = Image.fromarray(np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8))
                img.save(img_path)

                # 添加标注
                db.add_label({
                    "file_name": f"A320-{i:04d}.jpg",
                    "original_file_name": img_name,
                    "type_id": "A320",
                    "type_name": "空客A320",
                    "airline_id": "CCA",
                    "airline_name": "中国国航",
                    "clarity": 0.9,
                    "block": 0.1,
                    "registration": f"B-100{i}",
                    "registration_area": "0.5 0.5 0.3 0.2"
                })

                # B738 图片
                img_name = f"test_b738_{i}.jpg"
                img_path = labeled_dir / img_name
                img = Image.fromarray(np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8))
                img.save(img_path)

                # 添加标注
                db.add_label({
                    "file_name": f"B738-{i:04d}.jpg",
                    "original_file_name": img_name,
                    "type_id": "B738",
                    "type_name": "波音737-800",
                    "airline_id": "CSN",
                    "airline_name": "中国南方航空",
                    "clarity": 0.85,
                    "block": 0.15,
                    "registration": f"B-200{i}",
                    "registration_area": "0.5 0.5 0.35 0.25"
                })

        except ImportError:
            pytest.skip("PIL not available for creating test images")

        # 模拟AeroVision-V1的训练脚本
        training_scripts_dir = aero_v1_path / "training" / "scripts"
        training_scripts_dir.mkdir(parents=True, exist_ok=True)

        # 创建虚拟的训练脚本（只是成功返回，不实际训练）
        train_script = training_scripts_dir / "train_classify.py"
        train_script.write_text("""#!/usr/bin/env python3
import sys
import json
from pathlib import Path
import time

# 简单的虚拟训练脚本
data_path = sys.argv[sys.argv.index('--data') + 1]
output_dir = sys.argv[sys.argv.index('--project') + 1]

# 模拟训练过程，保持running状态足够长
time.sleep(2.0)  # 睡眠2秒，确保测试能够捕捉到running状态

# 创建输出目录
output_path = Path(output_dir) / "train" / "weights"
output_path.mkdir(parents=True, exist_ok=True)

# 创建虚拟模型文件
model_path = output_path / "best.pt"
model_path.write_text("dummy model")

print(json.dumps({"status": "success", "model": str(model_path)}))
""")

        train_script.chmod(0o755)

        # 创建虚拟的评估脚本
        eval_script = training_scripts_dir / "evaluate_classify.py"
        eval_script.write_text("""#!/usr/bin/env python3
import sys
import json

# 简单的虚拟评估脚本
print(json.dumps({
    "accuracy": 0.95,
    "macro_recall": 0.93,
    "ece": 0.05,
    "total_samples": 10,
    "num_classes": 2,
    "per_class_accuracy": [0.9, 1.0],
    "recall_per_class": [0.9, 0.95],
    "confusion_matrix": [[5, 0], [1, 4]],
    "confidence_mean": 0.9,
    "confidence_std": 0.1
}))
""")

        eval_script.chmod(0o755)

        yield {
            "db": db,
            "db_path": db_path,
            "aero_v1_path": str(aero_v1_path),
            "labeled_dir": str(labeled_dir),
            "temp_dir": str(temp_dir),
            "models_dir": str(models_dir),
            "temp_root": temp_root
        }

        # 清理
        shutil.rmtree(temp_root, ignore_errors=True)

    def test_full_training_flow(self, integration_env):
        """
        测试完整的训练流程

        流程：
        1. 创建训练管理器
        2. 触发训练
        3. 等待训练完成
        4. 检查训练结果
        5. 检查模型版本
        6. 检查临时文件清理
        """
        env = integration_env
        db = env["db"]

        # 创建训练管理器
        manager = TrainingManager(
            db=db,
            aero_v1_path=env["aero_v1_path"],
            labeled_dir=env["labeled_dir"],
            temp_dir=env["temp_dir"],
            models_dir=env["models_dir"]
        )

        manager.start()

        try:
            # 触发训练
            result = manager.trigger_training(task_type="aircraft", triggered_by="manual")

            assert result["status"] == "queued"
            job_id = result["job_id"]

            # 等待训练完成（最多60秒）
            timeout = 60
            start_time = time.time()

            while time.time() - start_time < timeout:
                job = db.get_training_job(job_id)

                if job["status"] in ["completed", "failed"]:
                    break

                time.sleep(1.0)

            # 检查训练状态
            job = db.get_training_job(job_id)
            assert job["status"] == "completed", f"Training failed: {job.get('error_message')}"

            # 检查训练结果
            result = db.get_training_result(job_id)
            assert result is not None
            assert "accuracy" in result
            assert "macro_recall" in result

            # 检查模型版本
            versions = db.get_model_versions(model_type="aircraft")
            assert len(versions) > 0

            # 检查模型文件是否存在
            model_version = versions[0]
            model_path = Path(model_version["file_path"])
            assert model_path.exists()

            # 检查临时文件是否已清理
            dataset_dir = Path(env["temp_dir"]) / f"dataset_{job_id}"
            training_dir = Path(env["temp_dir"]) / f"training_{job_id}"
            eval_dir = Path(env["temp_dir"]) / f"eval_{job_id}"

            assert not dataset_dir.exists()
            assert not training_dir.exists()
            assert not eval_dir.exists()

        finally:
            manager.stop()

    def test_training_with_running_job(self, integration_env):
        """测试在有正在运行的任务时触发训练"""
        env = integration_env
        db = env["db"]

        # 创建训练管理器
        manager = TrainingManager(
            db=db,
            aero_v1_path=env["aero_v1_path"],
            labeled_dir=env["labeled_dir"],
            temp_dir=env["temp_dir"],
            models_dir=env["models_dir"]
        )

        manager.start()

        try:
            # 触发第一个训练
            result1 = manager.trigger_training(task_type="aircraft", triggered_by="manual")
            assert result1["status"] == "queued"
            job_id1 = result1["job_id"]

            # 等待任务进入running状态（虚拟脚本现在有2秒sleep）
            timeout = 5
            start_time = time.time()
            while time.time() - start_time < timeout:
                job = db.get_training_job(job_id1)
                if job["status"] == "running":
                    break
                time.sleep(0.1)
            else:
                pytest.fail("First training job did not enter running state within timeout")

            # 现在任务应该还在running状态，尝试触发第二个训练（应该被跳过）
            result2 = manager.trigger_training(task_type="aircraft", triggered_by="manual")
            assert result2["status"] == "skipped"
            assert "already running" in result2["reason"]

            # 等待第一个训练完成
            timeout = 60
            start_time = time.time()

            while time.time() - start_time < timeout:
                job = db.get_training_job(job_id1)
                if job["status"] in ["completed", "failed"]:
                    break
                time.sleep(1.0)

        finally:
            manager.stop()

    def test_scheduler_integration(self, integration_env):
        """测试调度器集成"""
        env = integration_env
        db = env["db"]

        # 创建训练管理器
        manager = TrainingManager(
            db=db,
            aero_v1_path=env["aero_v1_path"],
            labeled_dir=env["labeled_dir"],
            temp_dir=env["temp_dir"],
            models_dir=env["models_dir"]
        )

        manager.start()

        # 创建调度器（设置调度时间为当前时间）
        scheduler = TrainingScheduler(
            training_manager=manager,
            db=db,
            schedule_hour=time.localtime().tm_hour
        )
        scheduler.start()

        try:
            # 等待调度器触发训练（最多60秒）
            timeout = 60
            start_time = time.time()

            job_id = None
            while time.time() - start_time < timeout:
                # 获取最新的训练任务
                latest_job = db.get_latest_training_job()
                if latest_job and latest_job["status"] != "pending":
                    job_id = latest_job["id"]
                    break

                # 手动触发检查（模拟调度时间）
                scheduler._check_and_trigger_training()
                time.sleep(1.0)

            # 检查是否触发了训练
            assert job_id is not None, "Scheduler did not trigger training"

            # 等待训练完成
            timeout = 60
            start_time = time.time()

            while time.time() - start_time < timeout:
                job = db.get_training_job(job_id)
                if job["status"] in ["completed", "failed"]:
                    break
                time.sleep(1.0)

            job = db.get_training_job(job_id)
            assert job["status"] == "completed"
            assert job["triggered_by"] == "scheduler"

        finally:
            scheduler.stop()
            manager.stop()

    def test_memory_limit_handling(self, integration_env):
        """测试内存限制处理"""
        env = integration_env
        db = env["db"]

        # 创建训练管理器
        manager = TrainingManager(
            db=db,
            aero_v1_path=env["aero_v1_path"],
            labeled_dir=env["labeled_dir"],
            temp_dir=env["temp_dir"],
            models_dir=env["models_dir"]
        )

        # 使用patch全局替换ResourceManager.check_resources
        from training_manager import ResourceManager

        with patch.object(ResourceManager, 'check_resources', return_value=(False, {
            "vram_ok": False,
            "vram_gb": 5.0,
            "ram_ok": True,
            "ram_gb": 16.0,
            "min_vram_gb": 10.0,
            "min_ram_gb": 4.0
        })):
            manager.start()

            try:
                # 触发训练（应该因为资源不足而失败）
                result = manager.trigger_training(task_type="aircraft", triggered_by="manual")

                if result["status"] == "queued":
                    job_id = result["job_id"]

                    # 等待任务完成
                    timeout = 30
                    start_time = time.time()

                    while time.time() - start_time < timeout:
                        job = db.get_training_job(job_id)
                        if job["status"] in ["completed", "failed"]:
                            break
                        time.sleep(1.0)

                    job = db.get_training_job(job_id)
                    assert job["status"] == "failed", f"Expected failed, got {job['status']}"
                    assert "Insufficient resources" in job["error_message"], f"Error message: {job.get('error_message')}"
                elif result["status"] == "failed":
                    # 任务在创建时就因为资源检查而失败
                    # 这种情况不应该发生，因为资源检查是在队列执行时进行的
                    pass

            finally:
                manager.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--timeout=120"])
