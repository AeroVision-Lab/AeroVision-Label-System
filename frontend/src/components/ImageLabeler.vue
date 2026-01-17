<template>
  <div class="image-labeler">
    <div v-if="loading" class="loading">
      加载中...
    </div>

    <div v-else-if="!currentImage" class="no-images">
      <div class="empty-icon">🎉</div>
      <h2>没有待标注的图片</h2>
      <p>所有图片都已标注完成，或待标注文件夹为空</p>
    </div>

    <div v-else class="labeler-content">
      <!-- 左侧：图片和矩形框 -->
      <div class="image-section">
        <div class="image-info">
          <span class="filename">{{ currentImage.filename }}</span>
          <span v-if="lockStatus === 'locked'" class="lock-status locked">
            已锁定
          </span>
          <span v-else-if="lockStatus === 'failed'" class="lock-status failed">
            锁定失败
          </span>
          <span class="progress">
            {{ currentIndex + 1 }} / {{ availableImages.length }}
          </span>
        </div>

        <BoundingBox
          ref="boundingBoxRef"
          :image-src="getImageUrl(currentImage.filename)"
          :image-width="imageWidth"
          :image-height="imageHeight"
          @update:registration-box="onRegistrationBoxUpdate"
        />
      </div>

      <!-- 右侧：标注表单 -->
      <div class="form-section">
        <LabelForm
          ref="labelFormRef"
          :registration-area="registrationArea"
          :current-image="currentImage"
          @submit="handleSubmit"
          @skip="handleSkip"
          @skip-as-invalid="handleSkipAsInvalid"
        />
      </div>
    </div>

    <!-- 消息提示 -->
    <div v-if="message" :class="['message', message.type]">
      {{ message.text }}
    </div>

    <!-- 废图确认弹窗 -->
    <div v-if="showSkipConfirm" class="modal-overlay" @click.self="showSkipConfirm = false">
      <div class="modal-content">
        <h3>确认标记为废图</h3>
        <p>确定要将 "{{ skipConfirmFilename }}" 标记为废图吗？</p>
        <p class="warning">标记后此图片将永久隐藏，不再显示在待标注列表中。</p>
        <div class="modal-actions">
          <button class="cancel-btn" @click="showSkipConfirm = false">取消</button>
          <button class="confirm-btn" @click="confirmSkipAsInvalid">确认</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import BoundingBox from './BoundingBox.vue'
import LabelForm from './LabelForm.vue'
import {
  getImages,
  getImageUrl,
  createLabel,
  acquireLock,
  releaseLock,
  releaseAllLocks,
  sendHeartbeat,
  userId,
  skipImage
} from '../api'

const emit = defineEmits(['labeled'])

const loading = ref(true)
const images = ref([])
const currentIndex = ref(0)
const boundingBoxRef = ref(null)
const labelFormRef = ref(null)
const message = ref(null)

// 锁相关
const lockStatus = ref('') // 'locked' | 'failed' | ''
const currentLockedFile = ref(null)
let heartbeatTimer = null

// 废图确认弹窗
const showSkipConfirm = ref(false)
const skipConfirmFilename = ref('')

// 图片尺寸（实际尺寸，用于计算 YOLO 格式）
const imageWidth = ref(1920)
const imageHeight = ref(1080)

// 过滤掉被他人锁定的图片
const availableImages = computed(() =>
  images.value.filter(img => !img.locked)
)

// 当前图片
const currentImage = computed(() => availableImages.value[currentIndex.value] || null)

// 区域数据
const registrationBox = ref(null)

// 计算 YOLO 格式的区域字符串
const registrationArea = computed(() => {
  if (!registrationBox.value) return ''
  return calculateArea(registrationBox.value)
})

// 计算 YOLO 格式
const calculateArea = (box) => {
  const xCenter = ((box.x1 + box.x2) / 2) / imageWidth.value
  const yCenter = ((box.y1 + box.y2) / 2) / imageHeight.value
  const width = (box.x2 - box.x1) / imageWidth.value
  const height = (box.y2 - box.y1) / imageHeight.value
  return `${xCenter.toFixed(4)} ${yCenter.toFixed(4)} ${width.toFixed(4)} ${height.toFixed(4)}`
}

