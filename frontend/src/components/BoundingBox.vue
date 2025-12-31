<template>
  <div class="bounding-box-container" ref="containerRef">
    <div class="canvas-wrapper">
      <canvas
        ref="canvasRef"
        :width="canvasWidth"
        :height="canvasHeight"
        @mousedown="handleMouseDown"
        @mousemove="handleMouseMove"
        @mouseup="handleMouseUp"
        @mouseleave="handleMouseUp"
        @wheel.prevent="handleWheel"
        @contextmenu.prevent
      ></canvas>
      <div class="zoom-info">
        {{ Math.round(zoomLevel * 100) }}%
      </div>
    </div>
    <div class="box-legend">
      <span class="legend-item registration">
        <span class="legend-color"></span>
        注册号区域 ({{ registrationBox ? '已绘制' : '未绘制' }})
      </span>
    </div>
    <div class="box-controls">
      <button @click="setMode('registration')" :class="{ active: currentMode === 'registration' }">
        绘制注册号
      </button>
      <button @click="setMode('pan')" :class="{ active: currentMode === 'pan' }">
        平移
      </button>
      <button @click="resetView" class="reset-btn">
        重置视图
      </button>
      <button @click="clearBoxes" class="clear-btn">清除</button>
    </div>
    <div class="zoom-hint">
      滚轮缩放 | 中键/右键拖动平移 | 双击重置
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  imageSrc: String,
  imageWidth: Number,
  imageHeight: Number,
  initialRegistrationBox: Object
})

const emit = defineEmits(['update:registrationBox'])

const containerRef = ref(null)
const canvasRef = ref(null)
const canvasWidth = ref(800)
const canvasHeight = ref(600)

const currentMode = ref('registration') // 'registration' | 'pan'
const isDrawing = ref(false)
const isPanning = ref(false)
const startPoint = ref(null)
const currentPoint = ref(null)
const lastPanPoint = ref(null)

const registrationBox = ref(props.initialRegistrationBox || null)

const image = ref(null)

// 基础缩放（适应画布）
const baseScale = ref(1)
// 用户缩放级别
const zoomLevel = ref(1)
// 实际缩放 = baseScale * zoomLevel
const scale = ref(1)
// 平移偏移
const panX = ref(0)
const panY = ref(0)
// 图片在画布中的偏移（居中用）
const baseOffsetX = ref(0)
const baseOffsetY = ref(0)

// 缩放限制
const MIN_ZOOM = 0.5
const MAX_ZOOM = 5

// 加载图片
const loadImage = () => {
  if (!props.imageSrc) return

  const img = new Image()
  img.onload = () => {
    image.value = img

    // 计算缩放比例，使图片适应画布
    const containerWidth = containerRef.value?.clientWidth || 800
    const containerHeight = 600

    canvasWidth.value = containerWidth
    canvasHeight.value = containerHeight

    const scaleX = containerWidth / img.width
    const scaleY = containerHeight / img.height
    baseScale.value = Math.min(scaleX, scaleY, 1)

    // 重置缩放和平移
    zoomLevel.value = 1
    panX.value = 0
    panY.value = 0

    updateScale()

    nextTick(() => {
      draw()
    })
  }
  img.src = props.imageSrc
}

// 更新实际缩放
const updateScale = () => {
  scale.value = baseScale.value * zoomLevel.value

  // 计算居中偏移
  const containerWidth = canvasWidth.value
  const containerHeight = canvasHeight.value
  baseOffsetX.value = (containerWidth - image.value.width * scale.value) / 2
  baseOffsetY.value = (containerHeight - image.value.height * scale.value) / 2
}

// 获取最终偏移（基础偏移 + 平移）
const getOffsetX = () => baseOffsetX.value + panX.value
const getOffsetY = () => baseOffsetY.value + panY.value

// 绘制画布
const draw = () => {
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvasWidth.value, canvasHeight.value)

  // 绘制背景格子（表示可视区域外）
  ctx.fillStyle = '#0a0a0a'
  ctx.fillRect(0, 0, canvasWidth.value, canvasHeight.value)

  // 绘制图片
  if (image.value) {
    const offsetX = getOffsetX()
    const offsetY = getOffsetY()

    ctx.drawImage(
      image.value,
      offsetX,
      offsetY,
      image.value.width * scale.value,
      image.value.height * scale.value
    )
  }

  // 绘制注册号框
  if (registrationBox.value) {
    drawBox(ctx, registrationBox.value, '#ff6600', '注册号')
  }

  // 绘制当前正在绘制的框
  if (isDrawing.value && startPoint.value && currentPoint.value && currentMode.value !== 'pan') {
    drawTempBox(ctx, startPoint.value, currentPoint.value, '#ff6600')
  }
}

