"""
故障排除脚本
帮助快速定位问题

用法:
    python troubleshoot.py                    # 运行所有检查
    python troubleshoot.py --check models      # 只检查模型
    python troubleshoot.py --check api         # 只检查API
"""

import sys
import os
import argparse
import traceback
import json
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# ANSI 颜色代码
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"


def print_header(title):
    """打印标题"""
    print(f"\n{BLUE}{'=' * 60}{RESET}")
    print(f"{BLUE}{title}{RESET}")
    print(f"{BLUE}{'=' * 60}{RESET}\n")


def print_section(title):
    """打印小节标题"""
    print(f"\n{CYAN}--- {title} ---{RESET}")


def print_success(message):
    """打印成功消息"""
    print(f"{GREEN}✓ {message}{RESET}")


def print_error(message):
    """打印错误消息"""
    print(f"{RED}✗ {message}{RESET}")


def print_warning(message):
    """打印警告消息"""
    print(f"{YELLOW}⚠ {message}{RESET}")


def print_info(message):
    """打印信息消息"""
    print(f"{CYAN}ℹ {message}{RESET}")


def check_config_files():
    """检查配置文件"""
    print_section("检查配置文件")

    config_path = os.getenv("AI_CONFIG_PATH", "./config.yaml")

    if not os.path.exists(config_path):
        print_error(f"配置文件不存在: {config_path}")
        return False

    print_success(f"配置文件存在: {config_path}")

    try:
        if config_path.endswith(".json"):
            with open(config_path, "r") as f:
                config = json.load(f)
        else:
            import yaml

            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

        print_success("配置文件可以解析")

        # 检查必要的配置项
        required_keys = ["models", "ocr", "quality", "hdbscan"]
        for key in required_keys:
            if key in config:
                print_success(f"配置项 '{key}' 存在")
            else:
                print_warning(f"配置项 '{key}' 不存在")

        # 检查模型路径
        models = config.get("models", {})
        for model_name, model_config in models.items():
            model_path = model_config.get("path")
            if model_path:
                if os.path.exists(model_path):
                    print_success(f"{model_name} 模型文件存在: {model_path}")
                else:
                    print_error(f"{model_name} 模型文件不存在: {model_path}")

        return True

    except Exception as e:
        print_error(f"解析配置文件失败: {e}")
        traceback.print_exc()
        return False


def check_database():
    """检查数据库"""
    print_section("检查数据库")

    db_path = os.getenv("DATABASE_PATH", "./labels.db")

    if not os.path.exists(db_path):
        print_error(f"数据库文件不存在: {db_path}")
        return False

    print_success(f"数据库文件存在: {db_path}")

    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 检查表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print_success(f"数据库包含 {len(tables)} 个表: {', '.join(tables)}")

        # 检查数据
        for table in ["labels", "airlines", "aircraft_types", "ai_predictions"]:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print_info(f"{table}: {count} 条记录")

        conn.close()
        return True

    except Exception as e:
        print_error(f"数据库检查失败: {e}")
        traceback.print_exc()
        return False


def check_directories():
    """检查目录"""
    print_section("检查目录")

    directories = {
        "IMAGES_DIR": os.getenv("IMAGES_DIR", "./images"),
        "LABELED_DIR": os.getenv("LABELED_DIR", "./labeled"),
        "DATA_DIR": os.path.join(project_root, "data"),
        "FRONTEND_DIR": os.path.join(project_root, "frontend/dist"),
    }

    all_ok = True
    for name, path in directories.items():
        if os.path.exists(path):
            if os.path.isdir(path):
                file_count = len(os.listdir(path)) if os.listdir(path) else 0
                print_success(f"{name} ({path}): {file_count} 个文件/目录")
            else:
                print_error(f"{name} ({path}): 不是目录")
                all_ok = False
        else:
            if name in ["IMAGES_DIR", "LABELED_DIR"]:
                print_warning(f"{name} ({path}): 不存在（可以自动创建）")
            else:
                print_info(f"{name} ({path}): 不存在")

    return all_ok


def check_models_loading():
    """检查模型加载"""
    print_section("检查模型加载")

    try:
        from ai_service.ai_predictor import AIPredictor

        config_path = os.getenv("AI_CONFIG_PATH", "./config.yaml")

        print_info("正在初始化 AI predictor...")
        predictor = AIPredictor(config_path)
        print_success("AI predictor 初始化成功")

        print_info("检查各个服务状态...")
        services = ["ocr", "quality", "hdbscan"]
        for service in services:
            enabled = predictor.is_enabled(service)
            status = "启用" if enabled else "禁用"
            print_info(f"服务 '{service}': {status}")

        print_info("正在加载模型（这可能需要一些时间）...")
        import time

        start_time = time.time()

        try:
            predictor.load_models()
            load_time = time.time() - start_time
            print_success(f"模型加载成功，耗时 {load_time:.2f} 秒")

            # 卸载模型释放内存
            predictor.unload_models()
            print_success("模型卸载成功")

            return True

        except Exception as e:
            print_error(f"模型加载失败: {e}")
            traceback.print_exc()
            return False

    except Exception as e:
        print_error(f"AI predictor 初始化失败: {e}")
        traceback.print_exc()
        return False


