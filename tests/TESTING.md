# 测试文档

本文档说明如何使用测试系统来快速定位问题，隔离模型推理、前端和数据库。

## 快速开始

### 1. 安装测试依赖

```bash
pip install pytest pytest-cov pytest-mock
```

### 2. 运行所有测试

```bash
python tests/scripts/run_tests.py
```

### 3. 快速检查系统健康

```bash
python tests/scripts/health_check.py
```

### 4. 故障排除

```bash
python tests/scripts/troubleshoot.py
```

## 测试架构

### 单元测试（隔离测试）

单元测试使用 mock 和临时资源，不依赖外部服务，可以快速运行并定位问题。

#### 测试文件

- **test_database.py** - 数据库操作测试
  - 使用临时数据库
  - 测试 CRUD 操作
  - 测试锁机制
  - 测试 AI 预测数据管理

- **test_api.py** - API 端点测试
  - 使用 mock 隔离 AI 服务
  - 测试所有 API 端点
  - 测试错误处理

- **test_ai_models.py** - AI 模型测试
  - 使用 mock 避免真实模型加载
  - 测试模型接口
  - 测试 OCR、质量评估、HDBSCAN

### 集成测试

- **test_integration.py** - AI 集成测试
  - 测试真实 AI 服务
  - 测试完整工作流
  - 需要真实图片和模型

## 快速定位问题

### 问题 1: 模型调用失败

#### 步骤 1: 检查模型文件

```bash
python tests/scripts/health_check.py --component ai
```

#### 步骤 2: 检查配置文件

```bash
python tests/scripts/troubleshoot.py --check config
```

#### 步骤 3: 运行 AI 模型测试

```bash
python tests/scripts/run_tests.py --unit
# 运行 test_ai_models.py 中的测试
```

#### 步骤 4: 查看详细错误

```bash
pytesttest_ai_models.py -v -s
```

### 问题 2: 数据库问题

#### 步骤 1: 检查数据库

```bash
python tests/scripts/health_check.py --component db
```

#### 步骤 2: 运行数据库测试

```bash
pytesttest_database.py -v
```

#### 步骤 3: 检查数据完整性

```bash
python tests/scripts/troubleshoot.py --check db
```

### 问题 3: API 问题

#### 步骤 1: 检查 API 端点

```bash
python tests/scripts/troubleshoot.py --check api
```

#### 步骤 2: 运行 API 测试

```bash
pytesttest_api.py -v
```

#### 步骤 3: 测试特定端点

```bash
pytesttest_api.py::TestAPI::test_get_airlines -v
```

### 问题 4: OCR 服务问题

#### 步骤 1: 检查 OCR 服务

```bash
python tests/scripts/health_check.py --component ocr
```

#### 步骤 2: 测试 OCR 接口

```bash
pytesttest_ai_models.py::TestOCRService -v
```

## 测试隔离

### 隔离数据库

测试使用临时数据库，不影响生产数据：

```python
@pytest.fixture
def temp_db():
    """创建临时数据库"""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    db = Database(db_path)
    yield db, db_path
    
    os.unlink(db_path)
```

### 隔离 AI 模型

使用 mock 避免真实模型加载：

```python
@patch('ai_service.predictor.YOLO')
def test_load_models(self, mock_yolo):
    mock_aircraft_model = MagicMock()
    mock_yolo.return_value = mock_aircraft_model
    
    predictor = ModelPredictor(config)
    predictor.load_models()
```

### 隔离 API

使用 mock 隔离外部依赖：

```python
@patch('app.ai_predictor')
def test_ai_predict_single(self, mock_predictor):
    mock_predictor.predict_single.return_value = {...}
    # 测试逻辑
```

## 测试命令

### 基本命令

```bash
# 运行所有测试
pytest

# 运行特定测试文件
pytesttest_database.py

# 运行特定测试类
pytesttest_api.py::TestAPI

# 运行特定测试函数
pytesttest_api.py::TestAPI::test_get_airlines

# 显示详细输出
pytest -v

# 显示打印输出
pytest -s

# 只运行失败的测试
pytest --lf

# 停在第一个失败
pytest -x
```

### 标记过滤

