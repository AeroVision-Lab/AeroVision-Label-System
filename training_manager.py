"""
训练管理器
负责管理训练任务的生命周期，包括资源检查、队列管理、训练执行和评估
"""

import os
import sys
import json
import shutil
import logging
import subprocess
import threading
import time
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List
import traceback

import torch
import GPUtil

from database import Database


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TrainingQueue:
    """训练/推理队列管理器"""

    def __init__(self, max_size: int = 10):
        """
        初始化队列

        Args:
            max_size: 队列最大长度
        """
        self.queue = []
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.max_size = max_size
        self._current_job: Optional[Dict] = None

    def add_job(self, job_type: str, job_data: dict) -> int:
        """
        添加任务到队列

        Args:
            job_type: 任务类型 ('training', 'inference')
            job_data: 任务数据

        Returns:
            队列位置
        """
        with self.lock:
            if len(self.queue) >= self.max_size:
                raise RuntimeError(f"Queue is full (max_size={self.max_size})")

            job_id = len(self.queue)
            self.queue.append({
                "id": job_id,
                "type": job_type,
                "data": job_data,
                "status": "queued",
                "created_at": time.time()
            })

            logger.info(f"Added {job_type} job #{job_id} to queue")
            self.condition.notify_all()

            return job_id

    def get_next_job(self) -> Optional[Dict]:
        """获取下一个待处理的任务"""
        with self.condition:
            while True:
                # 查找等待中的任务
                for job in self.queue:
                    if job["status"] == "queued":
                        job["status"] = "running"
                        self._current_job = job
                        logger.info(f"Starting {job['type']} job #{job['id']}")
                        return job

                # 没有待处理任务，等待
                self.condition.wait(timeout=1.0)

    def complete_job(self, job_id: int, success: bool, error: str = None):
        """标记任务完成"""
        with self.lock:
            for job in self.queue:
                if job["id"] == job_id:
                    job["status"] = "completed" if success else "failed"
                    job["error"] = error
                    job["completed_at"] = time.time()

                    if self._current_job and self._current_job["id"] == job_id:
                        self._current_job = None

                    logger.info(f"Completed {job['type']} job #{job_id} (success={success})")
                    self.condition.notify_all()
                    return

    def get_current_job(self) -> Optional[Dict]:
        """获取当前正在运行的任务"""
        with self.lock:
            return self._current_job

    def get_queue_status(self) -> Dict:
        """获取队列状态"""
        with self.lock:
            return {
                "queue_length": len(self.queue),
                "queued": len([j for j in self.queue if j["status"] == "queued"]),
                "running": len([j for j in self.queue if j["status"] == "running"]),
                "completed": len([j for j in self.queue if j["status"] == "completed"]),
                "failed": len([j for j in self.queue if j["status"] == "failed"]),
                "current_job": self._current_job
            }


class ResourceManager:
    """资源管理器 - 检查显存和内存"""

    @staticmethod
    def check_gpu_memory(min_vram_gb: float = 10.0) -> tuple[bool, float]:
        """
        检查GPU显存是否足够

        Args:
            min_vram_gb: 最小显存需求（GB）

        Returns:
            (是否足够, 可用显存GB)
        """
        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                logger.warning("No GPU detected")
                return False, 0.0

            # 查找可用显存最多的GPU
            gpu = max(gpus, key=lambda g: g.memoryFree)

            # 转换为GB
            free_vram_gb = gpu.memoryFree / 1024.0

            is_enough = free_vram_gb >= min_vram_gb

            logger.info(f"GPU #{gpu.id}: {free_vram_gb:.2f} GB free "
                       f"(required: {min_vram_gb:.2f} GB) - {'OK' if is_enough else 'NOT ENOUGH'}")

            return is_enough, free_vram_gb

        except Exception as e:
            logger.error(f"Failed to check GPU memory: {e}")
            return False, 0.0

    @staticmethod
    def check_system_memory(min_ram_gb: float = 4.0) -> tuple[bool, float]:
        """
        检查系统内存是否足够

        Args:
            min_ram_gb: 最小内存需求（GB）

        Returns:
            (是否足够, 可用内存GB)
        """
        try:
            import psutil
            mem = psutil.virtual_memory()

            free_ram_gb = mem.available / (1024**3)
            is_enough = free_ram_gb >= min_ram_gb

            logger.info(f"System RAM: {free_ram_gb:.2f} GB free "
                       f"(required: {min_ram_gb:.2f} GB) - {'OK' if is_enough else 'NOT ENOUGH'}")

            return is_enough, free_ram_gb

        except ImportError:
            logger.warning("psutil not available, skipping RAM check")
            return True, 0.0
        except Exception as e:
            logger.error(f"Failed to check system memory: {e}")
            return False, 0.0

    @staticmethod
    def check_resources(min_vram_gb: float = 10.0, min_ram_gb: float = 4.0) -> tuple[bool, Dict]:
        """
        检查所有资源

        Args:
            min_vram_gb: 最小显存需求（GB）
            min_ram_gb: 最小内存需求（GB）

        Returns:
            (是否足够, 资源信息字典)
        """
        vram_ok, vram_gb = ResourceManager.check_gpu_memory(min_vram_gb)
        ram_ok, ram_gb = ResourceManager.check_system_memory(min_ram_gb)

        all_ok = vram_ok and ram_ok

        return all_ok, {
            "vram_ok": vram_ok,
            "vram_gb": vram_gb,
            "ram_ok": ram_ok,
            "ram_gb": ram_gb,
            "min_vram_gb": min_vram_gb,
            "min_ram_gb": min_ram_gb
        }