def check_api_endpoints():
    """检查 API 端点"""
    print_section("检查 API 端点")

    try:
        from app import app

        # 检查路由
        routes = []
        for rule in app.url_map.iter_rules():
            routes.append(f"{rule.methods} {rule.rule}")

        print_success(f"应用已注册 {len(routes)} 个路由")

        # 列出主要路由
        main_routes = [
            "/api/images",
            "/api/labels",
            "/api/airlines",
            "/api/aircraft-types",
            "/api/ai/status",
            "/api/stats",
        ]

        for route in main_routes:
            if any(route in r for r in routes):
                print_success(f"路由存在: {route}")
            else:
                print_error(f"路由不存在: {route}")

        return True

    except Exception as e:
        print_error(f"API 检查失败: {e}")
        traceback.print_exc()
        return False


def check_ocr_service():
    """检查 OCR 服务"""
    print_section("检查 OCR 服务")

    ocr_url = os.getenv("OCR_API_URL", "http://localhost:8000/v2/models/ocr/infer")
    print_info(f"OCR API URL: {ocr_url}")

    try:
        import requests

        # 尝试连接
        print_info("正在尝试连接 OCR 服务...")
        try:
            response = requests.get(ocr_url.replace("/infer", "/health"), timeout=5)
            if response.status_code == 200:
                print_success("OCR 服务健康检查通过")
                return True
            else:
                print_warning(f"OCR 服务响应异常: {response.status_code}")
        except:
            # 如果没有健康检查端点，尝试发送一个简单的测试请求
            print_warning("OCR 服务没有健康检查端点，跳过连接测试")

        return True

    except Exception as e:
        print_warning(f"OCR 服务检查失败: {e}")
        return True  # OCR 不可选，不影响主要功能


def check_dependencies():
    """检查依赖包"""
    print_section("检查依赖包")

    packages = {
        "flask": "Flask",
        "flask_cors": "Flask-CORS",
        "requests": "Requests",
        "yaml": "PyYAML",
        "cv2": "OpenCV",
        "numpy": "NumPy",
        "PIL": "Pillow",
        "ultralytics": "Ultralytics",
        "hdbscan": "HDBSCAN",
    }

    missing_packages = []
    for module, name in packages.items():
        try:
            __import__(module)
            print_success(f"{name} 已安装")
        except ImportError:
            print_error(f"{name} 未安装")
            missing_packages.append(name)

    if missing_packages:
        print_warning(f"缺少 {len(missing_packages)} 个依赖包")
        return False
    else:
        return True


def check_environment_variables():
    """检查环境变量"""
    print_section("检查环境变量")

    env_vars = {
        "DATABASE_PATH": "./labels.db",
        "IMAGES_DIR": "./images",
        "LABELED_DIR": "./labeled",
        "AI_CONFIG_PATH": "./config.yaml",
        "OCR_API_URL": "http://localhost:8000/v2/models/ocr/infer",
    }

    for var, default in env_vars.items():
        value = os.getenv(var, default)
        print_info(f"{var} = {value}")


def main():
    parser = argparse.ArgumentParser(description="故障排除脚本")
    parser.add_argument(
        "--check",
        choices=["all", "config", "db", "dirs", "models", "api", "ocr", "deps", "env"],
        default="all",
        help="要检查的项目",
    )

    args = parser.parse_args()

    print_header("AeroVision Label System - 故障排除")

    results = {}

    if args.check in ["all", "config"]:
        results["config"] = check_config_files()

    if args.check in ["all", "env"]:
        check_environment_variables()

    if args.check in ["all", "deps"]:
        results["dependencies"] = check_dependencies()

    if args.check in ["all", "db"]:
        results["database"] = check_database()

    if args.check in ["all", "dirs"]:
        results["directories"] = check_directories()

    if args.check in ["all", "models"]:
        results["models"] = check_models_loading()

    if args.check in ["all", "api"]:
        results["api"] = check_api_endpoints()

    if args.check in ["all", "ocr"]:
        check_ocr_service()

    # 总结
    print_header("总结")

    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)

    for name, status in results.items():
        if status:
            print_success(f"{name}: 通过")
        else:
            print_error(f"{name}: 失败")

    if failed == 0:
        print_success(f"\n所有检查通过！")
        return 0
    else:
        print_error(f"\n{failed} 项检查失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