```bash
# 只运行快速测试
pytest -m "not slow"

# 只运行单元测试
pytest -m unit

# 只运行集成测试
pytest -m integration

# 只运行 AI 测试
pytest -m ai
```

### 覆盖率报告

```bash
# 生成 HTML 覆盖率报告
pytest --cov=. --cov-report=html

# 在终端显示覆盖率
pytest --cov=. --cov-report=term

# 使用运行脚本
python tests/scripts/run_tests.py --coverage
```

## 测试标记

- `@pytest.mark.slow` - 标记慢速测试（如加载模型）
- `@pytest.mark.integration` - 标记集成测试
- `@pytest.mark.unit` - 标记单元测试
- `@pytest.mark.ai` - 标记 AI 相关测试
- `@pytest.mark.db` - 标记数据库测试
- `@pytest.mark.api` - 标记 API 测试

## 持续集成

### 在 CI 中运行测试

```bash
# 快速检查（不加载真实模型）
python tests/scripts/run_tests.py --fast --coverage

# 完整测试（包括集成测试）
python tests/scripts/run_tests.py --coverage
```

### 健康检查脚本

健康检查脚本可以快速定位问题：

```bash
# 检查所有组件
python tests/scripts/health_check.py

# 只检查数据库
python tests/scripts/health_check.py --component db

# 只检查 AI 模型
python tests/scripts/health_check.py --component ai

# 只检查目录
python tests/scripts/health_check.py --component dirs

# 只检查依赖
python tests/scripts/health_check.py --component deps

# 只检查 OCR 服务
python tests/scripts/health_check.py --component ocr
```

### 故障排除脚本

故障排除脚本提供更详细的诊断：

```bash
# 运行所有检查
python tests/scripts/troubleshoot.py

# 只检查配置
python tests/scripts/troubleshoot.py --check config

# 只检查数据库
python tests/scripts/troubleshoot.py --check db

# 只检查模型
python tests/scripts/troubleshoot.py --check models

# 只检查 API
python tests/scripts/troubleshoot.py --check api
```

## 测试最佳实践

### 1. 使用 fixture 管理测试资源

```python
@pytest.fixture
def temp_db():
    db = create_temp_db()
    yield db
    cleanup_temp_db(db)
```

### 2. 使用 mock 隔离外部依赖

```python
@patch('module.external_service')
def test_something(mock_service):
    mock_service.return_value = expected_value
    # 测试逻辑
```

### 3. 保持测试独立

每个测试应该可以独立运行，不依赖其他测试的状态。

### 4. 使用描述性名称

```python
def test_add_airline_with_valid_data(self):
    def test_add_airline_with_duplicate_code_raises_error(self):
```

### 5. 测试边界情况

```python
def test_skip_image_when_not_exists(self):
def test_skip_image_already_skipped(self):
```

## 调试测试

### 打印调试信息

```bash
pytest -s -v tests/test_api.py::TestAPI::test_get_airlines
```

### 进入调试器

```python
def test_something(self):
    import pdb; pdb.set_trace()
    # 或
    breakpoint()
```

### 查看测试输出

```bash
pytest -v --tb=long
```

## 常见问题

### Q: 测试失败，但本地运行正常

A: 检查环境变量、数据库路径、模型路径是否配置正确。

### Q: 如何测试真实 AI 模型？

A: 运行集成测试：
```bash
pytesttest_integration.py -v
```

### Q: 如何跳过慢速测试？

A: 使用标记过滤：
```bash
pytest -m "not slow"
```

### Q: 如何生成覆盖率报告？

A: 使用覆盖率选项：
```bash
pytest --cov=. --cov-report=html
```

## 总结

通过这套测试系统，你可以：

1. **快速定位问题** - 使用 health_check.py 和 troubleshoot.py
2. **隔离测试** - 单元测试使用 mock 和临时资源
3. **不依赖 docker** - 直接运行测试即可发现问题
4. **持续集成** - 完善的测试覆盖率和 CI 支持

开始测试：

```bash
# 1. 运行健康检查
python tests/scripts/health_check.py

# 2. 运行测试
python tests/scripts/run_tests.py

# 3. 如果有问题，运行故障排除
python tests/scripts/troubleshoot.py
```
