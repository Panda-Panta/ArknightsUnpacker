<script setup>
import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue'
import { ArrowLeft } from '@element-plus/icons-vue'

const props = defineProps({
  run: { type: Function, required: true },
  state: { type: Object, required: true },
  token: { type: String, required: true },
})
const emit = defineEmits(['close'])

const catalog = shallowRef({ loading: true, groups: [], diagnostics: [] })
const form = reactive({ group_id: '', base_id: '', face_id: '', x: 0, y: 0, width: 1, height: 1 })
const waiting = ref(false)
const imageFailed = ref(false)
const zoom = ref(0)
const group = computed(() => catalog.value.groups.find((item) => item.id === form.group_id))
const baseEntries = computed(() => (group.value?.entries || []).filter((item) => ['base', 'whole'].includes(item.role)))
const faceEntries = computed(() => (group.value?.entries || []).filter((item) => ['face', 'whole'].includes(item.role)))
const face = computed(() => faceEntries.value.find((entry) => entry.id === form.face_id))
const overlay = computed(() => face.value?.role === 'face')
const fields = [
  { key: 'x', label: 'X（从左向右）', min: -32768, max: 32768 },
  { key: 'y', label: 'Y（从上向下）', min: -32768, max: 32768 },
  { key: 'width', label: '表情宽度', min: 1, max: 16384 },
  { key: 'height', label: '表情高度', min: 1, max: 16384 },
]
const valid = computed(() => Boolean(group.value && form.base_id) && fields.every(({ key }) => Number.isInteger(form[key])))
const formKey = computed(() => valid.value ? JSON.stringify({ ...form }) : '')
const current = computed(() => {
  const preview = catalog.value.preview
  return formKey.value && preview && Object.entries(form).every(([key, value]) => preview.options[key] === value)
    ? preview : null
})
const previewing = computed(() => waiting.value || catalog.value.previewLoading)
const placement = computed(() => {
  if (face.value?.role === 'whole') return '整幅替换会使用该姿态的完整图片。'
  if (!overlay.value) return '当前仅使用所选底图。'
  return '以底图左上角为原点。超出画布的部分会被裁剪。'
})

let readSequence = 0
let renderSequence = 0
let previewTimer

function entryLabel(entry) {
  const name = entry.alias || entry.name || entry.id
  const size = entry.width && entry.height ? `（${entry.width} × ${entry.height}）` : ''
  return name + size + (entry.role === 'whole' ? ' · 整幅替换' : '')
}

function resetGroup(id = form.group_id) {
  const next = catalog.value.groups.find((item) => item.id === id)
  if (!next) return
  const entries = next.entries || []
  const position = next.face_pos || [0, 0]
  const size = next.face_size || [1, 1]
  Object.assign(form, {
    group_id: id,
    base_id: next.base_id || entries.find((entry) => ['base', 'whole'].includes(entry.role))?.id || '',
    face_id: entries.find((entry) => ['face', 'whole'].includes(entry.role))?.id || '',
    x: Math.max(-32768, Math.min(32768, Math.round(position[0]))),
    y: Math.max(-32768, Math.min(32768, Math.round(position[1]))),
    width: Math.max(1, Math.min(16384, Math.round(size[0]))),
    height: Math.max(1, Math.min(16384, Math.round(size[1]))),
  })
}

async function refresh() {
  const sequence = ++readSequence
  const data = await props.run('characterState', { token: props.token })
  if (sequence !== readSequence) return
  if (!data) {
    catalog.value = { ...catalog.value, loading: false, previewLoading: false,
      error: '无法读取角色表情工作台，请返回资源列表后重新打开。' }
    return
  }
  catalog.value = data
  if (!form.group_id && data.groups.length) resetGroup(data.groups[0].id)
}

watch(() => props.token, () => {
  ++renderSequence
  window.clearTimeout(previewTimer)
  waiting.value = false
  catalog.value = { loading: true, groups: [], diagnostics: [] }
  form.group_id = ''
  void refresh()
}, { immediate: true })

watch(() => props.state, () => {
  if (catalog.value.loading || previewing.value) void refresh()
})

watch(formKey, (key) => {
  const sequence = ++renderSequence
  window.clearTimeout(previewTimer)
  imageFailed.value = false
  zoom.value = 0
  waiting.value = Boolean(key)
  if (!key) return
  const token = props.token
  const options = JSON.parse(key)
  previewTimer = window.setTimeout(async () => {
    const reply = await props.run('characterPreview', { token, options })
    if (sequence !== renderSequence) return
    if (reply === undefined) {
      waiting.value = false
      catalog.value = { ...catalog.value, previewLoading: false, preview: null,
        previewError: '无法提交合成预览，请检查位置和尺寸。' }
      return
    }
    await refresh()
    if (sequence === renderSequence) waiting.value = false
  }, 250)
})

function exportCurrent() {
  if (current.value && !previewing.value && !imageFailed.value) {
    return props.run('characterExport', { token: props.token, options: { ...form } })
  }
}

onBeforeUnmount(() => {
  ++readSequence
  ++renderSequence
  window.clearTimeout(previewTimer)
})
</script>

