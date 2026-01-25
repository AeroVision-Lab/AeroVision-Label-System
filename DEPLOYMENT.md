# AI预测与复审功能 - 部署指南

## 功能概述

本更新为AeroVision标注系统添加了以下AI辅助功能：

1. **AI自动预测**：自动对新增图片进行机型、航司分类，OCR识别注册号，以及质量评估
2. **新类别检测**：使用HDBSCAN聚类算法检测潜在的飞机新类别
3. **AI复审界面**：提供专门的复审页面，分模块展示AI预测结果
4. **智能推送**：按照置信度由低到高、新类别优先的顺序推送图片
5. **一键通过**：对置信度≥95%且非新类的图片提供一键批量批准功能

## 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                        前端 (Vue.js)                       │
├─────────────────────────────────────────────────────────┤
│  标注页  │  AI复审页  │  已标注  │  统计              │
└────────────┬────────────────────────────────────────────┘
             │ REST API
┌────────────▼────────────────────────────────────────────┐
│                   后端 (Flask)                            │
├─────────────────────────────────────────────────────────┤
│  图片API  │  标注API  │  锁API  │  AI预测API           │
└────────────┬────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────┐
│              AI预测服务 (AIPredictor)                    │
├─────────────────────────────────────────────────────────┤
│  ModelPredictor  │  OCR  │  Quality  │  HDBSCAN         │
│  (机型/航司分类)  │ (注册号)│ (质量评估)│ (新类别检测)      │
└────────────┬────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────┐
│                   模型文件                                │
│  YOLOv8-cls-aircraft.pt                                  │
│  YOLOv8-cls-airline.pt                                   │
└─────────────────────────────────────────────────────────┘
```

## 数据库Schema变更

### labels表新增字段
- `review_status`: TEXT - 复审状态（'pending', 'approved', 'rejected', 'auto_approved', 'reviewed'）
- `ai_approved`: INTEGER - 是否由AI自动批准（0/1）

### 新增ai_predictions表
```sql
CREATE TABLE ai_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL UNIQUE,
    aircraft_class TEXT NOT NULL,
    aircraft_confidence REAL NOT NULL,
    airline_class TEXT NOT NULL,
    airline_confidence REAL NOT NULL,
    registration TEXT,
    registration_area TEXT,
    registration_confidence REAL DEFAULT 0.0,
    clarity REAL DEFAULT 0.0,
    block REAL DEFAULT 0.0,
    quality_confidence REAL DEFAULT 0.0,
    is_new_class INTEGER DEFAULT 0,
    outlier_score REAL DEFAULT 0.0,
    prediction_time REAL NOT NULL,
    processed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

## 部署步骤

### 1. 前置准备

#### 1.1 安装nvidia-docker（如果使用GPU）
```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update && sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

#### 1.2 确保模型文件存在
模型文件应位于：`/home/wlx/yolo26x-cls-aircraft.pt` 和 `/home/wlx/yolo26x-cls-airline.pt`

### 2. 配置文件修改

#### 2.1 更新config.yaml
```yaml
models:
  aircraft:
    path: /app/models/yolo26x-cls-aircraft.pt  # 修改为容器内路径
    device: cuda
    image_size: 640
  airline:
    path: /app/models/yolo26x-cls-airline.pt   # 修改为容器内路径
    device: cuda
    image_size: 640
```

#### 2.2 配置环境变量
创建`.env`文件（参考`.env.example`）：
```bash
cp .env.example .env
# 编辑.env，设置GLM_API_KEY（可选，用于质量评估）
```

### 3. 数据库迁移

运行迁移脚本以更新现有数据：
```bash
cd /home/wlx/AeroVision-Label-System
python scripts/migrate_db.py
```

这将：
- 添加`review_status`和`ai_approved`字段到`labels`表
- 创建`ai_predictions`表
- 将现有标注记录的`review_status`设置为`'reviewed'`

### 4. 构建和部署

#### 4.1 停止现有容器
```bash
cd /home/wlx/AeroVision-Label-System
docker-compose down
```

#### 4.2 重新构建镜像
```bash
docker-compose build
```

注意：首次构建可能需要较长时间，因为需要安装所有AI依赖包。

#### 4.3 启动容器
```bash
docker-compose up -d
```

#### 4.4 查看日志
```bash
docker-compose logs -f
```

### 5. 验证部署

#### 5.1 检查AI服务状态
访问：`http://your-domain/api/ai/status`

预期响应：
```json
{
  "enabled": true,
  "config": { ... },
  "services": {
    "ocr": true,
    "quality": true,
    "hdbscan": true
  }
}
```

#### 5.2 测试批量预测
```bash
curl -X POST http://your-domain/api/ai/predict-batch
```

#### 5.3 访问AI复审页面
在浏览器中访问系统，点击"AI复审"标签页。

