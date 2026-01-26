#!/usr/bin/env python3
"""
诊断 AI 模块问题
"""

import os
import sys
import traceback
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_1_check_environment():
    """测试 1: 检查环境变量和配置文件"""
    print("=" * 60)
    print("测试 1: 检查环境变量和配置文件")
    print("=" * 60)

    print(f"当前工作目录: {os.getcwd()}")
    print(f"AI_CONFIG_PATH: {os.getenv('AI_CONFIG_PATH', './config.yaml')}")

    config_path = os.getenv("AI_CONFIG_PATH", "./config.yaml")
    if os.path.exists(config_path):
        print(f"✓ 配置文件存在: {config_path}")
        import yaml

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        print(f"  模型路径: {config.get('models', {})}")
    else:
        print(f"✗ 配置文件不存在: {config_path}")

    print()


def test_2_check_model_files():
    """测试 2: 检查模型文件是否存在"""
    print("=" * 60)
    print("测试 2: 检查模型文件是否存在")
    print("=" * 60)

    import yaml

    config_path = os.getenv("AI_CONFIG_PATH", "./config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    models = config.get("models", {})
    model_paths = [
        ("aircraft", models.get("aircraft", {}).get("path")),
        ("airline", models.get("airline", {}).get("path")),
        ("detection", models.get("detection", {}).get("path")),
    ]

    for model_type, path in model_paths:
        if path:
            exists = os.path.exists(path)
            status = "✓" if exists else "✗"
            print(f"{status} {model_type}: {path} - {'存在' if exists else '不存在'}")

    print()


def test_3_import_ai_predictor():
    """测试 3: 尝试导入 AIPredictor"""
    print("=" * 60)
    print("测试 3: 尝试导入 AIPredictor")
    print("=" * 60)

    try:
        from ai_service.ai_predictor import AIPredictor

        print("✓ 成功导入 AIPredictor")
    except Exception as e:
        print(f"✗ 导入 AIPredictor 失败: {e}")
        traceback.print_exc()

    print()


def test_4_initialize_ai_predictor():
    """测试 4: 尝试初始化 AIPredictor"""
    print("=" * 60)
    print("测试 4: 尝试初始化 AIPredictor")
    print("=" * 60)

    try:
        from ai_service.ai_predictor import AIPredictor

        config_path = os.getenv("AI_CONFIG_PATH", "./config.yaml")
        ai_predictor = AIPredictor(config_path)
        print("✓ AIPredictor 初始化成功")
        print(f"  Config: {ai_predictor.get_config()}")
    except Exception as e:
        print(f"✗ AIPredictor 初始化失败: {e}")
        traceback.print_exc()

    print()


def test_5_load_models():
    """测试 5: 尝试加载模型"""
    print("=" * 60)
    print("测试 5: 尝试加载模型")
    print("=" * 60)

    try:
        from ai_service.ai_predictor import AIPredictor

        config_path = os.getenv("AI_CONFIG_PATH", "./config.yaml")
        ai_predictor = AIPredictor(config_path)
        ai_predictor.load_models()
        print("✓ 模型加载成功")
    except Exception as e:
        print(f"✗ 模型加载失败: {e}")
        traceback.print_exc()

    print()


def test_6_run_startup_prediction():
    """测试 6: 运行启动时预测"""
    print("=" * 60)
    print("测试 6: 运行启动时预测")
    print("=" * 60)

    try:
        from app import run_startup_ai_prediction

        print("✓ 成功导入 run_startup_ai_prediction")

        # 设置环境变量
        os.environ["IMAGES_DIR"] = "./images"
        os.environ["LABELED_DIR"] = "./labeled"
        os.environ["DATABASE_PATH"] = "./labels.db"
        os.environ["AI_CONFIG_PATH"] = "./config.yaml"

        # 运行预测
        run_startup_ai_prediction()
        print("✓ 启动时预测函数执行完成")
    except Exception as e:
        print(f"✗ 启动时预测失败: {e}")
        traceback.print_exc()

    print()


def test_7_check_gpu():
    """测试 7: 检查 CUDA/GPU 可用性"""
    print("=" * 60)
    print("测试 7: 检查 CUDA/GPU 可用性")
    print("=" * 60)

    try:
        import torch

        cuda_available = torch.cuda.is_available()
        print(f"✓ PyTorch 可用")
        print(f"  CUDA 可用: {cuda_available}")
        if cuda_available:
            print(f"  CUDA 设备数: {torch.cuda.device_count()}")
            print(f"  当前设备: {torch.cuda.current_device()}")
            print(f"  设备名称: {torch.cuda.get_device_name(0)}")
    except Exception as e:
        print(f"✗ PyTorch 检查失败: {e}")

    print()


def test_8_check_database():
    """测试 8: 检查数据库连接"""
    print("=" * 60)
    print("测试 8: 检查数据库连接")
    print("=" * 60)

    try:
        from database import Database

        db_path = os.getenv("DATABASE_PATH", "./labels.db")
        db = Database(db_path)
        print(f"✓ 数据库连接成功: {db_path}")
        labeled_files = db.get_labeled_original_filenames()
        print(f"  已标注文件数: {len(labeled_files)}")
    except Exception as e:
        print(f"✗ 数据库连接失败: {e}")
        traceback.print_exc()

    print()


def test_9_check_images_dir():
    """测试 9: 检查 images 目录"""
    print("=" * 60)
    print("测试 9: 检查 images 目录")
    print("=" * 60)

    images_dir = os.getenv("IMAGES_DIR", "./images")
    print(f"Images 目录: {images_dir}")

    if os.path.exists(images_dir):
        print(f"✓ 目录存在")
        files = os.listdir(images_dir)
        print(f"  文件数: {len(files)}")
        image_files = [
            f
            for f in files
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"))
        ]
        print(f"  图片数: {len(image_files)}")
        if image_files:
            print(f"  前 5 个图片: {image_files[:5]}")
    else:
        print(f"✗ 目录不存在")

    print()


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("开始诊断 AI 模块问题")
    print("=" * 60 + "\n")

    test_1_check_environment()
    test_2_check_model_files()
    test_3_import_ai_predictor()
    test_4_initialize_ai_predictor()
    test_5_load_models()
    test_6_run_startup_prediction()
    test_7_check_gpu()
    test_8_check_database()
    test_9_check_images_dir()

    print("=" * 60)
    print("诊断完成")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