// 绘制矩形框
const drawBox = (ctx, box, color, label) => {
  const offsetX = getOffsetX()
  const offsetY = getOffsetY()

  const x1 = box.x1 * scale.value + offsetX
  const y1 = box.y1 * scale.value + offsetY
  const x2 = box.x2 * scale.value + offsetX
  const y2 = box.y2 * scale.value + offsetY

  ctx.strokeStyle = color
  ctx.lineWidth = 2
  ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)

  // 半透明填充
  ctx.fillStyle = color + '20'
  ctx.fillRect(x1, y1, x2 - x1, y2 - y1)

  // 标签
  ctx.fillStyle = color
  ctx.font = '14px sans-serif'
  ctx.fillText(label, x1 + 4, y1 + 16)
}

// 绘制临时框
const drawTempBox = (ctx, start, end, color) => {
  ctx.strokeStyle = color
  ctx.lineWidth = 2
  ctx.setLineDash([5, 5])
  ctx.strokeRect(start.x, start.y, end.x - start.x, end.y - start.y)
  ctx.setLineDash([])
}

// 将画布坐标转换为图片坐标
const canvasToImage = (canvasX, canvasY) => {
  const offsetX = getOffsetX()
  const offsetY = getOffsetY()
  const imageX = (canvasX - offsetX) / scale.value
  const imageY = (canvasY - offsetY) / scale.value
  return { x: imageX, y: imageY }
}

// 滚轮缩放
const handleWheel = (e) => {
  const rect = canvasRef.value.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top

  // 缩放前的图片坐标
  const beforeZoom = canvasToImage(mouseX, mouseY)

  // 计算新的缩放级别
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoomLevel.value * delta))

  if (newZoom !== zoomLevel.value) {
    zoomLevel.value = newZoom
    updateScale()

    // 缩放后的图片坐标
    const afterZoom = canvasToImage(mouseX, mouseY)

    // 调整平移以保持鼠标位置不变
    panX.value += (afterZoom.x - beforeZoom.x) * scale.value
    panY.value += (afterZoom.y - beforeZoom.y) * scale.value

    draw()
  }
}

// 鼠标事件处理
const handleMouseDown = (e) => {
  const rect = canvasRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top

  // 中键或右键开始平移
  if (e.button === 1 || e.button === 2 || currentMode.value === 'pan') {
    isPanning.value = true
    lastPanPoint.value = { x: e.clientX, y: e.clientY }
    return
  }

  // 左键绘制
  if (e.button === 0 && currentMode.value !== 'pan') {
    isDrawing.value = true
    startPoint.value = { x, y }
    currentPoint.value = { x, y }
  }
}

const handleMouseMove = (e) => {
  // 平移模式
  if (isPanning.value && lastPanPoint.value) {
    const dx = e.clientX - lastPanPoint.value.x
    const dy = e.clientY - lastPanPoint.value.y
    panX.value += dx
    panY.value += dy
    lastPanPoint.value = { x: e.clientX, y: e.clientY }
    draw()
    return
  }

  // 绘制模式
  if (!isDrawing.value) return

  const rect = canvasRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top

  currentPoint.value = { x, y }
  draw()
}

const handleMouseUp = (e) => {
  // 结束平移
  if (isPanning.value) {
    isPanning.value = false
    lastPanPoint.value = null
    return
  }

  if (!isDrawing.value || !startPoint.value || !currentPoint.value) {
    isDrawing.value = false
    return
  }

  // 转换为图片坐标
  const start = canvasToImage(startPoint.value.x, startPoint.value.y)
  const end = canvasToImage(currentPoint.value.x, currentPoint.value.y)

  // 确保坐标在图片范围内
  const imgWidth = props.imageWidth || image.value?.width || 1920
  const imgHeight = props.imageHeight || image.value?.height || 1080

  const box = {
    x1: Math.max(0, Math.min(start.x, end.x)),
    y1: Math.max(0, Math.min(start.y, end.y)),
    x2: Math.min(imgWidth, Math.max(start.x, end.x)),
    y2: Math.min(imgHeight, Math.max(start.y, end.y))
  }

  // 检查框是否有效（宽高大于10像素）
  if (box.x2 - box.x1 > 10 && box.y2 - box.y1 > 10) {
    if (currentMode.value === 'registration') {
      registrationBox.value = box
      emit('update:registrationBox', box)
    }
  }

  isDrawing.value = false
  startPoint.value = null
  currentPoint.value = null
  draw()
}