<template>
  <section class="character-page" aria-label="表情差分制作">
    <header class="character-header">
      <el-button :icon="ArrowLeft" @click="emit('close')">返回资源列表</el-button>
      <div class="character-title">
        <h2>表情差分制作</h2>
        <span :title="catalog.name">{{ catalog.name }}</span>
      </div>
    </header>

    <div v-if="catalog.loading" class="character-empty" role="status">正在读取角色表情配置…</div>
    <div v-else-if="catalog.error" class="character-empty" role="alert">{{ catalog.error }}</div>
    <div v-else-if="!catalog.groups.length" class="character-empty">
      <p>此资源没有可制作的角色表情配置。</p>
      <ul v-if="catalog.diagnostics.length" class="character-diagnostics">
        <li v-for="(message, index) in catalog.diagnostics" :key="index">{{ message }}</li>
      </ul>
    </div>
    <div v-else class="character-body">
      <el-form class="character-controls" label-position="top" @submit.prevent>
        <el-form-item label="姿态组">
          <el-select :model-value="form.group_id" @update:model-value="resetGroup">
            <el-option v-for="item in catalog.groups" :key="item.id" :value="item.id" :label="item.title || item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="底图">
          <el-select v-model="form.base_id">
            <el-option v-for="entry in baseEntries" :key="entry.id" :value="entry.id" :label="entryLabel(entry)" />
          </el-select>
        </el-form-item>
        <el-form-item label="表情">
          <el-select v-model="form.face_id" :empty-values="[null, undefined]">
            <el-option value="" label="不叠加表情（仅底图）" />
            <el-option v-for="entry in faceEntries" :key="entry.id" :value="entry.id" :label="entryLabel(entry)" />
          </el-select>
        </el-form-item>
        <div class="character-geometry">
          <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
            <el-input-number v-model="form[field.key]" :min="field.min" :max="field.max" :precision="0"
              :disabled="!overlay" :aria-label="field.label" controls-position="right" />
          </el-form-item>
        </div>
        <p class="character-hint">{{ placement }}</p>
        <el-button @click="resetGroup()">恢复本组配置</el-button>
        <details v-if="catalog.diagnostics.length" class="character-diagnostics">
          <summary>配置诊断（{{ catalog.diagnostics.length }}）</summary>
          <ul>
            <li v-for="(message, index) in catalog.diagnostics" :key="index">{{ message }}</li>
          </ul>
        </details>
      </el-form>

      <section class="character-preview" aria-label="合成预览">
        <header class="character-preview-tools">
          <strong>合成预览</strong>
          <span v-if="current">{{ current.width }} × {{ current.height }} px</span>
          <div class="character-zoom">
            <el-button :disabled="!current || zoom === 0" @click="zoom = 0">适应画布</el-button>
            <el-button :disabled="!current || zoom === 100" @click="zoom = 100">原始尺寸</el-button>
          </div>
        </header>
        <div v-if="previewing" class="character-empty" role="status">正在合成预览…</div>
        <div v-else-if="catalog.previewError || imageFailed" class="character-empty" role="alert">
          {{ catalog.previewError || '无法加载合成图片。' }}
        </div>
        <div v-else-if="current" class="character-canvas" :class="{ 'character-canvas-fit': zoom === 0 }">
          <img :key="current.url" :src="current.url" :width="current.width" :height="current.height"
            alt="当前表情合成" @error="imageFailed = true">
        </div>
        <div v-else class="character-empty">选择底图和表情后自动生成预览。</div>
      </section>
    </div>

    <footer class="character-actions">
      <el-button :disabled="catalog.loading || !catalog.groups.length"
        @click="run('characterBatch', { token })">批量导出全部表情</el-button>
      <el-button type="primary" :disabled="!current || previewing || imageFailed"
        @click="exportCurrent">导出当前合成</el-button>
    </footer>
  </section>
</template>

<style scoped>
.character-page {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--surface);
}

.character-header, .character-actions, .character-preview-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 19px;
}

.character-header, .character-preview-tools {
  border-bottom: 1px solid var(--rule);
  background: var(--wash);
}

.character-title { min-width: 0; }
.character-title h2 { margin: 0 0 3px; font-size: 17px; }
.character-title span { display: block; overflow: hidden; color: var(--muted); text-overflow: ellipsis; white-space: nowrap; }

.character-body {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: clamp(275px, 27vw, 345px) minmax(0, 1fr);
}

.character-controls {
  overflow: auto;
  padding: 18px 20px;
  border-right: 1px solid var(--rule);
}

.character-controls :deep(.el-select), .character-geometry :deep(.el-input-number) { width: 100%; }
.character-geometry { display: grid; gap: 0 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.character-hint { margin: 0 0 12px; color: var(--muted); line-height: 1.55; }
.character-diagnostics { margin: 16px 0 0; overflow-wrap: anywhere; color: var(--muted); line-height: 1.55; }
.character-diagnostics ul { padding-left: 20px; }

.character-preview { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.character-preview-tools span { color: var(--muted); font-variant-numeric: tabular-nums; }
.character-zoom { display: flex; gap: 8px; margin-left: auto; }
.character-zoom :deep(.el-button + .el-button), .character-actions :deep(.el-button + .el-button) { margin-left: 0; }

.character-canvas {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px;
  background: repeating-conic-gradient(var(--pale-blue) 0 25%, var(--wash) 0 50%) 0 / 24px 24px;
}

.character-canvas img { display: block; }
.character-canvas-fit { display: grid; place-items: center; }
.character-canvas-fit img { width: auto; height: auto; max-width: 100%; max-height: 100%; object-fit: contain; }

.character-empty {
  flex: 1;
  overflow: auto;
  align-content: center;
  padding: 24px;
  color: var(--muted);
  text-align: center;
  overflow-wrap: anywhere;
}

.character-empty ul { width: fit-content; margin-inline: auto; text-align: left; }
.character-actions { justify-content: flex-end; margin-top: auto; border-top: 1px solid var(--rule); }
</style>
