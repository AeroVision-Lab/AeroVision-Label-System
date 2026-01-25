<template>
  <div class="review-panel">
    <!-- 头部统计 -->
    <div class="review-header">
      <div class="stats-grid">
        <div class="stat-item">
          <div class="stat-label">待复审</div>
          <div class="stat-value">{{ stats.pending_count }}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">新类别</div>
          <div class="stat-value new-class">{{ stats.new_class_count }}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">可一键通过</div>
          <div class="stat-value auto-approve">{{ stats.auto_approve_count }}</div>
        </div>
      </div>
      <div class="header-actions">
        <button
          v-if="showAutoApproveButton"
          class="auto-approve-btn"
          @click="handleBulkAutoApprove"
        >
          一键通过全部 ({{ stats.auto_approve_count }} 张)
        </button>
        <button class="refresh-btn" @click="loadData" :disabled="loading">
          {{ loading ? '加载中...' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 主内容区 -->
    <div v-if="loading" class="loading">
      加载中...
    </div>

    <div v-else-if="!currentPrediction" class="no-predictions">
      <div class="empty-icon">✓</div>
      <h2>没有待复审的预测</h2>
      <p>所有AI预测已处理完成</p>
    </div>

    <div v-else class="review-content">
      <!-- 左侧：图片 -->
      <div class="image-section">
        <div class="image-info">
          <span class="filename">{{ currentPrediction.filename }}</span>
          <span class="index">{{ currentIndex + 1 }} / {{ predictions.length }}</span>
        </div>
        <div class="image-container">
          <img :src="getImageUrl(currentPrediction.filename)" :alt="currentPrediction.filename" />
        </div>
      </div>

      <!-- 右侧：复审表单 -->
      <div class="form-section">
        <h3>AI预测结果</h3>

        <!-- 模块1：机型分类 -->
        <div class="review-module">
          <div class="module-header">
            <span class="module-title">机型</span>
            <span class="module-confidence" :class="getConfidenceClass(currentPrediction.aircraft_confidence)">
              {{ (currentPrediction.aircraft_confidence * 100).toFixed(1) }}%
            </span>
          </div>
          <div class="module-content">
            <div class="prediction-result">
              <span class="result-label">预测:</span>
              <span class="result-value">{{ currentPrediction.aircraft_class }}</span>
            </div>
            <div class="confidence-indicator">
              <div class="confidence-bar">
                <div
                  class="confidence-fill"
                  :style="{ width: (currentPrediction.aircraft_confidence * 100) + '%' }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <!-- 模块2：航司分类 -->
        <div class="review-module">
          <div class="module-header">
            <span class="module-title">航司</span>
            <span class="module-confidence" :class="getConfidenceClass(currentPrediction.airline_confidence)">
              {{ (currentPrediction.airline_confidence * 100).toFixed(1) }}%
            </span>
          </div>
          <div class="module-content">
            <div class="prediction-result">
              <span class="result-label">预测:</span>
              <span class="result-value">{{ currentPrediction.airline_class }}</span>
            </div>
            <div class="confidence-indicator">
              <div class="confidence-bar">
                <div
                  class="confidence-fill"
                  :style="{ width: (currentPrediction.airline_confidence * 100) + '%' }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <!-- 模块3：OCR识别 -->
        <div class="review-module">
          <div class="module-header">
            <span class="module-title">OCR注册号</span>
            <span class="module-status" :class="{ has_result: !!currentPrediction.registration }">
              {{ currentPrediction.registration ? '已识别' : '未识别' }}
            </span>
          </div>
          <div class="module-content">
            <div class="prediction-result">
              <span class="result-label">识别:</span>
              <span class="result-value">{{ currentPrediction.registration || '-' }}</span>
            </div>
            <div v-if="currentPrediction.registration" class="ocr-details">
              <span class="detail-label">置信度:</span>
              <span class="detail-value">{{ (currentPrediction.registration_confidence * 100).toFixed(1) }}%</span>
            </div>
          </div>
        </div>

        <!-- 模块4：质量评估 -->
        <div class="review-module">
          <div class="module-header">
            <span class="module-title">质量评估</span>
          </div>
          <div class="module-content">
            <div class="quality-item">
              <span class="quality-label">清晰度:</span>
              <span class="quality-value">{{ currentPrediction.clarity.toFixed(2) }}</span>
              <div class="quality-bar">
                <div
                  class="quality-fill"
                  :style="{ width: (currentPrediction.clarity * 100) + '%' }"
                ></div>
              </div>
            </div>
            <div class="quality-item">
              <span class="quality-label">遮挡度:</span>
              <span class="quality-value">{{ currentPrediction.block.toFixed(2) }}</span>
              <div class="quality-bar">
                <div
                  class="quality-fill"
                  :style="{ width: (currentPrediction.block * 100) + '%' }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <!-- 新类别标记 -->
        <div v-if="currentPrediction.is_new_class" class="new-class-badge">
          ⚠️ 检测到新类别 (异常分: {{ currentPrediction.outlier_score.toFixed(3) }})
        </div>

        <!-- 操作按钮 -->
        <div class="review-actions">
          <button
            v-if="canAutoApprove(currentPrediction)"
            class="btn btn-auto-approve"
            @click="handleApprove(true)"
          >
            一键通过
          </button>
          <button class="btn btn-approve" @click="handleApprove(false)">
            批准
          </button>
          <button class="btn btn-reject" @click="handleReject(false)">
            拒绝
          </button>
          <button class="btn btn-reject-invalid" @click="handleReject(true)">
            标记为废图
          </button>
        </div>
      </div>
    </div>

    <!-- 消息提示 -->
    <div v-if="message" :class="['message', message.type]">
      {{ message.text }}
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const emit = defineEmits(['refresh'])

const loading = ref(true)
const predictions = ref([])
const currentIndex = ref(0)
const stats = ref({
  pending_count: 0,
  new_class_count: 0,
  auto_approve_count: 0
})
const message = ref(null)

// 当前预测
const currentPrediction = computed(() =>
  predictions.value[currentIndex.value] || null
)

// 是否显示一键通过全部按钮
const showAutoApproveButton = computed(() =>
  stats.value.auto_approve_count > 0 &&
  predictions.value.filter(p => canAutoApprove(p)).length === predictions.value.length
)

// 获取图片URL
const getImageUrl = (filename) => `/api/images/${encodeURIComponent(filename)}`

// 判断是否可以一键通过
const canAutoApprove = (prediction) => {
  return (
    !prediction.is_new_class &&
    prediction.aircraft_confidence >= 0.95 &&
    prediction.airline_confidence >= 0.95
  )
}

// 获取置信度等级
const getConfidenceClass = (confidence) => {
  if (confidence >= 0.95) return 'high'
  if (confidence >= 0.80) return 'medium'
  return 'low'
}

// 加载数据
const loadData = async () => {
  loading.value = true
  try {
    // 获取统计信息
    const statsRes = await axios.get('/api/ai/stats')
    stats.value = statsRes.data

    // 获取待复审的预测
    const predRes = await axios.get('/api/ai/review/pending')
    predictions.value = predRes.data.items
    currentIndex.value = 0
  } catch (e) {
    console.error('加载数据失败:', e)
    showMessage('加载数据失败', 'error')
  } finally {
    loading.value = false
  }
}

// 批准预测
const handleApprove = async (autoApprove = false) => {
  if (!currentPrediction.value) return

  try {
    await axios.post('/api/ai/review/approve', {
      filename: currentPrediction.value.filename,
      auto_approve
    })

    showMessage(autoApprove ? '一键通过成功' : '批准成功', 'success')

    // 从列表中移除
    predictions.value.splice(currentIndex.value, 1)

    // 更新统计
    if (autoApprove) {
      stats.value.auto_approve_count--
    }
    stats.value.pending_count--

    emit('refresh')

    // 跳到下一个
    if (predictions.value.length > 0) {
      if (currentIndex.value >= predictions.value.length) {
        currentIndex.value = 0
      }
    }
  } catch (e) {
    console.error('批准失败:', e)
    showMessage(e.response?.data?.error || '批准失败', 'error')
  }
}

// 拒绝预测
const handleReject = async (skipAsInvalid = false) => {
  if (!currentPrediction.value) return

  try {
    await axios.post('/api/ai/review/reject', {
      filename: currentPrediction.value.filename,
      skip_as_invalid: skipAsInvalid
    })

    showMessage(skipAsInvalid ? '已标记为废图' : '已拒绝', 'success')

    // 从列表中移除
    predictions.value.splice(currentIndex.value, 1)

    // 更新统计
    stats.value.pending_count--
    if (currentPrediction.value.is_new_class) {
      stats.value.new_class_count--
    }
    if (canAutoApprove(currentPrediction.value)) {
      stats.value.auto_approve_count--
    }

    emit('refresh')

    // 跳到下一个
    if (predictions.value.length > 0) {
      if (currentIndex.value >= predictions.value.length) {
        currentIndex.value = 0
      }
    }
  } catch (e) {
    console.error('拒绝失败:', e)
    showMessage(e.response?.data?.error || '拒绝失败', 'error')
  }
}

// 批量一键通过
const handleBulkAutoApprove = async () => {
  if (!stats.value.auto_approve_count) return

  try {
    // 获取可一键通过的预测
    const autoApprovePred = await axios.get('/api/ai/review/auto-approvable')
    const filenames = autoApprovePred.data.items.map(p => p.filename)

    if (filenames.length === 0) {
      showMessage('没有可一键通过的预测', 'info')
      return
    }

    await axios.post('/api/ai/review/bulk-approve', { filenames })

    showMessage(`已一键通过 ${filenames.length} 张图片`, 'success')

    // 刷新数据
    await loadData()
    emit('refresh')
  } catch (e) {
    console.error('批量批准失败:', e)
    showMessage(e.response?.data?.error || '批量批准失败', 'error')
  }
}

// 显示消息
const showMessage = (text, type = 'info') => {
  message.value = { text, type }
  setTimeout(() => {
    message.value = null
  }, 3000)
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.review-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1a1a1a;
  color: #fff;
}

.review-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  background: #252525;
  border-bottom: 1px solid #333;
}

.stats-grid {
  display: flex;
  gap: 20px;
}

.stat-item {
  text-align: center;
}

.stat-label {
  font-size: 12px;
  color: #888;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 24px;
  font-weight: 500;
  color: #4a90d9;
}

.stat-value.new-class {
  color: #ff9800;
}

.stat-value.auto-approve {
  color: #4caf50;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.auto-approve-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  background: #4caf50;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.auto-approve-btn:hover {
  background: #5cb85c;
}

.refresh-btn {
  padding: 10px 20px;
  border: 1px solid #666;
  border-radius: 4px;
  background: transparent;
  color: #aaa;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.refresh-btn:hover:not(:disabled) {
  border-color: #888;
  color: #fff;
}

.refresh-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.loading,
.no-predictions {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #888;
}

.no-predictions .empty-icon {
  font-size: 64px;
  margin-bottom: 20px;
  color: #4caf50;
}

.no-predictions h2 {
  margin: 0 0 10px 0;
  color: #fff;
}

.review-content {
  flex: 1;
  display: flex;
  gap: 20px;
  overflow: hidden;
}

.image-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.image-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  padding: 10px;
  background: #252525;
  border-radius: 4px;
}