class TrainingManager:
    """训练管理器 - 管理训练任务的完整生命周期"""

    def __init__(
        self,
        db: Database,
        aero_v1_path: str,
        labeled_dir: str,
        temp_dir: str,
        models_dir: str
    ):
        """
        初始化训练管理器

        Args:
            db: 数据库实例
            aero_v1_path: AeroVision-V1项目路径
            labeled_dir: 已标注图片目录
            temp_dir: 临时文件目录
            models_dir: 模型存储目录
        """
        self.db = db
        self.aero_v1_path = Path(aero_v1_path)
        self.labeled_dir = Path(labeled_dir)
        self.temp_dir = Path(temp_dir)
        self.models_dir = Path(models_dir)

        # 确保目录存在
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)

        # 队列
        self.queue = TrainingQueue()

        # 工作线程
        self._worker_thread: Optional[threading.Thread] = None
        self._should_stop = False

        logger.info("TrainingManager initialized")

    def start(self):
        """启动工作线程"""
        if self._worker_thread and self._worker_thread.is_alive():
            logger.warning("Worker thread already running")
            return

        self._should_stop = False
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

        logger.info("Training manager worker thread started")

    def stop(self):
        """停止工作线程"""
        self._should_stop = True
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
        logger.info("Training manager worker thread stopped")

    def _worker_loop(self):
        """工作线程主循环"""
        logger.info("Worker loop started")

        while not self._should_stop:
            try:
                # 获取下一个任务
                job = self.queue.get_next_job()
                if not job:
                    time.sleep(0.1)
                    continue

                # 执行任务
                if job["type"] == "training":
                    self._execute_training_job(job)
                else:
                    logger.warning(f"Unknown job type: {job['type']}")

            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                logger.error(traceback.format_exc())
                time.sleep(1.0)

        logger.info("Worker loop stopped")

    def _execute_training_job(self, job: Dict):
        """执行训练任务"""
        job_id = job["data"].get("job_id")
        task_type = job["data"].get("task_type", "aircraft")

        logger.info(f"Executing training job #{job_id} for {task_type}")

        try:
            # 获取训练任务信息
            training_job = self.db.get_training_job(job_id)
            if not training_job:
                raise RuntimeError(f"Training job #{job_id} not found")

            # 检查资源
            resources_ok, resource_info = ResourceManager.check_resources(
                min_vram_gb=10.0,
                min_ram_gb=4.0
            )

            if not resources_ok:
                error_msg = f"Insufficient resources: VRAM={resource_info['vram_gb']:.2f}GB, RAM={resource_info['ram_gb']:.2f}GB"
                logger.error(error_msg)
                self.queue.complete_job(job_id, False, error_msg)
                self.db.update_training_job_status(job_id, "failed", error_message=error_msg)
                return

            # 更新状态为运行中
            self.db.update_training_job_status(job_id, "running")

            # 准备数据集
            dataset_info = self._prepare_dataset(job_id, task_type, training_job.get("dataset_info"))

            # 执行训练
            model_path = self._run_training(job_id, task_type, dataset_info)

            # 执行评估
            eval_results = self._run_evaluation(job_id, task_type, model_path, dataset_info)

            # 保存模型版本
            version_name = datetime.now().strftime("v%Y%m%d_%H%M%S")
            self.db.create_model_version(
                model_type=task_type,
                version_name=version_name,
                file_path=model_path,
                training_job_id=job_id
            )

            # 保存训练结果
            self.db.create_training_result(job_id, eval_results)

            # 更新状态为完成
            self.db.update_training_job_status(
                job_id,
                "completed",
                progress=100.0,
                error_message=None
            )

            # 清理临时文件
            self._cleanup_temp_files(job_id)

            self.queue.complete_job(job_id, True)
            logger.info(f"Training job #{job_id} completed successfully")

        except Exception as e:
            error_msg = f"Training failed: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())

            self.queue.complete_job(job_id, False, error_msg)
            self.db.update_training_job_status(job_id, "failed", error_message=error_msg)

            # 清理临时文件
            self._cleanup_temp_files(job_id)

    def _prepare_dataset(self, job_id: int, task_type: str, dataset_info: Dict = None) -> Dict:
        """
        准备训练数据集

        从数据库读取标注数据，组织成YOLO训练所需的目录结构
        """
        logger.info(f"Preparing dataset for {task_type} training job #{job_id}")

        # 创建临时数据集目录
        temp_dataset_dir = self.temp_dir / f"dataset_{job_id}"
        temp_dataset_dir.mkdir(parents=True, exist_ok=True)

        # 获取标注数据
        labels_data = self.db.get_labels_for_training(min_samples_per_class=1)

        logger.info(f"Found {len(labels_data)} aircraft types with labels")

        # 按机型组织数据
        for type_info in labels_data:
            type_id = type_info["type_id"]
            type_dir = temp_dataset_dir / type_id
            type_dir.mkdir(exist_ok=True)

            # 获取该机型的所有标注
            # 这里需要查询数据库获取文件列表
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_name FROM labels WHERE type_id = ?",
                (type_id,)
            )
            rows = cursor.fetchall()
            conn.close()

            # 复制图片到临时目录
            for row in rows:
                src_path = self.labeled_dir / row["file_name"]
                if src_path.exists():
                    shutil.copy2(src_path, type_dir / row["file_name"])

        # 统计信息
        total_images = sum(
            len(list(temp_dataset_dir.glob(f"{t['type_id']}/*")))
            for t in labels_data
        )

        dataset_info = {
            "dataset_dir": str(temp_dataset_dir),
            "num_classes": len(labels_data),
            "total_images": total_images,
            "classes": [t["type_id"] for t in labels_data]
        }

        logger.info(f"Dataset prepared: {dataset_info}")
        return dataset_info

    def _run_training(self, job_id: int, task_type: str, dataset_info: Dict) -> str:
        """
        运行训练

        调用AeroVision-V1的训练脚本
        """
        logger.info(f"Starting training for {task_type} (job #{job_id})")

        # 确定训练脚本路径
        if task_type == "aircraft":
            train_script = self.aero_v1_path / "training" / "scripts" / "train_classify.py"
        elif task_type == "airline":
            train_script = self.aero_v1_path / "training" / "scripts" / "train_airline.py"
        else:
            raise ValueError(f"Unsupported task type: {task_type}")

        if not train_script.exists():
            raise RuntimeError(f"Training script not found: {train_script}")

        # 创建输出目录
        output_dir = self.temp_dir / f"training_{job_id}"
        output_dir.mkdir(exist_ok=True)

        # 构建训练命令
        cmd = [
            sys.executable,
            str(train_script),
            "--data", dataset_info["dataset_dir"],
            "--epochs", "50",
            "--batch-size", "32",
            "--imgsz", "224",
            "--device", "0",
            "--project", str(output_dir),
            "--name", "train",
            "--exist-ok"
        ]

        logger.info(f"Running command: {' '.join(cmd)}")

        # 执行训练
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1小时超时
            )

            if result.returncode != 0:
                logger.error(f"Training failed with return code {result.returncode}")
                logger.error(f"STDOUT: {result.stdout}")
                logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError(f"Training script failed: {result.stderr}")

            # 查找训练好的模型
            model_path = None
            for name in ["best.pt", "last.pt"]:
                candidate = output_dir / "train" / "weights" / name
                if candidate.exists():
                    model_path = str(candidate)
                    logger.info(f"Found trained model: {model_path}")
                    break

            if not model_path:
                raise RuntimeError("No model file found after training")

            # 复制模型到模型目录
            version_name = datetime.now().strftime("v%Y%m%d_%H%M%S")
            dest_path = self.models_dir / f"{task_type}_{version_name}.pt"
            shutil.copy2(model_path, dest_path)

            logger.info(f"Model saved to: {dest_path}")
            return str(dest_path)

        except subprocess.TimeoutExpired:
            raise RuntimeError("Training timeout after 1 hour")

    def _run_evaluation(self, job_id: int, task_type: str, model_path: str, dataset_info: Dict) -> Dict:
        """
        运行评估

        调用AeroVision-V1的评估脚本
        """
        logger.info(f"Starting evaluation for {task_type} (job #{job_id})")

        # 确定评估脚本路径
        eval_script = self.aero_v1_path / "training" / "scripts" / "evaluate_classify.py"

        if not eval_script.exists():
            raise RuntimeError(f"Evaluation script not found: {eval_script}")

        # 构建评估命令
        cmd = [
            sys.executable,
            str(eval_script),
            "--model", model_path,
            "--data", dataset_info["dataset_dir"],
            "--device", "0",
            "--batch-size", "32",
            "--imgsz", "224",
            "--output-dir", str(self.temp_dir / f"eval_{job_id}")
        ]

        logger.info(f"Running command: {' '.join(cmd)}")

        # 执行评估
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10分钟超时
            )

            if result.returncode != 0:
                logger.warning(f"Evaluation failed with return code {result.returncode}")
                logger.warning(f"STDOUT: {result.stdout}")
                logger.warning(f"STDERR: {result.stderr}")
                # 评估失败不影响训练结果，返回空指标
                return {}

            # 解析评估结果（假设输出JSON）
            # 这里简化处理，实际应该从文件读取
            return {
                "accuracy": 0.0,
                "macro_recall": 0.0,
                "ece": 0.0,
                "total_samples": dataset_info["total_images"],
                "num_classes": dataset_info["num_classes"]
            }

        except subprocess.TimeoutExpired:
            logger.warning("Evaluation timeout after 10 minutes")
            return {}

    def _cleanup_temp_files(self, job_id: int):
        """清理临时文件"""
        logger.info(f"Cleaning up temp files for job #{job_id}")

        # 删除数据集目录
        dataset_dir = self.temp_dir / f"dataset_{job_id}"
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir)

        # 删除训练输出目录
        training_dir = self.temp_dir / f"training_{job_id}"
        if training_dir.exists():
            shutil.rmtree(training_dir)

        # 删除评估输出目录
        eval_dir = self.temp_dir / f"eval_{job_id}"
        if eval_dir.exists():
            shutil.rmtree(eval_dir)

        logger.info(f"Temp files cleaned up for job #{job_id}")

    def trigger_training(self, task_type: str, triggered_by: str = "scheduler") -> Dict:
        """
        触发训练任务

        Args:
            task_type: 任务类型 ('aircraft', 'airline')
            triggered_by: 触发者 ('scheduler', 'manual')

        Returns:
            任务信息字典
        """
        # 检查是否有正在运行的任务
        running_job = self.db.get_running_training_job()
        if running_job:
            return {
                "status": "skipped",
                "reason": f"Training job #{running_job['id']} is already running",
                "current_job": running_job
            }

        # 检查是否有新标注（简单检查：总标注数 > 上次训练的标注数）
        label_count = self.db.get_label_count_for_training()
        if label_count < 8:  # 最小样本数
            return {
                "status": "skipped",
                "reason": f"Insufficient labels: {label_count} (minimum: 8)"
            }

        # 创建训练任务
        job_id = self.db.create_training_job(
            task_type=task_type,
            triggered_by=triggered_by,
            config={
                "epochs": 50,
                "batch_size": 32,
                "imgsz": 224,
                "device": "0"
            },
            dataset_info={
                "label_count": label_count
            }
        )

        # 添加到队列
        try:
            queue_id = self.queue.add_job("training", {"job_id": job_id, "task_type": task_type})
        except RuntimeError as e:
            # 队列满，取消任务
            self.db.update_training_job_status(job_id, "cancelled", error_message=str(e))
            return {
                "status": "failed",
                "error": str(e)
            }

        return {
            "status": "queued",
            "job_id": job_id,
            "queue_id": queue_id,
            "task_type": task_type,
            "triggered_by": triggered_by
        }

    def get_queue_status(self) -> Dict:
        """获取队列状态"""
        return self.queue.get_queue_status()

    def check_resources(self) -> Dict:
        """检查资源状态"""
        return ResourceManager.check_resources()