// 双击重置视图
const handleDoubleClick = () => {
  resetView()
}

// 设置绘制模式
const setMode = (mode) => {
  currentMode.value = mode
}

// 重置视图
const resetView = () => {
  zoomLevel.value = 1
  panX.value = 0
  panY.value = 0
  if (image.value) {
    updateScale()
  }
  draw()
}

// 清除所有框
const clearBoxes = () => {
  registrationBox.value = null
  emit('update:registrationBox', null)
  draw()
}

// 计算 YOLO 格式的区域字符串
const calculateArea = (box, imgWidth, imgHeight) => {
  if (!box) return ''

  const xCenter = ((box.x1 + box.x2) / 2) / imgWidth
  const yCenter = ((box.y1 + box.y2) / 2) / imgHeight
  const width = (box.x2 - box.x1) / imgWidth
  const height = (box.y2 - box.y1) / imgHeight

  return `${xCenter.toFixed(4)} ${yCenter.toFixed(4)} ${width.toFixed(4)} ${height.toFixed(4)}`
}

// 暴露方法给父组件
defineExpose({
  calculateArea,
  getRegistrationBox: () => registrationBox.value,
  resetView
})

// 监听图片变化
watch(() => props.imageSrc, () => {
  registrationBox.value = null
  loadImage()
})

// 监听初始值变化
watch(() => props.initialRegistrationBox, (val) => {
  registrationBox.value = val
  draw()
})

// 键盘事件（空格键切换平移模式）
let previousMode = 'registration'
const handleKeyDown = (e) => {
  if (e.code === 'Space' && currentMode.value !== 'pan') {
    e.preventDefault()
    previousMode = currentMode.value
    currentMode.value = 'pan'
  }
}

const handleKeyUp = (e) => {
  if (e.code === 'Space') {
    e.preventDefault()
    currentMode.value = previousMode
  }
}

onMounted(() => {
  loadImage()
  canvasRef.value?.addEventListener('dblclick', handleDoubleClick)
  window.addEventListener('keydown', handleKeyDown)
  window.addEventListener('keyup', handleKeyUp)
})

onUnmounted(() => {
  canvasRef.value?.removeEventListener('dblclick', handleDoubleClick)
  window.removeEventListener('keydown', handleKeyDown)
  window.removeEventListener('keyup', handleKeyUp)
})
</script>

<style scoped>
.bounding-box-container {
  position: relative;
  width: 100%;
}

.canvas-wrapper {
  position: relative;
}

canvas {
  display: block;
  background: #1a1a1a;
  border: 1px solid #333;
  cursor: crosshair;
}

.zoom-info {
  position: absolute;
  top: 10px;
  right: 10px;
  padding: 4px 10px;
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  font-size: 12px;
  border-radius: 4px;
  pointer-events: none;
}

.box-legend {
  display: flex;
  gap: 20px;
  margin-top: 10px;
  font-size: 14px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-color {
  width: 16px;
  height: 16px;
  border-radius: 2px;
}

.legend-item.registration .legend-color {
  background: #ff6600;
}

.box-controls {
  display: flex;
  gap: 10px;
  margin-top: 10px;
}

.box-controls button {
  padding: 8px 16px;
  border: 1px solid #444;
  background: #2a2a2a;
  color: #fff;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.2s;
}

.box-controls button:hover {
  background: #3a3a3a;
}

.box-controls button.active {
  background: #4a90d9;
  border-color: #4a90d9;
}

.box-controls .reset-btn {
  background: #555;
  border-color: #666;
}

.box-controls .reset-btn:hover {
  background: #666;
}

.box-controls .clear-btn {
  margin-left: auto;
  background: #aa3333;
  border-color: #aa3333;
}

.box-controls .clear-btn:hover {
  background: #cc4444;
}

.zoom-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #666;
}
</style>
