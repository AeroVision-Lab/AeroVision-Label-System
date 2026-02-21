"""
数据库操作模块
"""

import sqlite3
import os
import json
import time
from typing import Optional

# 锁超时时间（秒）- 10分钟后自动释放
LOCK_TIMEOUT = 600


class Database:
    def __init__(self, db_path: str = "./labels.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """初始化数据库表"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 创建标注表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL UNIQUE,
                original_file_name TEXT NOT NULL,
                type_id TEXT NOT NULL,
                type_name TEXT NOT NULL,
                airline_id TEXT NOT NULL,
                airline_name TEXT NOT NULL,
                clarity REAL NOT NULL,
                block REAL NOT NULL,
                registration TEXT NOT NULL,
                registration_area TEXT NOT NULL,
                review_status TEXT DEFAULT 'pending',
                ai_approved INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 检查并添加review_status字段（用于数据库迁移）
        cursor.execute("PRAGMA table_info(labels)")
        columns = [col[1] for col in cursor.fetchall()]
        if "review_status" not in columns:
            cursor.execute(
                "ALTER TABLE labels ADD COLUMN review_status TEXT DEFAULT 'pending'"
            )
        if "ai_approved" not in columns:
            cursor.execute(
                "ALTER TABLE labels ADD COLUMN ai_approved INTEGER DEFAULT 0"
            )

        # 创建航司表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS airlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL
            )
        """)

        # 创建机型表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS aircraft_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL
            )
        """)

        # 创建图片锁表（用于多人协作时防止冲突）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS image_locks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                locked_at REAL NOT NULL
            )
        """)

        # 创建跳过（废图）记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skipped_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                skipped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建AI预测记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                aircraft_class TEXT NOT NULL,
                aircraft_confidence REAL NOT NULL,
                airline_class TEXT NOT NULL,
                airline_confidence REAL NOT NULL,
                registration TEXT,
                registration_area TEXT,
                registration_confidence REAL DEFAULT 0.0,
                clarity REAL DEFAULT 0.0,
                block REAL DEFAULT 0.0,
                quality_confidence REAL DEFAULT 0.0,
                is_new_class INTEGER DEFAULT 0,
                outlier_score REAL DEFAULT 0.0,
                prediction_time REAL NOT NULL,
                processed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建训练任务表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                task_type TEXT NOT NULL,
                triggered_by TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                total_samples INTEGER DEFAULT 0,
                progress REAL DEFAULT 0.0,
                current_epoch INTEGER DEFAULT 0,
                total_epochs INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                config_json TEXT,
                dataset_info_json TEXT
            )
        """)

        # 创建模型版本表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_type TEXT NOT NULL,
                version_name TEXT NOT NULL UNIQUE,
                file_path TEXT NOT NULL,
                training_job_id INTEGER NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (training_job_id) REFERENCES training_jobs(id)
            )
        """)

        # 创建训练结果表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                training_job_id INTEGER NOT NULL UNIQUE,
                accuracy REAL,
                macro_recall REAL,
                ece REAL,
                total_samples INTEGER,
                num_classes INTEGER,
                per_class_accuracy TEXT,
                recall_per_class TEXT,
                confusion_matrix TEXT,
                confidence_mean REAL,
                confidence_std REAL,
                metrics_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (training_job_id) REFERENCES training_jobs(id)
            )
        """)

        # 兼容性处理：如果表结构不正确（有 user_id 字段），则重建表
        cursor.execute("PRAGMA table_info(skipped_images)")
        columns = [col[1] for col in cursor.fetchall()]
        if "user_id" in columns:
            # 备份数据
            cursor.execute("SELECT filename FROM skipped_images")
            old_data = cursor.fetchall()
            # 删除旧表
            cursor.execute("DROP TABLE skipped_images")
            # 创建新表
            cursor.execute("""
                CREATE TABLE skipped_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL UNIQUE,
                    skipped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 恢复数据
            for row in old_data:
                cursor.execute(
                    "INSERT INTO skipped_images (filename) VALUES (?)", (row[0],)
                )
            conn.commit()

        conn.commit()
        conn.close()

    def load_preset_data(self, data_dir: str):
        """加载预置数据（航司和机型）"""
        airlines_file = os.path.join(data_dir, "airlines.json")
        if os.path.exists(airlines_file):
            with open(airlines_file, "r", encoding="utf-8") as f:
                airlines = json.load(f)
                for airline in airlines:
                    self.add_airline(
                        airline["code"], airline["name"], ignore_exists=True
                    )

        types_file = os.path.join(data_dir, "aircraft_types.json")
        if os.path.exists(types_file):
            with open(types_file, "r", encoding="utf-8") as f:
                types = json.load(f)
                for t in types:
                    self.add_aircraft_type(t["code"], t["name"], ignore_exists=True)

    # ==================== 航司操作 ====================

    def get_airlines(self) -> list:
        """获取所有航司"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, code, name FROM airlines ORDER BY code")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def add_airline(
        self, code: str, name: str, ignore_exists: bool = False
    ) -> Optional[int]:
        """添加航司"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO airlines (code, name) VALUES (?, ?)", (code, name)
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            if not ignore_exists:
                raise
            return None
        finally:
            conn.close()

    # ==================== 机型操作 ====================

    def get_aircraft_types(self) -> list:
        """获取所有机型"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, code, name FROM aircraft_types ORDER BY code")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def add_aircraft_type(
        self, code: str, name: str, ignore_exists: bool = False
    ) -> Optional[int]:
        """添加机型"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO aircraft_types (code, name) VALUES (?, ?)", (code, name)
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            if not ignore_exists:
                raise
            return None
        finally:
            conn.close()

    def get_aircraft_type_id_by_code(self, code: str) -> Optional[int]:
        """根据 code 获取机型的数字 id"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM aircraft_types WHERE code = ?", (code,))
        row = cursor.fetchone()
        conn.close()
        return row["id"] if row else None

    def get_airline_id_by_code(self, code: str) -> Optional[int]:
        """根据 code 获取航司的数字 id"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM airlines WHERE code = ?", (code,))
        row = cursor.fetchone()
        conn.close()
        return row["id"] if row else None

    def get_aircraft_type_code_by_id(self, type_id: int) -> Optional[str]:
        """根据数字 id 获取机型的 code"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code FROM aircraft_types WHERE id = ?", (type_id,))
        row = cursor.fetchone()
        conn.close()
        return row["code"] if row else None

    def get_airline_code_by_id(self, airline_id: int) -> Optional[str]:
        """根据数字 id 获取航司的 code"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code FROM airlines WHERE id = ?", (airline_id,))
        row = cursor.fetchone()
        conn.close()
        return row["code"] if row else None

    # ==================== 标注操作 ====================

    def get_next_sequence(self, type_id: str) -> int:
        """获取指定机型的下一个序号"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_name FROM labels WHERE type_id = ? ORDER BY file_name DESC LIMIT 1",
            (type_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return 1

        # 解析文件名获取序号，格式：A320-0001.jpg
        try:
            file_name = row["file_name"]
            name_part = os.path.splitext(file_name)[0]  # A320-0001
            seq_str = name_part.split("-")[-1]  # 0001
            return int(seq_str) + 1
        except (ValueError, IndexError):
            return 1

    def add_label(self, data: dict) -> dict:
        """添加标注记录"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO labels (
                file_name, original_file_name, type_id, type_name,
                airline_id, airline_name, clarity, block,
                registration, registration_area
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                data["file_name"],
                data["original_file_name"],
                data["type_id"],
                data["type_name"],
                data["airline_id"],
                data["airline_name"],
                data["clarity"],
                data["block"],
                data["registration"],
                data["registration_area"],
            ),
        )

        conn.commit()
        label_id = cursor.lastrowid
        conn.close()

        return {"id": label_id, "file_name": data["file_name"]}

    def get_labels(self, page: int = 1, per_page: int = 50) -> dict:
        """获取标注列表（分页）"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM labels")
        total = cursor.fetchone()["count"]

        offset = (page - 1) * per_page
        cursor.execute(
            """
            SELECT * FROM labels
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """,
            (per_page, offset),
        )
        rows = cursor.fetchall()
        conn.close()

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "items": [dict(row) for row in rows],
        }

    def get_all_labels_for_export(
        self, start_id: int = None, end_id: int = None
    ) -> list:
        """获取标注数据用于导出，支持ID范围筛选"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if start_id is not None and end_id is not None:
            cursor.execute(
                """
                SELECT file_name, type_id, type_name, airline_id, airline_name,
                       clarity, block, registration
                FROM labels
                WHERE id >= ? AND id <= ?
                ORDER BY file_name
            """,
                (start_id, end_id),
            )
        elif start_id is not None:
            cursor.execute(
                """
                SELECT file_name, type_id, type_name, airline_id, airline_name,
                       clarity, block, registration
                FROM labels
                WHERE id >= ?
                ORDER BY file_name
            """,
                (start_id,),
            )
        elif end_id is not None:
            cursor.execute(
                """
                SELECT file_name, type_id, type_name, airline_id, airline_name,
                       clarity, block, registration
                FROM labels
                WHERE id <= ?
                ORDER BY file_name
            """,
                (end_id,),
            )
        else:
            cursor.execute("""
                SELECT file_name, type_id, type_name, airline_id, airline_name,
                       clarity, block, registration
                FROM labels
                ORDER BY file_name
            """)

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_all_labels_with_area(
        self, start_id: int = None, end_id: int = None
    ) -> list:
        """获取标注数据（包含区域信息）用于 YOLO 导出，支持ID范围筛选"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if start_id is not None and end_id is not None:
            cursor.execute(
                """
                SELECT file_name, registration_area
                FROM labels
                WHERE id >= ? AND id <= ?
                ORDER BY file_name
            """,
                (start_id, end_id),
            )
        elif start_id is not None:
            cursor.execute(
                """
                SELECT file_name, registration_area
                FROM labels
                WHERE id >= ?
                ORDER BY file_name
            """,
                (start_id,),
            )
        elif end_id is not None:
            cursor.execute(
                """
                SELECT file_name, registration_area
                FROM labels
                WHERE id <= ?
                ORDER BY file_name
            """,
                (end_id,),
            )
        else:
            cursor.execute("""
                SELECT file_name, registration_area
                FROM labels
                ORDER BY file_name
            """)

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_labeled_original_filenames(self) -> set:
        """获取所有已标注的原始文件名集合"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT original_file_name FROM labels")
        rows = cursor.fetchall()
        conn.close()
        return {row["original_file_name"] for row in rows}

    def get_label_by_id(self, label_id: int) -> Optional[dict]:
        """根据ID获取标注记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM labels WHERE id = ?", (label_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_label(self, label_id: int, data: dict) -> bool:
        """更新标注记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE labels SET
                type_id = ?,
                type_name = ?,
                airline_id = ?,
                airline_name = ?,
                clarity = ?,
                block = ?,
                registration = ?,
                registration_area = ?
            WHERE id = ?
        """,
            (
                data["type_id"],
                data["type_name"],
                data["airline_id"],
                data["airline_name"],
                data["clarity"],
                data["block"],
                data["registration"],
                data["registration_area"],
                label_id,
            ),
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def delete_label(self, label_id: int) -> bool:
        """删除标注记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM labels WHERE id = ?", (label_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def get_stats(self) -> dict:
        """获取统计信息"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM labels")
        total = cursor.fetchone()["count"]

        # 按机型统计（包含名称）
        cursor.execute("""
            SELECT type_id, type_name, COUNT(*) as count
            FROM labels
            GROUP BY type_id
            ORDER BY count DESC
        """)
        by_type = {row["type_id"]: row["count"] for row in cursor.fetchall()}

        # 获取涉及的机型列表（包含详情）
        cursor.execute("""
            SELECT type_id, type_name, COUNT(*) as count
            FROM labels
            GROUP BY type_id
            ORDER BY count DESC
        """)
        types_detail = [
            {"code": row["type_id"], "name": row["type_name"], "count": row["count"]}
            for row in cursor.fetchall()
        ]

        # 按航司统计（包含名称）
        cursor.execute("""
            SELECT airline_id, airline_name, COUNT(*) as count
            FROM labels
            GROUP BY airline_id
            ORDER BY count DESC
        """)
        by_airline = {row["airline_id"]: row["count"] for row in cursor.fetchall()}

        # 获取涉及的航司列表（包含详情）
        cursor.execute("""
            SELECT airline_id, airline_name, COUNT(*) as count
            FROM labels
            GROUP BY airline_id
            ORDER BY count DESC
        """)
        airlines_detail = [
            {
                "code": row["airline_id"],
                "name": row["airline_name"],
                "count": row["count"],
            }
            for row in cursor.fetchall()
        ]

        # 废图数量
        cursor.execute("SELECT COUNT(*) as count FROM skipped_images")
        skipped_count = cursor.fetchone()["count"]

        conn.close()

        return {
            "total_labeled": total,
            "by_type": by_type,
            "by_airline": by_airline,
            "types_detail": types_detail,
            "airlines_detail": airlines_detail,
            "skipped_count": skipped_count,
        }

    # ==================== 图片锁操作 ====================

    def cleanup_expired_locks(self):
        """清理过期的锁"""
        conn = self.get_connection()
        cursor = conn.cursor()
        expire_time = time.time() - LOCK_TIMEOUT
        cursor.execute("DELETE FROM image_locks WHERE locked_at < ?", (expire_time,))
        conn.commit()
        conn.close()

    def acquire_lock(self, filename: str, user_id: str) -> bool:
        """
        尝试获取图片锁
        返回 True 表示成功获取锁，False 表示图片已被他人锁定
        """
        self.cleanup_expired_locks()

        conn = self.get_connection()
        cursor = conn.cursor()

        # 检查是否已被锁定
        cursor.execute(
            "SELECT user_id, locked_at FROM image_locks WHERE filename = ?", (filename,)
        )
        row = cursor.fetchone()

        if row:
            # 已被锁定，检查是否是同一用户
            if row["user_id"] == user_id:
                # 同一用户，更新锁定时间
                cursor.execute(
                    "UPDATE image_locks SET locked_at = ? WHERE filename = ?",
                    (time.time(), filename),
                )
                conn.commit()
                conn.close()
                return True
            else:
                # 其他用户锁定
                conn.close()
                return False

        # 未被锁定，创建新锁
        try:
            cursor.execute(
                "INSERT INTO image_locks (filename, user_id, locked_at) VALUES (?, ?, ?)",
                (filename, user_id, time.time()),
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            # 并发情况下可能插入失败
            conn.close()
            return False

    def release_lock(self, filename: str, user_id: str) -> bool:
        """释放图片锁（只能释放自己的锁）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM image_locks WHERE filename = ? AND user_id = ?",
            (filename, user_id),
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def release_all_user_locks(self, user_id: str) -> int:
        """释放某用户的所有锁（用于用户断开连接时）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM image_locks WHERE user_id = ?", (user_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected

    def get_locked_filenames(self) -> set:
        """获取所有被锁定的文件名（排除过期的）"""
        self.cleanup_expired_locks()

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM image_locks")
        rows = cursor.fetchall()
        conn.close()
        return {row["filename"] for row in rows}

    def get_lock_info(self, filename: str) -> Optional[dict]:
        """获取指定文件的锁信息"""
        self.cleanup_expired_locks()

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM image_locks WHERE filename = ?", (filename,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    # ==================== 跳过（废图）操作 ====================

    def get_skipped_filenames(self) -> set:
        """获取所有被跳过的文件名集合"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM skipped_images")
        rows = cursor.fetchall()
        conn.close()
        return {row["filename"] for row in rows}

    def skip_image(self, filename: str) -> bool:
        """将图片标记为废图（跳过）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO skipped_images (filename) VALUES (?)", (filename,)
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            # 已经被跳过
            conn.close()
            return False

    # ==================== AI预测操作 ====================

    def add_ai_prediction(self, data: dict) -> dict:
        """添加AI预测记录"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO ai_predictions (
                    filename, aircraft_class, aircraft_confidence,
                    airline_class, airline_confidence, registration,
                    registration_area, registration_confidence,
                    clarity, block, quality_confidence,
                    is_new_class, outlier_score, prediction_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    data["filename"],
                    data["aircraft_class"],
                    data["aircraft_confidence"],
                    data["airline_class"],
                    data["airline_confidence"],
                    data.get("registration", ""),
                    data.get("registration_area", ""),
                    data.get("registration_confidence", 0.0),
                    data.get("clarity", 0.0),
                    data.get("block", 0.0),
                    data.get("quality_confidence", 0.0),
                    data.get("is_new_class", 0),
                    data.get("outlier_score", 0.0),
                    data["prediction_time"],
                ),
            )

            conn.commit()
            pred_id = cursor.lastrowid
            conn.close()
            return {"id": pred_id, "filename": data["filename"]}
        except sqlite3.IntegrityError:
            conn.close()
            return {"error": "Prediction already exists"}

    def get_ai_prediction(self, filename: str) -> Optional[dict]:
        """获取指定文件的AI预测结果"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ai_predictions WHERE filename = ?", (filename,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_unprocessed_predictions(self, limit: int = None) -> list:
        """获取未处理的AI预测记录（按优先级排序）"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 排序优先级：
        # 1. 新类别 (is_new_class=1) - 按outlier_score降序
        # 2. 样本量<8的已知类别 - 按样本量升序（样本越少越优先）
        # 3. 样本量>=8的已知类别 - 按置信度升序（置信度越低越优先）
        if limit:
            cursor.execute(
                """
                SELECT 
                    p.*,
                    CASE 
                        WHEN p.is_new_class = 1 THEN 0
                        WHEN (SELECT COUNT(*) FROM labels WHERE type_id = p.aircraft_class) < 8 THEN 1
                        ELSE 2
                    END AS priority,
                    (SELECT COUNT(*) FROM labels WHERE type_id = p.aircraft_class) AS sample_count
                FROM ai_predictions p
                WHERE p.processed = 0
                ORDER BY 
                    priority ASC,
                    CASE 
                        WHEN priority = 0 THEN -p.outlier_score
                        WHEN priority = 1 THEN sample_count
                        ELSE MIN(p.aircraft_confidence, p.airline_confidence)
                    END ASC
                LIMIT ?
            """,
                (limit,),
            )
        else:
            cursor.execute("""
                SELECT 
                    p.*,
                    CASE 
                        WHEN p.is_new_class = 1 THEN 0
                        WHEN (SELECT COUNT(*) FROM labels WHERE type_id = p.aircraft_class) < 8 THEN 1
                        ELSE 2
                    END AS priority,
                    (SELECT COUNT(*) FROM labels WHERE type_id = p.aircraft_class) AS sample_count
                FROM ai_predictions p
                WHERE p.processed = 0
                ORDER BY 
                    priority ASC,
                    CASE 
                        WHEN priority = 0 THEN -p.outlier_score
                        WHEN priority = 1 THEN sample_count
                        ELSE MIN(p.aircraft_confidence, p.airline_confidence)
                    END ASC
            """)

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_auto_approvable_predictions(self) -> list:
        """获取可以直接自动批准的预测（置信度>=95%且非新类）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM ai_predictions
            WHERE processed = 0
              AND is_new_class = 0
              AND aircraft_confidence >= ?
              AND airline_confidence >= ?
            ORDER BY prediction_time DESC
        """,
            (0.95, 0.95),
        )

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def mark_prediction_processed(self, filename: str) -> bool:
        """标记预测为已处理"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE ai_predictions SET processed = 1 WHERE filename = ?", (filename,)
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def update_ai_prediction_new_class_flag(
        self, filename: str, is_new_class: int, outlier_score: float = 0.0
    ) -> bool:
        """更新AI预测的新类别标记和异常分数"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE ai_predictions SET is_new_class = ?, outlier_score = ? WHERE filename = ?",
            (is_new_class, outlier_score, filename),
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def update_label_with_ai_data(self, label_id: int, ai_data: dict) -> bool:
        """更新标注记录的AI相关字段"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE labels SET
                review_status = ?,
                ai_approved = ?
            WHERE id = ?
        """,
            (
                ai_data.get("review_status", "pending"),
                1 if ai_data.get("ai_approved", False) else 0,
                label_id,
            ),
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def get_review_stats(self) -> dict:
        """获取复审统计信息"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 总预测数
        cursor.execute("SELECT COUNT(*) as count FROM ai_predictions")
        total_predictions = cursor.fetchone()["count"]

        # 未处理数
        cursor.execute(
            "SELECT COUNT(*) as count FROM ai_predictions WHERE processed = 0"
        )
        pending_count = cursor.fetchone()["count"]

        # 新类别数
        cursor.execute(
            "SELECT COUNT(*) as count FROM ai_predictions WHERE is_new_class = 1 AND processed = 0"
        )
        new_class_count = cursor.fetchone()["count"]

        # 可自动批准数
        cursor.execute("""
            SELECT COUNT(*) as count FROM ai_predictions
            WHERE processed = 0 AND is_new_class = 0
              AND aircraft_confidence >= 0.95 AND airline_confidence >= 0.95
        """)
        auto_approve_count = cursor.fetchone()["count"]

        # 标注表复审状态统计
        cursor.execute("""
            SELECT review_status, COUNT(*) as count
            FROM labels
            GROUP BY review_status
        """)
        review_status_counts = {
            row["review_status"]: row["count"] for row in cursor.fetchall()
        }

        conn.close()

        return {
            "total_predictions": total_predictions,
            "pending_count": pending_count,
            "new_class_count": new_class_count,
            "auto_approve_count": auto_approve_count,
            "review_status_counts": review_status_counts,
        }

    def bulk_mark_processed(self, filenames: list) -> int:
        """批量标记预测为已处理"""
        if not filenames:
            return 0

        conn = self.get_connection()
        cursor = conn.cursor()

        placeholders = ",".join("?" * len(filenames))
        cursor.execute(
            f"UPDATE ai_predictions SET processed = 1 WHERE filename IN ({placeholders})",
            filenames,
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected

    # ==================== 训练任务操作 ====================

    def create_training_job(self, task_type: str, triggered_by: str, config: dict, dataset_info: dict = None) -> int:
        """创建训练任务"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO training_jobs (status, task_type, triggered_by, config_json, dataset_info_json)
            VALUES (?, ?, ?, ?, ?)
        """,
            ( "pending", task_type, triggered_by,
              json.dumps(config) if config else None,
              json.dumps(dataset_info) if dataset_info else None)
        )

        conn.commit()
        job_id = cursor.lastrowid
        conn.close()
        return job_id

    def update_training_job_status(self, job_id: int, status: str, **kwargs) -> bool:
        """更新训练任务状态"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 构建动态更新语句
        update_fields = ["status = ?"]
        values = [status]

        if "progress" in kwargs:
            update_fields.append("progress = ?")
            values.append(kwargs["progress"])
        if "current_epoch" in kwargs:
            update_fields.append("current_epoch = ?")
            values.append(kwargs["current_epoch"])
        if "total_samples" in kwargs:
            update_fields.append("total_samples = ?")
            values.append(kwargs["total_samples"])
        if "total_epochs" in kwargs:
            update_fields.append("total_epochs = ?")
            values.append(kwargs["total_epochs"])
        if "error_message" in kwargs:
            update_fields.append("error_message = ?")
            values.append(kwargs["error_message"])

        # 处理时间戳
        if status == "running" and "started_at" not in kwargs:
            update_fields.append("started_at = CURRENT_TIMESTAMP")
        if status in ["completed", "failed"] and "completed_at" not in kwargs:
            update_fields.append("completed_at = CURRENT_TIMESTAMP")

        values.append(job_id)

        cursor.execute(
            f"UPDATE training_jobs SET {', '.join(update_fields)} WHERE id = ?",
            values
        )

        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def get_training_job(self, job_id: int) -> Optional[dict]:
        """获取训练任务详情"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM training_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_training_jobs(self, status: str = None, limit: int = None) -> list:
        """获取训练任务列表"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if status:
            cursor.execute(
                f"SELECT * FROM training_jobs WHERE status = ? ORDER BY created_at DESC",
                (status,)
            )
        else:
            cursor.execute("SELECT * FROM training_jobs ORDER BY created_at DESC")

        rows = cursor.fetchall()
        conn.close()

        # 解析JSON字段
        jobs = []
        for row in rows:
            job = dict(row)
            if job.get("config_json"):
                job["config"] = json.loads(job["config_json"])
            if job.get("dataset_info_json"):
                job["dataset_info"] = json.loads(job["dataset_info_json"])
            jobs.append(job)

        if limit:
            return jobs[:limit]
        return jobs

    def get_latest_training_job(self, task_type: str = None) -> Optional[dict]:
        """获取最新的训练任务"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if task_type:
            cursor.execute(
                "SELECT * FROM training_jobs WHERE task_type = ? ORDER BY created_at DESC LIMIT 1",
                (task_type,)
            )
        else:
            cursor.execute("SELECT * FROM training_jobs ORDER BY created_at DESC LIMIT 1")

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        job = dict(row)
        if job.get("config_json"):
            job["config"] = json.loads(job["config_json"])
        if job.get("dataset_info_json"):
            job["dataset_info"] = json.loads(job["dataset_info_json"])
        return job

    def get_running_training_job(self) -> Optional[dict]:
        """获取当前正在运行的任务"""
        jobs = self.get_training_jobs(status="running", limit=1)
        return jobs[0] if jobs else None

    # ==================== 模型版本操作 ====================

    def create_model_version(self, model_type: str, version_name: str, file_path: str, training_job_id: int) -> int:
        """创建模型版本记录"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 先将所有该类型的模型设为非激活
        cursor.execute("UPDATE model_versions SET is_active = 0 WHERE model_type = ?", (model_type,))

        # 创建新模型版本并设为激活
        cursor.execute(
            """
            INSERT INTO model_versions (model_type, version_name, file_path, training_job_id, is_active)
            VALUES (?, ?, ?, ?, 1)
        """,
            (model_type, version_name, file_path, training_job_id)
        )

        conn.commit()
        version_id = cursor.lastrowid
        conn.close()
        return version_id

    def get_model_versions(self, model_type: str = None, active_only: bool = False) -> list:
        """获取模型版本列表"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if model_type and active_only:
            cursor.execute(
                "SELECT * FROM model_versions WHERE model_type = ? AND is_active = 1 ORDER BY created_at DESC",
                (model_type,)
            )
        elif model_type:
            cursor.execute(
                "SELECT * FROM model_versions WHERE model_type = ? ORDER BY created_at DESC",
                (model_type,)
            )
        elif active_only:
            cursor.execute(
                "SELECT * FROM model_versions WHERE is_active = 1 ORDER BY model_type, created_at DESC"
            )
        else:
            cursor.execute("SELECT * FROM model_versions ORDER BY model_type, created_at DESC")

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_active_model(self, model_type: str) -> Optional[dict]:
        """获取指定类型的激活模型"""
        versions = self.get_model_versions(model_type=model_type, active_only=True)
        return versions[0] if versions else None

    def set_active_model(self, version_id: int) -> bool:
        """设置指定模型版本为激活"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 先获取该模型信息
        cursor.execute("SELECT model_type FROM model_versions WHERE id = ?", (version_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False

        model_type = row["model_type"]

        # 将同类型的所有模型设为非激活
        cursor.execute("UPDATE model_versions SET is_active = 0 WHERE model_type = ?", (model_type,))

        # 设置指定模型为激活
        cursor.execute("UPDATE model_versions SET is_active = 1 WHERE id = ?", (version_id,))

        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    # ==================== 训练结果操作 ====================

    def create_training_result(self, training_job_id: int, metrics: dict) -> int:
        """创建训练结果记录"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO training_results (
                training_job_id, accuracy, macro_recall, ece, total_samples, num_classes,
                per_class_accuracy, recall_per_class, confusion_matrix, confidence_mean, confidence_std, metrics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                training_job_id,
                metrics.get("accuracy"),
                metrics.get("macro_recall"),
                metrics.get("ece"),
                metrics.get("total_samples"),
                metrics.get("num_classes"),
                json.dumps(metrics.get("per_class_accuracy", [])),
                json.dumps(metrics.get("recall_per_class", [])),
                json.dumps(metrics.get("confusion_matrix", [])),
                metrics.get("confidence_mean"),
                metrics.get("confidence_std"),
                json.dumps(metrics)
            )
        )

        conn.commit()
        result_id = cursor.lastrowid
        conn.close()
        return result_id

    def get_training_result(self, training_job_id: int) -> Optional[dict]:
        """获取训练结果"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM training_results WHERE training_job_id = ?", (training_job_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        result = dict(row)
        if result.get("metrics_json"):
            result["metrics"] = json.loads(result["metrics_json"])
        if result.get("per_class_accuracy"):
            result["per_class_accuracy"] = json.loads(result["per_class_accuracy"])
        if result.get("recall_per_class"):
            result["recall_per_class"] = json.loads(result["recall_per_class"])
        if result.get("confusion_matrix"):
            result["confusion_matrix"] = json.loads(result["confusion_matrix"])
        return result

    def get_label_count_for_training(self) -> int:
        """获取可用于训练的标注数量"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM labels")
        count = cursor.fetchone()["count"]
        conn.close()
        return count

    def get_labels_for_training(self, min_samples_per_class: int = 0) -> list:
        """
        获取可用于训练的标注数据
        按机型分组统计，返回每个机型的样本数
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # 按机型统计样本数
        cursor.execute("""
            SELECT
                type_id,
                type_name,
                COUNT(*) as count
            FROM labels
            GROUP BY type_id
            ORDER BY count DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        # 过滤样本数不足的机型
        results = []
        for row in rows:
            if row["count"] >= min_samples_per_class:
                results.append({
                    "type_id": row["type_id"],
                    "type_name": row["type_name"],
                    "sample_count": row["count"]
                })

        return results

    def delete_training_job(self, job_id: int) -> bool:
        """删除训练任务（级联删除关联的结果和模型版本）"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 删除训练结果
            cursor.execute("DELETE FROM training_results WHERE training_job_id = ?", (job_id,))

            # 删除模型版本
            cursor.execute("DELETE FROM model_versions WHERE training_job_id = ?", (job_id,))

            # 删除训练任务
            cursor.execute("DELETE FROM training_jobs WHERE id = ?", (job_id,))

            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return affected > 0
        except Exception as e:
            conn.rollback()
            conn.close()
            raise e
