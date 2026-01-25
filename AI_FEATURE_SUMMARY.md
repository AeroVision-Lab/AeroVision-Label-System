# AI预测与复审功能 - 实施总结

## 实施日期
2025年1月24日

## 实施范围

本次更新为AeroVision标注系统添加了完整的AI辅助功能，包括：

1. **AI自动预测**
   - 机型分类（YOLOv8-cls）
   - 航司分类（YOLOv8-cls）
   - OCR注册号识别（PaddleOCR）
   - 图像质量评估（GLM-4V VLM）
   - 新类别检测（HDBSCAN聚类）

2. **AI复审界面**
   - 分模块展示预测结果
   - 智能推送排序（新类别优先，置信度升序）
   - 一键通过功能（置信度≥95%且非新类）
   - 批量操作支持

3. **自动化流程**
   - 新图片自动触发AI预测
   - 预测结果自动保存
   - 审批后自动创建标注并移动文件

## 文件变更清单

### 新增文件

#### 配置文件
- `config.yaml` - AI服务配置文件
- `.env.example` - 环境变量模板

#### AI服务模块（`ai_service/`）
- `ai_service/__init__.py` - 模块初始化
- `ai_service/predictor.py` - 分类器预测服务
- `ai_service/ocr_service.py` - OCR识别服务
- `ai_service/quality_service.py` - 质量评估服务
- `ai_service/hdbscan_service.py` - 新类别检测服务
- `ai_service/ai_predictor.py` - 统一AI预测接口

#### 前端组件
- `frontend/src/components/ReviewPanel.vue` - AI复审页面

#### 后端API扩展
- `app.py` - 新增10+个AI相关API端点

#### 脚本和测试
- `scripts/migrate_db.py` - 数据库迁移脚本
- `tests/test_integration.py` - 集成测试套件

#### 文档
- `DEPLOYMENT.md` - 详细部署指南
- `AI_FEATURE_SUMMARY.md` - 本文件

### 修改文件

#### 后端
- `database.py` - 新增AI预测相关方法和数据库表结构
- `requirements.txt` - 添加AI依赖包
- `app.py` - 集成AI预测服务和新增API

#### 前端
- `frontend/src/App.vue` - 新增AI复审标签页

#### 部署配置
- `Dockerfile` - 更新依赖和配置
- `docker-compose.yaml` - 添加GPU支持和环境变量

## 数据库变更

### labels表
新增字段：
- `review_status` TEXT DEFAULT 'pending' - 复审状态
- `ai_approved` INTEGER DEFAULT 0 - 是否AI自动批准

### ai_predictions表（新增）
存储AI预测结果，包含：
- 分类结果和置信度（机型、航司）
- OCR识别结果（注册号、区域、置信度）
- 质量评估结果（清晰度、遮挡度、置信度）
- 新类别检测标记（is_new_class、outlier_score）
- 处理状态和时间戳

## API端点

### AI服务状态
- `GET /api/ai/status` - 获取AI服务状态

### AI预测
- `POST /api/ai/predict` - 单张图片预测
- `POST /api/ai/predict-batch` - 批量预测（自动触发）

### AI复审
- `GET /api/ai/review/pending` - 获取待复审列表（按优先级排序）
- `GET /api/ai/review/auto-approvable` - 获取可一键通过的预测
- `POST /api/ai/review/approve` - 批准单个预测
- `POST /api/ai/review/bulk-approve` - 批量批准预测
- `POST /api/ai/review/reject` - 拒绝预测

### 统计
- `GET /api/ai/stats` - 获取AI复审统计信息

## 配置项

### config.yaml
```yaml
models:
  aircraft:
    path: /app/models/yolo26x-cls-aircraft.pt
    device: cuda
    image_size: 640
  airline:
    path: /app/models/yolo26x-cls-airline.pt
    device: cuda
    image_size: 640

ocr:
  enabled: true
  lang: ch
  use_angle_cls: true

quality_assessor:
  enabled: true
  api_key: ""  # 通过环境变量设置
  api_url: "https://open.bigmodel.cn/api/paas/v4/chat/completions"
  model: "glm-4.6v"

hdbscan:
  enabled: true
  min_cluster_size: 5
  min_samples: 3

thresholds:
  high_confidence: 0.95
  low_confidence: 0.80

auto_annotate:
  enabled: true
  auto_trigger: true
  batch_size: 32
```

### 环境变量
- `GLM_API_KEY` - 智谱AI API密钥（质量评估，可选）
- `AI_CONFIG_PATH` - AI配置文件路径（默认`./config.yaml`）

## 推送逻辑

