<template>
  <form class="label-form" @submit.prevent="handleSubmit">
    <h3>标注信息</h3>

    <!-- 模型预测展示 - 机型 -->
    <div v-if="modelPrediction.type" class="model-prediction">
      <label>模型预测（机型）</label>
      <div class="prediction-card">
        <div class="top1">
          <span class="class-name">{{ modelPrediction.type.top1.class }}</span>
          <span class="confidence">{{ (modelPrediction.type.top1.confidence * 100).toFixed(1) }}%</span>
        </div>
        <div v-if="modelPrediction.type.top1.confidence < 0.7" class="warning">
          ⚠️ 置信度较低，请仔细确认
        </div>
        <label class="checkbox-label">
          <input
            type="checkbox"
            v-model="useModelType"
            @change="onUseModelTypeChange"
          />
          使用预测结果
        </label>
      </div>
    </div>

    <!-- 模型预测展示 - 注册号（OCR） -->
    <div v-if="modelPrediction.ocr && modelPrediction.ocr.text" class="model-prediction">
      <label>OCR识别（注册号）</label>
      <div class="prediction-card">
        <div class="ocr-result">
          <span class="text">{{ modelPrediction.ocr.text }}</span>
          <span class="confidence">{{ (modelPrediction.ocr.confidence * 100).toFixed(1) }}%</span>
        </div>
        <div v-if="modelPrediction.ocr.confidence < 0.7" class="warning">
          ⚠️ 识别置信度较低，请仔细确认
        </div>
        <label class="checkbox-label">
          <input
            type="checkbox"
            v-model="useModelOcr"
            @change="onUseModelOcrChange"
          />
          使用识别结果
        </label>
      </div>
    </div>

    <!-- 航司选择 -->
    <div class="form-group" :class="{ disabled: useModelAirline }">
      <label>航司</label>
      <div class="select-with-add">
        <select
          v-model="form.airlineId"
          @change="onAirlineChange"
          :disabled="useModelAirline"
        >
          <option value="">请选择航司</option>
          <option v-for="airline in airlines" :key="airline.code" :value="airline.code">
            {{ airline.code }} - {{ airline.name }}
          </option>
          <option value="__new__">+ 新增航司</option>
        </select>
      </div>
      <div v-if="showNewAirline" class="new-item-form">
        <input v-model="newAirline.code" placeholder="航司代码 (如 CCA)" maxlength="10" />
        <input v-model="newAirline.name" placeholder="航司名称" />
        <button type="button" @click="addAirline">添加</button>
        <button type="button" @click="cancelNewAirline">取消</button>
      </div>
    </div>

    <!-- 机型选择 -->
    <div class="form-group" :class="{ disabled: useModelType }">
      <label>机型</label>
      <div class="select-with-add">
        <select
          v-model="form.typeId"
          @change="onTypeChange"
          :disabled="useModelType"
        >
          <option value="">请选择机型</option>
          <option v-for="type in aircraftTypes" :key="type.code" :value="type.code">
            {{ type.code }} - {{ type.name }}
          </option>
          <option value="__new__">+ 新增机型</option>
        </select>
      </div>
      <div v-if="showNewType" class="new-item-form">
        <input v-model="newType.code" placeholder="机型代码 (如 A320)" maxlength="10" />
        <input v-model="newType.name" placeholder="机型名称" />
        <button type="button" @click="addType">添加</button>
        <button type="button" @click="cancelNewType">取消</button>
      </div>
    </div>

    <!-- 注册号 -->
    <div class="form-group" :class="{ disabled: useModelOcr }">
      <label>注册号</label>
      <input
        v-model="form.registration"
        placeholder="如 B-1234"
        maxlength="20"
        :disabled="useModelOcr"
      />
    </div>

    <!-- 清晰度 -->
    <div class="form-group">
      <label>清晰度: {{ form.clarity.toFixed(2) }}</label>
      <input
        type="range"
        v-model.number="form.clarity"
        min="0"
        max="1"
        step="0.01"
      />
      <div class="range-labels">
        <span>模糊</span>
        <span>清晰</span>
      </div>
    </div>

    <!-- 遮挡度 -->
    <div class="form-group">
      <label>遮挡度: {{ form.block.toFixed(2) }}</label>
      <input
        type="range"
        v-model.number="form.block"
        min="0"
        max="1"
        step="0.01"
      />
      <div class="range-labels">
        <span>无遮挡</span>
        <span>完全遮挡</span>
      </div>
    </div>

    <!-- 区域信息显示 -->
    <div class="form-group area-info">
      <label>区域信息</label>
      <div class="area-display">
        <div :class="{ valid: !!registrationArea }">
          注册号: {{ registrationArea || '未绘制' }}
        </div>
      </div>
    </div>

    <!-- 错误信息 -->
    <div v-if="error" class="error-message">
      {{ error }}
    </div>

    <!-- 提交按钮 -->
    <div class="form-actions">
      <button type="submit" :disabled="!isValid || loading" class="submit-btn">
        {{ loading ? '保存中...' : '保存标注' }}
      </button>
      <button type="button" @click="handleSkip" class="skip-btn">
        跳过
      </button>
      <button type="button" @click="handleSkipAsInvalid" class="skip-invalid-btn">
        废图
      </button>
    </div>
  </form>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { getAirlines, getAircraftTypes, createAirline, createAircraftType, predictImage, ocrImage } from '../api'