// 加载图片列表
const loadImages = async () => {
  loading.value = true
  try {
    const res = await getImages()
    images.value = res.data.items
    currentIndex.value = 0

    // 加载第一张图片并锁定
    if (availableImages.value.length > 0) {
      await loadAndLockImage(availableImages.value[0].filename)
    }
  } catch (e) {
    console.error('加载图片列表失败:', e)
    showMessage('加载图片列表失败', 'error')
  } finally {
    loading.value = false
  }
}

// 加载图片并锁定
const loadAndLockImage = async (filename) => {
  // 先释放之前的锁
  if (currentLockedFile.value && currentLockedFile.value !== filename) {
    await releaseLock(currentLockedFile.value).catch(() => {})
  }

  // 加载图片尺寸
  await loadImageSize(filename)

  // 尝试锁定
  try {
    await acquireLock(filename)
    lockStatus.value = 'locked'
    currentLockedFile.value = filename
    startHeartbeat(filename)
  } catch (e) {
    if (e.response?.status === 409) {
      lockStatus.value = 'failed'
      showMessage(`图片已被 ${e.response.data.locked_by} 锁定`, 'error')
      // 跳到下一张
      setTimeout(() => handleSkip(), 1500)
    }
  }
}

// 加载图片尺寸
const loadImageSize = (filename) => {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      imageWidth.value = img.width
      imageHeight.value = img.height
      resolve()
    }
    img.onerror = () => {
      // 使用默认尺寸
      resolve()
    }
    img.src = getImageUrl(filename)
  })
}

// 心跳保持锁
const startHeartbeat = (filename) => {
  stopHeartbeat()
  heartbeatTimer = setInterval(async () => {
    if (currentLockedFile.value === filename) {
      try {
        await sendHeartbeat(filename)
      } catch (e) {
        console.error('心跳失败:', e)
        lockStatus.value = 'failed'
        stopHeartbeat()
      }
    }
  }, 60000) // 每分钟发送一次心跳
}

