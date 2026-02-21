"""
定时任务调度器
负责定时触发训练任务（每天检查一次，有新图片则触发训练）
"""

import logging
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from typing import Optional

from training_manager import TrainingManager
from database import Database


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TrainingScheduler:
    """训练任务调度器"""

    def __init__(self, training_manager: TrainingManager, db: Database, schedule_hour: int = 2):
        """
        初始化调度器

        Args:
            training_manager: 训练管理器实例
            db: 数据库实例
            schedule_hour: 每天触发训练的小时数（默认凌晨2点）
        """
        self.training_manager = training_manager
        self.db = db
        self.schedule_hour = schedule_hour

        self._thread: Optional[threading.Thread] = None
        self._should_stop = False

        logger.info(f"TrainingScheduler initialized (schedule_hour={schedule_hour})")

    def start(self):
        """启动调度器"""
        if self._thread and self._thread.is_alive():
            logger.warning("Scheduler thread already running")
            return

        self._should_stop = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info("TrainingScheduler started")

    def stop(self):
        """停止调度器"""
        self._should_stop = True
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("TrainingScheduler stopped")

    def _run_loop(self):
        """调度器主循环"""
        logger.info("Scheduler loop started")

        last_check_date = None

        while not self._should_stop:
            try:
                now = datetime.now()
                current_date = now.date()
                current_hour = now.hour

                # 检查是否到达调度时间
                if (last_check_date is None or last_check_date != current_date) and current_hour == self.schedule_hour:
                    logger.info(f"Triggering scheduled training check at {now}")

                    # 检查是否有新标注
                    self._check_and_trigger_training()

                    last_check_date = current_date

                # 每分钟检查一次
                time.sleep(60)

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(60)

        logger.info("Scheduler loop stopped")

    def _check_and_trigger_training(self):
        """检查是否有新标注并触发训练"""
        try:
            # 获取最新训练任务
            latest_job = self.db.get_latest_training_job()

            # 获取当前标注数量
            label_count = self.db.get_label_count_for_training()

            if label_count < 8:
                logger.info(f"Insufficient labels for training: {label_count} (minimum: 8)")
                return

            # 检查是否需要训练
            should_train = False
            reason = ""

            if latest_job is None:
                # 首次训练
                should_train = True
                reason = "First training run"
            else:
                # 检查上次训练后的新增标注数
                # 简化：我们比较当前总数和上次训练时的总数
                last_label_count = latest_job.get("dataset_info", {}).get("label_count", 0)
                new_labels = label_count - last_label_count

                if new_labels > 0:
                    should_train = True
                    reason = f"New labels detected: {new_labels} (total: {label_count})"
                else:
                    logger.info(f"No new labels since last training (current: {label_count})")

            # 触发训练
            if should_train:
                logger.info(f"Triggering training: {reason}")

                # 触发机型分类训练
                result = self.training_manager.trigger_training(
                    task_type="aircraft",
                    triggered_by="scheduler"
                )
                logger.info(f"Training trigger result: {result}")

            else:
                logger.info("No training needed")

        except Exception as e:
            logger.error(f"Failed to check and trigger training: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def get_status(self) -> dict:
        """获取调度器状态"""
        now = datetime.now()
        next_run = None

        if now.hour < self.schedule_hour:
            # 今天还未到调度时间
            next_run = datetime.combine(now.date(), dt_time(self.schedule_hour, 0))
        else:
            # 明天的调度时间
            next_run = datetime.combine((now + datetime.timedelta(days=1)).date(), dt_time(self.schedule_hour, 0))

        return {
            "schedule_hour": self.schedule_hour,
            "is_running": self._thread and self._thread.is_alive(),
            "current_time": now.isoformat(),
            "next_run": next_run.isoformat()
        }
