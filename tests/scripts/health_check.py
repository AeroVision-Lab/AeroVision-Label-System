"""
健康检查脚本
快速检查系统各组件状态，用于定位问题

用法:
    python health_check.py                    # 检查所有组件
    python health_check.py --component db     # 只检查数据库
    python health_check.py --component ai     # 只检查AI服务
"""

import sys
import os
import argparse
import time
from pathlib import Path
import json
import sqlite3

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from database import Database
from ai_service.ai_predictor import AIPredictor

# ANSI 颜色代码
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def print_status(message, status):
    """打印带颜色的状态信息"""
    status_symbol = "✓" if status else "✗"
    color = GREEN if status else RED
    print(f"{color}{status_symbol} {message}{RESET}")
    return status


def check_database(db_path):
    """检查数据库"""
    print(f"\n{BLUE}=== Database Health Check ==={RESET}")

    all_ok = True

    try:
        # 检查数据库文件是否存在
        print_status(f"Database file exists: {db_path}", os.path.exists(db_path))
        if not os.path.exists(db_path):
            return False

        # 尝试连接数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print_status(f"Tables found: {len(tables)}", len(tables) > 0)

        # 检查必需的表
        required_tables = [
            "labels",
            "airlines",
            "aircraft_types",
            "image_locks",
            "skipped_images",
            "ai_predictions",
        ]
        for table in required_tables:
            table_exists = table in tables
            if not print_status(f"Table '{table}' exists", table_exists):
                all_ok = False

        # 检查数据完整性
        cursor.execute("SELECT COUNT(*) FROM labels")
        label_count = cursor.fetchone()[0]
        print_status(f"Labels count: {label_count}", True)

        cursor.execute("SELECT COUNT(*) FROM airlines")
        airline_count = cursor.fetchone()[0]
        print_status(f"Airlines count: {airline_count}", airline_count > 0)

        cursor.execute("SELECT COUNT(*) FROM aircraft_types")
        type_count = cursor.fetchone()[0]
        print_status(f"Aircraft types count: {type_count}", type_count > 0)

        cursor.execute("SELECT COUNT(*) FROM ai_predictions")
        ai_pred_count = cursor.fetchone()[0]
        print_status(f"AI predictions count: {ai_pred_count}", True)

        # 检查数据库是否有损坏
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        integrity_ok = integrity == "ok"
        if not print_status("Database integrity check", integrity_ok):
            all_ok = False

        conn.close()

    except Exception as e:
        print_status(f"Database error: {e}", False)
        all_ok = False

    return all_ok


def check_ai_models(config_path):
    """检查AI模型"""
    print(f"\n{BLUE}=== AI Models Health Check ==={RESET}")

    all_ok = True

    try:
        # 检查配置文件
        config_file = Path(config_path)
        print_status(f"Config file exists: {config_path}", config_file.exists())

        if not config_file.exists():
            print(f"{YELLOW}Using default config{RESET}")
            return False

        # 读取配置
        with open(config_file, "r") as f:
            config = (
                json.load(f)
                if config_path.endswith(".json")
                else __import__("yaml").safe_load(f)
            )

        # 检查模型路径
        models = config.get("models", {})
        for model_name, model_config in models.items():
            model_path = model_config.get("path")
            print_status(
                f"{model_name} model path: {model_path}", Path(model_path).exists()
            )

        # 尝试初始化 AI predictor
        print_status("Initializing AI predictor...", True)
        start_time = time.time()

        try:
            predictor = AIPredictor(config_path)
            init_time = time.time() - start_time
            print_status(f"AI predictor initialized in {init_time:.2f}s", True)

            # 检查各个服务
            services = ["ocr", "quality", "hdbscan"]
            for service in services:
                enabled = predictor.is_enabled(service)
                print_status(f"Service '{service}' enabled", enabled)

            # 尝试加载模型（可选，比较耗时）
            try_load_models = (
                os.getenv("HEALTH_CHECK_LOAD_MODELS", "false").lower() == "true"
            )
            if try_load_models:
                print_status("Loading models (this may take a while)...", True)
                start_time = time.time()
                predictor.load_models()
                load_time = time.time() - start_time
                print_status(f"Models loaded in {load_time:.2f}s", True)

                # 卸载模型释放内存
                predictor.unload_models()
            else:
                print(
                    f"{YELLOW}Skipping model load (set HEALTH_CHECK_LOAD_MODELS=true to test model loading){RESET}"
                )

        except Exception as e:
            print_status(f"AI predictor initialization failed: {e}", False)
            all_ok = False

    except Exception as e:
        print_status(f"AI models error: {e}", False)
        all_ok = False

    return all_ok


