#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本

用于将现有数据迁移到新的数据库schema
- 添加 review_status 字段到 labels 表
- 添加 ai_approved 字段到 labels 表
- 创建 ai_predictions 表
- 将现有标注记录的 review_status 设置为 'reviewed'（已人工检查）
"""

import sys
import os
import sqlite3

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database


def migrate_database(db_path: str):
    """
    执行数据库迁移

    Args:
        db_path: 数据库文件路径
    """
    print(f"开始迁移数据库: {db_path}")

    # 创建数据库实例（会自动添加新表和字段）
    db = Database(db_path)

    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 1. 检查是否需要更新现有数据的review_status
        cursor.execute("PRAGMA table_info(labels)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'review_status' in columns and 'ai_approved' in columns:
            print("检查现有数据...")

            # 更新所有现有标注记录为已人工检查
            cursor.execute("""
                UPDATE labels
                SET review_status = 'reviewed',
                    ai_approved = 0
                WHERE review_status IS NULL OR review_status = 'pending'
            """)

            affected = cursor.rowcount
            print(f"已更新 {affected} 条标注记录为 'reviewed' 状态")

        # 2. 验证迁移结果
        print("\n验证迁移结果:")

        # 检查 ai_predictions 表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_predictions'")
        ai_predictions_exists = cursor.fetchone() is not None
        print(f"- ai_predictions 表: {'存在' if ai_predictions_exists else '不存在'}")

        # 检查 labels 表字段
        cursor.execute("PRAGMA table_info(labels)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"- review_status 字段: {'存在' if 'review_status' in columns else '不存在'}")
        print(f"- ai_approved 字段: {'存在' if 'ai_approved' in columns else '不存在'}")

        # 统计各类状态的标注数量
        cursor.execute("SELECT review_status, COUNT(*) as count FROM labels GROUP BY review_status")
        status_counts = {row[0]: row[1] for row in cursor.fetchall()}
        print(f"\n标注记录状态分布:")
        for status, count in status_counts.items():
            print(f"  - {status}: {count}")

        conn.commit()
        print("\n✅ 数据库迁移成功完成!")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ 数据库迁移失败: {str(e)}")
        raise
    finally:
        conn.close()


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='数据库迁移脚本')
    parser.add_argument(
        '--db-path',
        type=str,
        default='./data/labels.db',
        help='数据库文件路径 (默认: ./data/labels.db)'
    )

    args = parser.parse_args()

    # 确保数据目录存在
    data_dir = os.path.dirname(args.db_path)
    if data_dir and not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
        print(f"创建数据目录: {data_dir}")

    # 执行迁移
    migrate_database(args.db_path)


if __name__ == '__main__':
    main()