.filename {
  font-family: monospace;
  color: #4a90d9;
}

.index {
  color: #888;
  font-size: 14px;
}

.image-container {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #000;
  border-radius: 4px;
  overflow: hidden;
}

.image-container img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.form-section {
  width: 380px;
  flex-shrink: 0;
  padding: 20px;
  background: #252525;
  border-radius: 8px;
  overflow-y: auto;
}

.form-section h3 {
  margin: 0 0 20px 0;
  font-size: 18px;
}

.review-module {
  margin-bottom: 20px;
  padding: 15px;
  background: #1a1a1a;
  border-radius: 4px;
}

.module-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.module-title {
  font-weight: 500;
  color: #aaa;
  font-size: 13px;
}

.module-confidence {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.module-confidence.high {
  background: #2d5a2d;
  color: #8fdf8f;
}

.module-confidence.medium {
  background: #5a4a2d;
  color: #dfdf8f;
}

.module-confidence.low {
  background: #5a2d2d;
  color: #df8f8f;
}

.module-status {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  color: #888;
}

.module-status.has-result {
  color: #4caf50;
}

.module-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prediction-result {
  display: flex;
  justify-content: space-between;
}

.result-label {
  color: #666;
  font-size: 13px;
}

.result-value {
  color: #fff;
  font-weight: 500;
}

.confidence-indicator {
  margin-top: 4px;
}

.confidence-bar {
  height: 6px;
  background: #333;
  border-radius: 3px;
  overflow: hidden;
}

.confidence-fill {
  height: 100%;
  background: #4a90d9;
  transition: width 0.3s;
}

.ocr-details {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #666;
}

.quality-item {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.quality-label {
  width: 60px;
  color: #666;
  font-size: 12px;
}

.quality-value {
  width: 50px;
  text-align: right;
  color: #fff;
  font-size: 13px;
}

.quality-bar {
  flex: 1;
  height: 6px;
  background: #333;
  border-radius: 3px;
  overflow: hidden;
}

.quality-fill {
  height: 100%;
  background: #4a90d9;
  transition: width 0.3s;
}

.new-class-badge {
  margin-bottom: 20px;
  padding: 10px;
  background: #5a4a2d;
  border: 1px solid #dfdf8f;
  border-radius: 4px;
  color: #dfdf8f;
  font-size: 13px;
  text-align: center;
}

.review-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 20px;
}

.btn {
  padding: 12px 16px;
  border: none;
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-auto-approve {
  background: #4caf50;
  color: #fff;
}

.btn-auto-approve:hover {
  background: #5cb85c;
}

.btn-approve {
  background: #4a90d9;
  color: #fff;
}

.btn-approve:hover {
  background: #5a9fe9;
}

.btn-reject {
  border: 1px solid #666;
  background: transparent;
  color: #aaa;
}

.btn-reject:hover {
  border-color: #888;
  color: #fff;
}

.btn-reject-invalid {
  border: 1px solid #aa3333;
  background: transparent;
  color: #ff6666;
}

.btn-reject-invalid:hover {
  background: #aa3333;
  color: #fff;
}

.message {
  position: fixed;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  padding: 12px 24px;
  border-radius: 4px;
  font-size: 14px;
  z-index: 1000;
}

.message.success {
  background: #2d5a2d;
  color: #8fdf8f;
}

.message.error {
  background: #5a2d2d;
  color: #df8f8f;
}

.message.info {
  background: #2d4a5a;
  color: #8fdfdf;
}
</style>