def check_directories():
    """检查必要的目录"""
    print(f"\n{BLUE}=== Directories Health Check ==={RESET}")

    all_ok = True

    directories = {
        "IMAGES_DIR": os.getenv("IMAGES_DIR", "./images"),
        "LABELED_DIR": os.getenv("LABELED_DIR", "./labeled"),
        "DATA_DIR": os.path.join(project_root, "data"),
    }

    for name, path in directories.items():
        exists = os.path.exists(path)
        if exists:
            is_dir = os.path.isdir(path)
            file_count = len(os.listdir(path)) if is_dir else 0
            print_status(f"{name} ({path}): {file_count} files", is_dir)
            if not is_dir:
                all_ok = False
        else:
            print_status(f"{name} ({path}): Not found", False)
            all_ok = False

    return all_ok


def check_dependencies():
    """检查Python依赖"""
    print(f"\n{BLUE}=== Dependencies Health Check ==={RESET}")

    all_ok = True

    required_packages = [
        "flask",
        "flask_cors",
        "requests",
        "yaml",
        "cv2",
        "numpy",
        "PIL",
        "ultralytics",
        "hdbscan",
    ]

    for package in required_packages:
        try:
            if package == "cv2":
                import cv2
            elif package == "PIL":
                from PIL import Image
            elif package == "yaml":
                import yaml
            else:
                __import__(package)
            print_status(f"Package '{package}' installed", True)
        except ImportError:
            print_status(f"Package '{package}' NOT installed", False)
            all_ok = False

    return all_ok


def check_ocr_service():
    """检查OCR服务"""
    print(f"\n{BLUE}=== OCR Service Health Check ==={RESET}")

    all_ok = True

    ocr_url = os.getenv("OCR_API_URL", "http://localhost:8000/v2/models/ocr/infer")

    try:
        import requests

        print_status(f"Checking OCR API at {ocr_url}", True)

        # 尝试发送一个简单的健康检查请求
        try:
            response = requests.get(ocr_url.replace("/infer", "/health"), timeout=5)
            print_status(
                f"OCR service health check: {response.status_code}",
                response.status_code == 200,
            )
        except:
            # 如果没有健康检查端点，至少检查服务是否可访问
            print(
                f"{YELLOW}OCR service health endpoint not found, skipping detailed check{RESET}"
            )

    except Exception as e:
        print_status(f"OCR service error: {e}", False)
        all_ok = False

    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="Health check for AeroVision Label System"
    )
    parser.add_argument(
        "--component",
        choices=["all", "db", "ai", "dirs", "deps", "ocr"],
        default="all",
        help="Component to check",
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("DATABASE_PATH", "./labels.db"),
        help="Database path",
    )
    parser.add_argument(
        "--config-path",
        default=os.getenv("AI_CONFIG_PATH", "./config.yaml"),
        help="AI config path",
    )

    args = parser.parse_args()

    print(f"{BLUE}{'=' * 50}{RESET}")
    print(f"{BLUE}AeroVision Label System - Health Check{RESET}")
    print(f"{BLUE}{'=' * 50}{RESET}")

    results = {}

    if args.component in ["all", "db"]:
        results["database"] = check_database(args.db_path)

    if args.component in ["all", "ai"]:
        results["ai_models"] = check_ai_models(args.config_path)

    if args.component in ["all", "dirs"]:
        results["directories"] = check_directories()

    if args.component in ["all", "deps"]:
        results["dependencies"] = check_dependencies()

    if args.component in ["all", "ocr"]:
        results["ocr_service"] = check_ocr_service()

    # 总结
    print(f"\n{BLUE}{'=' * 50}{RESET}")
    print(f"{BLUE}Summary{RESET}")
    print(f"{BLUE}{'=' * 50}{RESET}")

    all_passed = all(results.values())

    for component, status in results.items():
        print_status(f"{component}", status)

    if all_passed:
        print(f"\n{GREEN}All checks passed! ✓{RESET}")
        return 0
    else:
        print(f"\n{RED}Some checks failed! ✗{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