const stopHeartbeat = () => {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

// 矩形框更新
const onRegistrationBoxUpdate = (box) => {
  registrationBox.value = box
}

// 提交标注
const handleSubmit = async (formData) => {
  if (!currentImage.value) return

  const filename = currentImage.value.filename

  try {
    const data = {
      original_file_name: filename,
      ...formData
    }

    await createLabel(data)

    // 释放锁
    await releaseLock(filename).catch(() => {})
    currentLockedFile.value = null
    stopHeartbeat()

    showMessage('标注保存成功', 'success')
    emit('labeled')

    // 从列表中移除已标注的图片
    const idx = images.value.findIndex(img => img.filename === filename)
    if (idx !== -1) {
      images.value.splice(idx, 1)
    }

    if (availableImages.value.length === 0) {
      // 没有更多图片了
      return
    }

    // 如果当前索引超出范围，回到第一张
    if (currentIndex.value >= availableImages.value.length) {
      currentIndex.value = 0
    }

    // 重置状态并加载下一张
    resetState()
    if (currentImage.value) {
      await loadAndLockImage(currentImage.value.filename)
    }
  } catch (e) {
    console.error('保存标注失败:', e)
    showMessage(e.response?.data?.error || '保存标注失败', 'error')
  }
}

// 跳过当前图片
const handleSkip = async () => {
  if (availableImages.value.length <= 1) {
    showMessage('没有更多图片了', 'info')
    return
  }

  const filename = currentImage.value?.filename

  // 释放当前锁
  if (filename && currentLockedFile.value === filename) {
    await releaseLock(filename).catch(() => {})
    currentLockedFile.value = null
    stopHeartbeat()
  }

  currentIndex.value = (currentIndex.value + 1) % availableImages.value.length
  resetState()

  if (currentImage.value) {
    await loadAndLockImage(currentImage.value.filename)
  }
}

// 标记为废图并跳过 - 显示确认弹窗
const handleSkipAsInvalid = () => {
  if (!currentImage.value) return
  skipConfirmFilename.value = currentImage.value.filename
  showSkipConfirm.value = true
}

// 确认标记为废图
const confirmSkipAsInvalid = async () => {
  const filename = skipConfirmFilename.value
  showSkipConfirm.value = false

  if (!filename) return

  try {
    // 调用跳过 API
    await skipImage(filename)

    // 释放锁
    if (currentLockedFile.value === filename) {
      await releaseLock(filename).catch(() => {})
      currentLockedFile.value = null
      stopHeartbeat()
    }

    showMessage('已标记为废图', 'success')
    emit('labeled')

    // 从列表中移除
    const idx = images.value.findIndex(img => img.filename === filename)
    if (idx !== -1) {
      images.value.splice(idx, 1)
    }

    if (availableImages.value.length === 0) {
      return
    }

    if (currentIndex.value >= availableImages.value.length) {
      currentIndex.value = 0
    }

    resetState()
    if (currentImage.value) {
      await loadAndLockImage(currentImage.value.filename)
    }
  } catch (e) {
    console.error('跳过图片失败:', e)
    showMessage(e.response?.data?.error || '跳过失败', 'error')
  }
}

// 重置状态
const resetState = () => {
  registrationBox.value = null
  lockStatus.value = ''
  if (boundingBoxRef.value) {
    boundingBoxRef.value.resetView()
  }
  if (labelFormRef.value) {
    labelFormRef.value.reset()
  }
}

// 显示消息
const showMessage = (text, type = 'info') => {
  message.value = { text, type }
  setTimeout(() => {
    message.value = null
  }, 3000)
}

// 页面卸载前释放所有锁
const handleBeforeUnload = () => {
  if (currentLockedFile.value) {
    // 使用同步请求释放锁（已废弃但在 beforeunload 中仍有用）
    navigator.sendBeacon('/api/locks/release', JSON.stringify({
      filename: currentLockedFile.value,
      user_id: userId
    }))
  }
}

onMounted(() => {
  loadImages()
  window.addEventListener('beforeunload', handleBeforeUnload)
})

onUnmounted(() => {
  stopHeartbeat()
  releaseAllLocks().catch(() => {})
  window.removeEventListener('beforeunload', handleBeforeUnload)
})
</script>

<style scoped>
.image-labeler {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.loading,
.no-images {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #888;
}

.no-images .empty-icon {
  font-size: 64px;
  margin-bottom: 20px;
}

.no-images h2 {
  margin: 0 0 10px 0;
  color: #fff;
}

.labeler-content {
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
  gap: 15px;
  margin-bottom: 10px;
  padding: 10px;
  background: #252525;
  border-radius: 4px;
}

.filename {
  font-family: monospace;
  color: #4a90d9;
}

.lock-status {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.lock-status.locked {
  background: #2d5a2d;
  color: #8fdf8f;
}

.lock-status.failed {
  background: #5a2d2d;
  color: #df8f8f;
}

.progress {
  margin-left: auto;
  color: #888;
  font-size: 14px;
}

.form-section {
  width: 350px;
  flex-shrink: 0;
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

/* 确认弹窗样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.modal-content {
  background: #2a2a2a;
  border-radius: 8px;
  padding: 24px;
  max-width: 400px;
  width: 90%;
}

.modal-content h3 {
  margin: 0 0 16px 0;
  color: #fff;
  font-size: 18px;
}

.modal-content p {
  margin: 0 0 12px 0;
  color: #ccc;
  font-size: 14px;
}

.modal-content .warning {
  color: #ff9800;
  font-size: 13px;
}

.modal-actions {
  display: flex;
  gap: 12px;
  margin-top: 20px;
  justify-content: flex-end;
}

.modal-actions .cancel-btn {
  padding: 10px 20px;
  border: 1px solid #666;
  border-radius: 4px;
  background: transparent;
  color: #aaa;
  cursor: pointer;
  transition: all 0.2s;
}

.modal-actions .cancel-btn:hover {
  border-color: #888;
  color: #fff;
}

.modal-actions .confirm-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  background: #aa3333;
  color: #fff;
  cursor: pointer;
  transition: all 0.2s;
}

.modal-actions .confirm-btn:hover {
  background: #cc4444;
}
</style>
