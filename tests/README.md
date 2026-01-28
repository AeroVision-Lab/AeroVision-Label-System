# 测试目录

本目录包含 AeroVision Label System 的所有测试相关文件。

## 目录结构

```
tests/
├── __init__.py                  # 测试包
├── conftest.py                  # Pytest fixtures（共享）
├── pytest.ini                    # Pytest 配置
├── TESTING.md                    # 详细测试文档
│
├── unit/                        # 单元测试（隔离测试）
│   ├── __init__.py
│   ├── test_database.py          # 数据库测试
│   ├── test_api.py               # API 测试
│   └── test_ai_models.py        # AI 模型测试
│
├── integration/                  # 集成测试（真实服务）
│   ├── __init__.py
│   └── test_integration.py       # AI 集成测试
│
└── scripts/                     # 测试工具脚本
    ├── __init__.py
    ├── health_check.py           # 健康检查
    ├── troubleshoot.py          # 故障排除
    └── run_tests.py            # 测试运行器
```

## 快速开始

### 1. 运行所有测试

```bash
pytest
```

### 2. 运行特定类型的测试

```bash
# 只运行单元测试
pytest tests/unit/

# 只运行集成测试
pytest tests/integration/

# 只运行数据库测试
pytest tests/unit/test_database.py

# 只运行 API 测试
pytest tests/unit/test_api.py
```

### 3. 使用测试脚本

```bash
# 健康检查
python tests/scripts/health_check.py

# 故障排除
python tests/scripts/troubleshoot.py

# 使用测试运行器
python tests/scripts/run_tests.py --fast
```

## 测试类型

### 单元测试 (unit/)
- 使用 mock 和临时资源
- 不依赖外部服务
- 快速执行
- 适合 CI/CD

### 集成测试 (integration/)
- 使用真实服务
- 测试完整工作流
- 需要真实模型和图片
- 较慢但更真实

## 详细文档

查看 [TESTING.md](TESTING.md) 获取详细的测试文档和使用说明。

## 标记说明

测试使用 pytest 标记进行分类：

- `@pytest.mark.unit` - 单元测试
- `@pytest.mark.integration` - 集成测试
- `@pytest.mark.slow` - 慢速测试
- `@pytest.mark.ai` - AI 相关测试
- `@pytest.mark.db` - 数据库测试
- `@pytest.mark.api` - API 测试

使用标记过滤测试：

```bash
# 只运行单元测试
pytest -m unit

# 只运行快速测试
pytest -m "not slow"

# 只运行 AI 测试
pytest -m ai
```

## 故障排除

如果测试失败：

1. 运行健康检查
   ```bash
   python tests/scripts/health_check.py
   ```

2. 运行故障排除脚本
   ```bash
   python tests/scripts/troubleshoot.py
   ```

3. 查看详细错误信息
   ```bash
   pytest -v --tb=long
   ```
