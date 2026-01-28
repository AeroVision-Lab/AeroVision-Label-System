"""
Pytest fixtures
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path
import pytest

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database import Database


@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
def temp_dirs():
    """创建临时目录"""
    images_dir = tempfile.mkdtemp()
    labeled_dir = tempfile.mkdtemp()

    import app as app_module

    original_images_dir = app_module.IMAGES_DIR
    original_labeled_dir = app_module.LABELED_DIR

    app_module.IMAGES_DIR = images_dir
    app_module.LABELED_DIR = labeled_dir

    yield images_dir, labeled_dir

    # 恢复原始设置
    app_module.IMAGES_DIR = original_images_dir
    app_module.LABELED_DIR = original_labeled_dir

    # 清理临时目录
    shutil.rmtree(images_dir, ignore_errors=True)
    shutil.rmtree(labeled_dir, ignore_errors=True)
