"""
测试运行脚本
提供便捷的测试运行命令

用法:
    python run_tests.py                    # 运行所有测试
    python run_tests.py --unit             # 只运行单元测试
    python run_tests.py --integration      # 只运行集成测试
    python run_tests.py --fast             # 快速测试（跳过耗时的测试）
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """运行命令并输出结果"""
    print(f"\n{'=' * 60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 60)

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print(f"\n✓ {description} passed")
    else:
        print(f"\n✗ {description} failed")

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="测试运行脚本")
    parser.add_argument("--unit", action="store_true", help="只运行单元测试")
    parser.add_argument("--integration", action="store_true", help="只运行集成测试")
    parser.add_argument(
        "--fast", action="store_true", help="快速测试（跳过耗时的测试）"
    )
    parser.add_argument("--coverage", action="store_true", help="生成覆盖率报告")

    args = parser.parse_args()

    # 基础 pytest 参数（从tests/目录运行）
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    pytest_args = ["pytest", "-v", "--tb=short"]

    if args.fast:
        pytest_args.extend(["-m", "not slow"])

    if args.coverage:
        pytest_args.extend(["--cov=..", "--cov-report=html", "--cov-report=term"])

    all_passed = True

    if args.unit:
        # 运行单元测试
        unit_tests = [
            "unit/test_database.py",
            "unit/test_api.py",
            "unit/test_ai_models.py",
        ]
        cmd = pytest_args + unit_tests
        passed = run_command(cmd, "Unit Tests")
        all_passed = all_passed and passed

    elif args.integration:
        # 运行集成测试
        cmd = pytest_args + ["integration/test_integration.py"]
        passed = run_command(cmd, "Integration Tests")
        all_passed = all_passed and passed

    else:
        # 运行所有测试
        cmd = pytest_args
        passed = run_command(cmd, "All Tests")
        all_passed = all_passed and passed

    print(f"\n{'=' * 60}")
    if all_passed:
        print("✓ All tests passed!")
        print("=" * 60)
        return 0
    else:
        print("✗ Some tests failed!")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