## 配置说明

### config.yaml配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `models.aircraft.path` | 机型分类模型路径 | `/home/wlx/yolo26x-cls-aircraft.pt` |
| `models.airline.path` | 航司分类模型路径 | `/home/wlx/yolo26x-cls-airline.pt` |
| `models.aircraft.device` | 计算设备 | `cuda` |
| `ocr.enabled` | 是否启用OCR | `true` |
| `quality_assessor.enabled` | 是否启用质量评估 | `true` |
| `hdbscan.enabled` | 是否启用新类别检测 | `true` |
| `thresholds.high_confidence` | 高置信度阈值 | `0.95` |
| `thresholds.low_confidence` | 低置信度阈值 | `0.80` |

### 环境变量

| 环境变量 | 说明 | 必需 |
|----------|------|------|
| `GLM_API_KEY` | 智谱AI API密钥（质量评估） | 否 |
| `AI_CONFIG_PATH` | AI配置文件路径 | 否（默认`./config.yaml`） |

## 使用指南

### 自动预测流程

系统会自动检测新图片并运行AI预测：
1. 将图片上传到`/mnt/disk/AeroVision/images/`目录
2. 系统自动检测新图片
3. 调用AI预测服务进行分类、OCR和质量评估
4. 预测结果保存到`ai_predictions`表
5. 在"AI复审"页面按优先级显示待复审图片

### AI复审流程

1. **访问复审页面**：点击"AI复审"标签页
2. **查看预测结果**：系统按优先级推送图片
   - 新类别优先显示
   - 常规类别按置信度低到高排序
3. **分模块审查**：
   - 机型：查看分类结果和置信度
   - 航司：查看分类结果和置信度
   - OCR：查看识别的注册号
   - 质量：查看清晰度和遮挡度评分
4. **操作选择**：
   - 一键通过：仅对置信度≥95%且非新类的图片显示
   - 批准：接受AI预测，创建标注
   - 拒绝：拒绝AI预测，不创建标注
   - 标记为废图：拒绝预测并将图片标记为废图

### 批量一键通过

当待复审列表中只剩下置信度≥95%且非新类的图片时，会出现"一键通过全部"按钮，可以批量批准所有符合条件的图片。

## 故障排查

### 问题1：AI服务未启用

**症状**：访问`/api/ai/status`返回`enabled: false`

**解决方案**：
1. 检查Docker日志：`docker-compose logs aerovision-backend`
2. 确认模型文件存在且路径正确
3. 检查GPU是否可用：`nvidia-smi`
4. 查看错误信息，通常是因为模型文件缺失或初始化失败

### 问题2：质量评估失败

**症状**：质量评估结果为默认值或报错

**解决方案**：
1. 确认`GLM_API_KEY`环境变量已设置
2. 验证API密钥有效性
3. 如果不需要质量评估，可在`config.yaml`中设置`quality_assessor.enabled: false`

### 问题3：OCR识别失败

**症状**：OCR结果为空或报错

**解决方案**：
1. 检查图片质量是否足够清晰
2. 确认PaddleOCR已正确安装
3. 如果不需要OCR，可在`config.yaml`中设置`ocr.enabled: false`

### 问题4：内存不足

**症状**：容器因OOM被杀死

**解决方案**：
1. 增加Docker内存限制
2. 在`config.yaml`中减小`batch_size`或`num_workers`
3. 如果使用质量评估，该服务消耗较多内存，考虑禁用

## 性能优化

### GPU使用

确保容器能够访问GPU：
```bash
docker run --gpus all ...
```

或修改`docker-compose.yaml`中的GPU配置。

### 批处理

对于大量图片，可以在`config.yaml`中调整批处理参数：
```yaml
auto_annotate:
  batch_size: 32  # 增大批处理大小
  num_workers: 4  # 增加工作线程
```

### 模型优化

如果推理速度较慢，可以考虑：
1. 使用TensorRT加速（需重新导出模型）
2. 减小模型尺寸
3. 使用FP16精度推理

## 测试

运行集成测试：
```bash
cd /home/wlx/AeroVision-Label-System
pip install pytest
pytest tests/test_integration.py -v -s
```

注意：集成测试需要真实的模型文件和图片。

## 维护

### 定期清理

清理已处理的AI预测记录：
```sql
DELETE FROM ai_predictions WHERE processed = 1 AND created_at < datetime('now', '-30 days');
```

### 监控

建议监控以下指标：
- AI预测成功/失败率
- 平均预测时间
- 复审通过率
- 新类别检测数量

## 回滚

如果需要回滚到旧版本：
```bash
cd /home/wlx/AeroVision-Label-System
git checkout <previous-version-tag>
docker-compose down
docker-compose build
docker-compose up -d
```

数据库Schema变更是向后兼容的，无需额外操作。