### 优先级排序
1. **新类别**（`is_new_class=1`）：优先推送，按`outlier_score`降序排列
2. **常规类别**（`is_new_class=0`）：按置信度升序排列（低置信度优先）

### 一键通过条件
- `is_new_class = 0`（非新类别）
- `aircraft_confidence >= 0.95`
- `airline_confidence >= 0.95`

满足以上条件的图片会：
1. 在单个图片复审时显示"一键通过"按钮
2. 当所有待复审图片都满足条件时，显示"一键通过全部"按钮

## 依赖项

### 新增Python包
```
pyyaml>=6.0.0
numpy>=1.24.0
opencv-python>=4.8.0
pillow>=10.0.0
paddleocr>=2.7.0
paddlepaddle>=2.6.0
ultralytics>=8.0.0
torch>=2.0.0
torchvision>=0.15.0
hdbscan>=0.8.0
zhipuai>=2.0.0
```

### 系统依赖
- NVIDIA GPU（推荐，用于推理加速）
- CUDA Toolkit（如果使用GPU）
- nvidia-docker（如果使用GPU容器）

## 部署检查清单

- [ ] 模型文件存在（`yolo26x-cls-aircraft.pt`, `yolo26x-cls-airline.pt`）
- [ ] Docker配置正确（GPU支持、卷挂载）
- [ ] `config.yaml`已正确配置
- [ ] 环境变量已设置（`.env`文件）
- [ ] 数据库迁移已完成
- [ ] 容器已重新构建并启动
- [ ] AI服务状态正常（`/api/ai/status`）
- [ ] 批量预测功能正常
- [ ] 前端AI复审页面可访问
- [ ] 测试图片上传和预测

## 测试覆盖

### 集成测试（`tests/test_integration.py`）
- ✅ AI服务状态检查
- ✅ 单张图片预测
- ✅ 批量预测
- ✅ 获取待复审列表
- ✅ 获取可一键通过的预测
- ✅ AI统计信息
- ✅ 批准AI预测
- ✅ 拒绝AI预测
- ✅ 完整工作流测试
- ✅ 推送顺序优先级测试

### 手动测试建议
1. 上传5-10张测试图片到`images/`目录
2. 调用批量预测API
3. 访问AI复审页面，检查：
   - 图片按正确顺序显示
   - 每个模块的预测结果正确
   - 一键通过功能正常
   - 批准/拒绝操作正常
4. 检查已标注目录，验证文件已正确移动

## 已知限制

1. **质量评估依赖外部API**
   - 使用智谱AI的GLM-4V API
   - 需要有效的API密钥
   - 如果API不可用，质量评估将返回默认值

2. **新类别检测准确性**
   - HDBSCAN的检测准确性取决于参数配置
   - 默认参数可能需要根据实际数据调整
   - 建议定期审查被标记为新类别的图片

3. **资源消耗**
   - AI预测服务消耗较多内存和GPU资源
   - 建议在具有足够资源的机器上运行
   - 批量预测时建议监控资源使用情况

4. **OCR识别**
   - PaddleOCR对模糊或低分辨率图片的识别效果可能不佳
   - 可以通过调整图片预处理或使用更强大的OCR模型来改善

## 后续优化建议

1. **性能优化**
   - 实现TensorRT加速
   - 使用模型量化和剪枝
   - 优化批处理大小和工作线程数

2. **功能增强**
   - 添加更多质量评估维度（角度、光照等）
   - 支持自定义新类别检测阈值
   - 添加预测结果导出功能

3. **用户体验**
   - 添加预测历史记录查看
   - 支持预测结果的批量编辑
   - 添加预测置信度分布可视化

4. **监控和日志**
   - 添加详细的AI预测日志
   - 实现预测性能指标监控
   - 添加异常检测和告警

## 回滚计划

如果需要回滚到无AI功能的版本：

1. 停止并移除容器：`docker-compose down`
2. 恢复之前的代码：`git checkout <previous-version>`
3. 重新构建并启动：`docker-compose up -d`

数据库Schema是向后兼容的，无需回滚数据库。

## 支持和反馈

如有问题或建议，请参考：
- 部署指南：`DEPLOYMENT.md`
- 问题排查：部署文档中的"故障排查"章节
- API文档：通过Swagger或直接查看`app.py`注释

## 版本信息

- 实施版本：v2.0.0
- 基础版本：v1.0.0
- 实施日期：2025年1月24日

---

**注意事项**：
1. 首次部署时，AI模型加载可能需要几分钟
2. 质量评估功能需要API密钥，如不需要可在配置中禁用
3. 建议定期备份数据库，特别是`ai_predictions`表
4. 生产环境部署前建议在测试环境充分验证