const props = defineProps({
  registrationArea: String,
  initialData: Object,
  currentImage: Object  // 新增：当前图片信息
})

const emit = defineEmits(['submit', 'skip', 'skipAsInvalid', 'fetchPrediction'])

const airlines = ref([])
const aircraftTypes = ref([])
const loading = ref(false)
const error = ref('')

// 模型预测数据
const modelPrediction = ref({
  type: null,  // YOLOv8-cls 预测结果
  ocr: null    // PaddleOCR 识别结果
})

// 是否使用模型预测
const useModelType = ref(false)
const useModelAirline = ref(false)
const useModelOcr = ref(false)

const form = ref({
  airlineId: '',
  airlineName: '',
  typeId: '',
  typeName: '',
  registration: '',
  clarity: 0.8,
  block: 0
})

// 新增航司
const showNewAirline = ref(false)
const newAirline = ref({ code: '', name: '' })

// 新增机型
const showNewType = ref(false)
const newType = ref({ code: '', name: '' })

// 表单验证
const isValid = computed(() => {
  return (
    form.value.airlineId &&
    form.value.typeId &&
    form.value.registration &&
    props.registrationArea
  )
})

// 获取模型预测
const fetchModelPrediction = async (imagePath) => {
  if (!imagePath) return

  try {
    // 调用后端预测接口
    const typeRes = await predictImage({ image_path: imagePath })
    if (typeRes.data) {
      modelPrediction.value.type = typeRes.data
    }

    // 调用后端OCR接口
    const ocrRes = await ocrImage({ image_path: imagePath })
    if (ocrRes.data) {
      modelPrediction.value.ocr = ocrRes.data
    }
  } catch (e) {
    console.error('获取模型预测失败:', e)
  }
}

// 监听当前图片变化，自动获取预测
watch(() => props.currentImage, (newImage) => {
  if (newImage && newImage.filename) {
    // 重置状态
    modelPrediction.value = { type: null, ocr: null }
    useModelType.value = false
    useModelAirline.value = false
    useModelOcr.value = false

    // 获取预测
    fetchModelPrediction(newImage.filename)
  }
}, { immediate: true })

// 使用模型预测切换事件
const onUseModelTypeChange = () => {
  if (useModelType.value && modelPrediction.value.type) {
    form.value.typeId = modelPrediction.value.type.top1.class
    form.value.typeName = modelPrediction.value.type.top1.class
  } else {
    form.value.typeId = ''
    form.value.typeName = ''
  }
}

const onUseModelOcrChange = () => {
  if (useModelOcr.value && modelPrediction.value.ocr) {
    form.value.registration = modelPrediction.value.ocr.text
  } else {
    form.value.registration = ''
  }
}

// 加载数据
const loadData = async () => {
  try {
    const [airlinesRes, typesRes] = await Promise.all([
      getAirlines(),
      getAircraftTypes()
    ])
    airlines.value = airlinesRes.data
    aircraftTypes.value = typesRes.data
  } catch (e) {
    console.error('加载数据失败:', e)
  }
}

// 航司选择变化
const onAirlineChange = () => {
  if (form.value.airlineId === '__new__') {
    showNewAirline.value = true
    form.value.airlineId = ''
  } else {
    const airline = airlines.value.find(a => a.code === form.value.airlineId)
    form.value.airlineName = airline?.name || ''
  }
}

// 机型选择变化
const onTypeChange = () => {
  if (form.value.typeId === '__new__') {
    showNewType.value = true
    form.value.typeId = ''
  } else {
    const type = aircraftTypes.value.find(t => t.code === form.value.typeId)
    form.value.typeName = type?.name || ''
  }
}

// 添加新航司
const addAirline = async () => {
  if (!newAirline.value.code || !newAirline.value.name) {
    error.value = '请填写航司代码和名称'
    return
  }

  try {
    await createAirline(newAirline.value)
    await loadData()
    form.value.airlineId = newAirline.value.code
    form.value.airlineName = newAirline.value.name
    cancelNewAirline()
  } catch (e) {
    error.value = e.response?.data?.error || '添加航司失败'
  }
}

const cancelNewAirline = () => {
  showNewAirline.value = false
  newAirline.value = { code: '', name: '' }
}

