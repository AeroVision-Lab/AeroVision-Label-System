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
    def __init__(self, db_path: str = './labels.db'):
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
        cursor.execute('''
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 创建航司表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS airlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL
            )
        ''')

        # 创建机型表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS aircraft_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL
            )
        ''')

        # 创建图片锁表（用于多人协作时防止冲突）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS image_locks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                locked_at REAL NOT NULL
            )
        ''')

        conn.commit()
        conn.close()

    def load_preset_data(self, data_dir: str):
        """加载预置数据（航司和机型）"""
        airlines_file = os.path.join(data_dir, 'airlines.json')
        if os.path.exists(airlines_file):
            with open(airlines_file, 'r', encoding='utf-8') as f:
                airlines = json.load(f)
                for airline in airlines:
                    self.add_airline(airline['code'], airline['name'], ignore_exists=True)

        types_file = os.path.join(data_dir, 'aircraft_types.json')
        if os.path.exists(types_file):
            with open(types_file, 'r', encoding='utf-8') as f:
                types = json.load(f)
                for t in types:
                    self.add_aircraft_type(t['code'], t['name'], ignore_exists=True)

    # ==================== 航司操作 ====================

    def get_airlines(self) -> list:
        """获取所有航司"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, code, name FROM airlines ORDER BY code')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def add_airline(self, code: str, name: str, ignore_exists: bool = False) -> Optional[int]:
        """添加航司"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO airlines (code, name) VALUES (?, ?)', (code, name))
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
        cursor.execute('SELECT id, code, name FROM aircraft_types ORDER BY code')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def add_aircraft_type(self, code: str, name: str, ignore_exists: bool = False) -> Optional[int]:
        """添加机型"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO aircraft_types (code, name) VALUES (?, ?)', (code, name))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            if not ignore_exists:
                raise
            return None
        finally:
            conn.close()

    # ==================== 标注操作 ====================

    def get_next_sequence(self, type_id: str) -> int:
        """获取指定机型的下一个序号"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_name FROM labels WHERE type_id = ? ORDER BY file_name DESC LIMIT 1",
            (type_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return 1

        # 解析文件名获取序号，格式：A320-0001.jpg
        try:
            file_name = row['file_name']
            name_part = os.path.splitext(file_name)[0]  # A320-0001
            seq_str = name_part.split('-')[-1]  # 0001
            return int(seq_str) + 1
        except (ValueError, IndexError):
            return 1

    def add_label(self, data: dict) -> dict:
        """添加标注记录"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO labels (
                file_name, original_file_name, type_id, type_name,
                airline_id, airline_name, clarity, block,
                registration, registration_area
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['file_name'],
            data['original_file_name'],
            data['type_id'],
            data['type_name'],
            data['airline_id'],
            data['airline_name'],
            data['clarity'],
            data['block'],
            data['registration'],
            data['registration_area']
        ))

        conn.commit()
        label_id = cursor.lastrowid
        conn.close()

        return {'id': label_id, 'file_name': data['file_name']}

    def get_labels(self, page: int = 1, per_page: int = 50) -> dict:
        """获取标注列表（分页）"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) as count FROM labels')
        total = cursor.fetchone()['count']

        offset = (page - 1) * per_page
        cursor.execute('''
            SELECT * FROM labels
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        ''', (per_page, offset))
        rows = cursor.fetchall()
        conn.close()

        return {
            'total': total,
            'page': page,
            'per_page': per_page,
            'items': [dict(row) for row in rows]
        }

    def get_all_labels_for_export(self) -> list:
        """获取所有标注数据用于导出"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT file_name, type_id, type_name, airline_id, airline_name,
                   clarity, block, registration
            FROM labels
            ORDER BY file_name
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_all_labels_with_area(self) -> list:
        """获取所有标注数据（包含区域信息）用于 YOLO 导出"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT file_name, registration_area
            FROM labels
            ORDER BY file_name
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_labeled_original_filenames(self) -> set:
        """获取所有已标注的原始文件名集合"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT original_file_name FROM labels')
        rows = cursor.fetchall()
        conn.close()
        return {row['original_file_name'] for row in rows}


    def get_label_by_id(self, label_id: int) -> Optional[dict]:
        """根据ID获取标注记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM labels WHERE id = ?', (label_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_label(self, label_id: int, data: dict) -> bool:
        """更新标注记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
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
        """, (
            data['type_id'],
            data['type_name'],
            data['airline_id'],
            data['airline_name'],
            data['clarity'],
            data['block'],
            data['registration'],
            data['registration_area'],
            label_id
        ))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def delete_label(self, label_id: int) -> bool:
        """删除标注记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM labels WHERE id = ?', (label_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def get_stats(self) -> dict:
        """获取统计信息"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) as count FROM labels')
        total = cursor.fetchone()['count']

        cursor.execute('''
            SELECT type_id, COUNT(*) as count
            FROM labels
            GROUP BY type_id
            ORDER BY count DESC
        ''')
        by_type = {row['type_id']: row['count'] for row in cursor.fetchall()}

        cursor.execute('''
            SELECT airline_id, COUNT(*) as count
            FROM labels
            GROUP BY airline_id
            ORDER BY count DESC
        ''')
        by_airline = {row['airline_id']: row['count'] for row in cursor.fetchall()}

        conn.close()

        return {
            'total_labeled': total,
            'by_type': by_type,
            'by_airline': by_airline
        }

    # ==================== 图片锁操作 ====================

    def cleanup_expired_locks(self):
        """清理过期的锁"""
        conn = self.get_connection()
        cursor = conn.cursor()
        expire_time = time.time() - LOCK_TIMEOUT
        cursor.execute('DELETE FROM image_locks WHERE locked_at < ?', (expire_time,))
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
        cursor.execute('SELECT user_id, locked_at FROM image_locks WHERE filename = ?', (filename,))
        row = cursor.fetchone()
        
        if row:
            # 已被锁定，检查是否是同一用户
            if row['user_id'] == user_id:
                # 同一用户，更新锁定时间
                cursor.execute(
                    'UPDATE image_locks SET locked_at = ? WHERE filename = ?',
                    (time.time(), filename)
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
                'INSERT INTO image_locks (filename, user_id, locked_at) VALUES (?, ?, ?)',
                (filename, user_id, time.time())
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
            'DELETE FROM image_locks WHERE filename = ? AND user_id = ?',
            (filename, user_id)
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def release_all_user_locks(self, user_id: str) -> int:
        """释放某用户的所有锁（用于用户断开连接时）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM image_locks WHERE user_id = ?', (user_id,))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected

    def get_locked_filenames(self) -> set:
        """获取所有被锁定的文件名（排除过期的）"""
        self.cleanup_expired_locks()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT filename FROM image_locks')
        rows = cursor.fetchall()
        conn.close()
        return {row['filename'] for row in rows}

    def get_lock_info(self, filename: str) -> Optional[dict]:
        """获取指定文件的锁信息"""
        self.cleanup_expired_locks()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM image_locks WHERE filename = ?', (filename,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

