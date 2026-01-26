#!/usr/bin/env python3
"""
AI 模块完整测试脚本
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_model_path_resolution():
    """测试模型路径解析"""
    print("=" * 60)
    print("测试 1: 模型路径解析")
    print("=" * 60)

    from ai_service.ai_predictor import AIPredictor

    ai_predictor = AIPredictor("./config.yaml")
    config = ai_predictor.get_config()

    print(f"机型模型路径: {config['models']['aircraft']['path']}")
    print(f"航司模型路径: {config['models']['airline']['path']}")
    print(f"检测模型路径: {config['models']['detection']['path']}")
    print(f"检测启用: {ai_predictor.is_enabled('detection')}")

    assert Path(config["models"]["aircraft"]["path"]).exists()
    assert Path(config["models"]["airline"]["path"]).exists()

    print("✓ 模型路径解析测试通过\n")


def test_model_loading():
    """测试模型加载"""
    print("=" * 60)
    print("测试 2: 模型加载")
    print("=" * 60)

    from ai_service.ai_predictor import AIPredictor

    ai_predictor = AIPredictor("./config.yaml")
    ai_predictor.load_models()

    print("✓ 模型加载测试通过\n")


def test_single_prediction():
    """测试单个图片预测"""
    print("=" * 60)
    print("测试 3: 单个图片预测")
    print("=" * 60)

    from ai_service.ai_predictor import AIPredictor

    ai_predictor = AIPredictor("./config.yaml")
    ai_predictor.load_models()

    # 使用测试图片
    test_image = "tests/test_images/test_1.jpg"
    if not Path(test_image).exists():
        print("⚠ 测试图片不存在，跳过此测试")
        return

    result = ai_predictor.predict_single(test_image)

    print(f"文件名: {result['filename']}")
    print(
        f"机型: {result['aircraft_class']} (置信度: {result['aircraft_confidence']:.2f})"
    )
    print(
        f"航司: {result['airline_class']} (置信度: {result['airline_confidence']:.2f})"
    )
    print(f"注册号: {result['registration']}")
    print(f"清晰度: {result['clarity']:.2f}")
    print(f"遮挡: {result['block']:.2f}")

    assert "aircraft_class" in result
    assert "airline_class" in result

    print("✓ 单个图片预测测试通过\n")


def test_batch_prediction():
    """测试批量预测"""
    print("=" * 60)
    print("测试 4: 批量预测")
    print("=" * 60)

    from ai_service.ai_predictor import AIPredictor

    ai_predictor = AIPredictor("./config.yaml")
    ai_predictor.load_models()

    # 准备测试图片
    test_dir = Path("tests/test_images")
    image_paths = list(test_dir.glob("*.jpg"))[:3]

    if not image_paths:
        print("⚠ 没有测试图片，跳过此测试")
        return

    result = ai_predictor.predict_batch([str(p) for p in image_paths])

    print(f"总图片数: {result['statistics']['total']}")
    print(f"高置信度数: {result['statistics']['high_confidence_count']}")
    print(f"新类别数: {result['statistics']['new_class_count']}")

    assert result["statistics"]["total"] == len(image_paths)

    print("✓ 批量预测测试通过\n")


def test_startup_prediction():
    """测试启动时预测"""
    print("=" * 60)
    print("测试 5: 启动时预测")
    print("=" * 60)

    import os

    os.environ["IMAGES_DIR"] = "./images"
    os.environ["LABELED_DIR"] = "./labeled"
    os.environ["DATABASE_PATH"] = "./labels.db"
    os.environ["AI_CONFIG_PATH"] = "./config.yaml"

    from app import run_startup_ai_prediction

    # 确保有测试图片
    images_dir = Path("./images")
    test_dir = Path("tests/test_images")

    if not list(images_dir.glob("*.jpg")):
        for img_file in test_dir.glob("*.jpg"):
            import shutil

            shutil.copy(img_file, images_dir / img_file.name)

    print("运行启动时 AI 预测...")
    run_startup_ai_prediction()
    print("✓ 启动时预测测试通过\n")


def test_database_prediction_storage():
    """测试预测结果数据库存储"""
    print("=" * 60)
    print("测试 6: 预测结果数据库存储")
    print("=" * 60)

    from database import Database

    db = Database("./labels.db")

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM ai_predictions")
    count = cursor.fetchone()[0]
    conn.close()

    print(f"数据库中的预测结果数: {count}")

    assert count > 0

    print("✓ 预测结果数据库存储测试通过\n")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("开始 AI 模块完整测试")
    print("=" * 60 + "\n")

    try:
        test_model_path_resolution()
        test_model_loading()
        test_single_prediction()
        test_batch_prediction()
        test_startup_prediction()
        test_database_prediction_storage()

        print("=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