// 添加新机型
const addType = async () => {
  if (!newType.value.code || !newType.value.name) {
    error.value = '请填写机型代码和名称'
    return
  }

  try {
    await createAircraftType(newType.value)
    await loadData()
    form.value.typeId = newType.value.code
    form.value.typeName = newType.value.name
    cancelNewType()
  } catch (e) {
    error.value = e.response?.data?.error || '添加机型失败'
  }
}

const cancelNewType = () => {
  showNewType.value = false
  newType.value = { code: '', name: '' }
}

// 提交表单
const handleSubmit = async () => {
  if (!isValid.value) return

  loading.value = true
  error.value = ''

  try {
    const data = {
      airline_id: form.value.airlineId,
      airline_name: form.value.airlineName,
      type_id: form.value.typeId,
      type_name: form.value.typeName,
      registration: form.value.registration,
      clarity: form.value.clarity,
      block: form.value.block,
      registration_area: props.registrationArea,
      // 模型预测信息
      model_prediction_type: modelPrediction.value.type?.top1?.class || null,
      model_prediction_airline: null,  // 暂不支持航司预测
      model_confidence: modelPrediction.value.type?.top1?.confidence || null,
      model_ocr_text: modelPrediction.value.ocr?.text || null,
      // 是否使用模型预测
      use_model_type: useModelType.value,
      use_model_airline: useModelAirline.value,
      use_model_ocr: useModelOcr.value
    }
    emit('submit', data)
  } catch (e) {
    error.value = e.response?.data?.error || '保存失败'
  } finally {
    loading.value = false
  }
}

// 跳过
const handleSkip = () => {
  emit('skip')
}

// 标记为废图并跳过
const handleSkipAsInvalid = () => {
  emit('skipAsInvalid')
}

// 重置表单
const reset = () => {
  form.value = {
    airlineId: '',
    airlineName: '',
    typeId: '',
    typeName: '',
    registration: '',
    clarity: 0.8,
    block: 0
  }
  error.value = ''
  modelPrediction.value = { type: null, ocr: null }
  useModelType.value = false
  useModelAirline.value = false
  useModelOcr.value = false
}

// 监听初始数据
watch(() => props.initialData, (data) => {
  if (data) {
    form.value = {
      airlineId: data.airline_id || '',
      airlineName: data.airline_name || '',
      typeId: data.type_id || '',
      typeName: data.type_name || '',
      registration: data.registration || '',
      clarity: data.clarity ?? 0.8,
      block: data.block ?? 0
    }
  }
}, { immediate: true })

// 暴露方法
defineExpose({ reset })

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.label-form {
  padding: 20px;
  background: #252525;
  border-radius: 8px;
}

.label-form h3 {
  margin: 0 0 20px 0;
  color: #fff;
  font-size: 18px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  color: #aaa;
  font-size: 14px;
}

.form-group select,
.form-group input[type="text"],
.form-group input:not([type="range"]) {
  width: 100%;
  padding: 10px;
  border: 1px solid #444;
  border-radius: 4px;
  background: #1a1a1a;
  color: #fff;
  font-size: 14px;
}

.form-group select:focus,
.form-group input:focus {
  outline: none;
  border-color: #4a90d9;
}

.form-group input[type="range"] {
  width: 100%;
  margin-top: 8px;
}

.range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #666;
  margin-top: 4px;
}

.new-item-form {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.new-item-form input {
  flex: 1;
  padding: 8px;
}

.new-item-form button {
  padding: 8px 12px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.new-item-form button:first-of-type {
  background: #4a90d9;
  color: #fff;
}

.new-item-form button:last-of-type {
  background: #444;
  color: #fff;
}

.area-info .area-display {
  background: #1a1a1a;
  padding: 12px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 13px;
}

.area-info .area-display div {
  color: #888;
}

.area-info .area-display div.valid {
  color: #4caf50;
}

.error-message {
  margin-top: 16px;
  padding: 12px;
  background: #442222;
  border: 1px solid #663333;
  border-radius: 4px;
  color: #ff6666;
}

.form-actions {
  display: flex;
  gap: 10px;
  margin-top: 24px;
}

.submit-btn {
  flex: 1;
  padding: 12px;
  border: none;
  border-radius: 4px;
  background: #4a90d9;
  color: #fff;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.2s;
}

.submit-btn:hover:not(:disabled) {
  background: #5a9fe9;
}

.submit-btn:disabled {
  background: #444;
  cursor: not-allowed;
}

.skip-btn {
  padding: 12px 16px;
  border: 1px solid #666;
  border-radius: 4px;
  background: transparent;
  color: #aaa;
  cursor: pointer;
  transition: all 0.2s;
}

.skip-btn:hover {
  border-color: #888;
  color: #fff;
}

.skip-invalid-btn {
  padding: 12px 16px;
  border: 1px solid #aa3333;
  border-radius: 4px;
  background: transparent;
  color: #ff6666;
  cursor: pointer;
  transition: all 0.2s;
}

.skip-invalid-btn:hover {
  background: #aa3333;
  color: #fff;
}
</style>
