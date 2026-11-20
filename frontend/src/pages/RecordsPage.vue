<script setup>
import { computed, onUnmounted, reactive, ref, shallowRef, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import WorkbenchTable from '../components/WorkbenchTable.vue'
import { fullTime, shortTime } from '../format.js'

const props = defineProps({
  run: { type: Function, required: true },
  state: { type: Object, required: true },
  mode: { type: String, required: true },
})
const emit = defineEmits(['open-resource'])

const PAGE_SIZE = 100
const DEFAULT_FILTERS = { scope: 'either', query: '', category: '', source: '', abOnly: false, excludeDeleted: true }
const SCOPE_OPTIONS = [
  { value: 'recent', label: '最近写入' },
  { value: 'changes', label: '相对文件基线变化' },
  { value: 'either', label: '任一命中' },
  { value: 'both', label: '两者交集' },
]
const columns = [
  { key: 'path', label: '文件路径', minWidth: 265 },
  { key: 'category', label: '用途', minWidth: 103 },
  { key: 'source', label: '状态 / 来源', minWidth: 145 },
  { key: 'size', label: '大小', minWidth: 82 },
  { key: 'modified', label: '修改时间', minWidth: 113 },
  { key: 'observed', label: '首次观测', minWidth: 113 },
  { key: 'evidence', label: '检测依据', minWidth: 158 },
]
const updateView = shallowRef({ rows: [], total: 0, categories: [], sources: [], diagnostics: [] })
const jobs = shallowRef({ rows: [], paused: false, active: '', progress: null })
const jobDetails = shallowRef(null)
const updatesMode = computed(() => props.mode === 'updates')
const filters = reactive({ ...DEFAULT_FILTERS })
const sort = reactive({ key: 'path', descending: false })
const page = ref(1)
const selectedUpdate = ref('')
const checked = ref(new Set())
const imageIds = ref(new Set())
const loading = ref(false)
const selectedJob = ref('')
const selectedArtifactIndex = ref(0)
const resource = computed(() => updateView.value.rows.find((row) => row.id === selectedUpdate.value))
const job = computed(() => jobs.value.rows.find((row) => row.id === selectedJob.value))
const artifact = computed(() => jobDetails.value?.artifacts[selectedArtifactIndex.value])
const progress = computed(() => {
  const value = jobs.value.progress
  if (!value || !(value.total > 0) || value.current == null) return null
  return Math.max(0, Math.min(100, Math.round(100 * value.current / value.total)))
})
let readSequence = 0
let detailSequence = 0
let filterTimer
let lastIndex = null

function filterStorageKey() {
  return 'arknights-unpacker-update-filters:' + props.state.root
}

watch(() => props.state.root, () => {
  let stored
  try {
    stored = props.state.root ? JSON.parse(localStorage.getItem(filterStorageKey())) : null
  } catch {
    stored = null
  }
  for (const key of Object.keys(DEFAULT_FILTERS)) {
    filters[key] = typeof stored?.[key] === typeof DEFAULT_FILTERS[key] ? stored[key] : DEFAULT_FILTERS[key]
  }
}, { immediate: true })

function updatePayload() {
  return { ...filters, sort: sort.key, descending: sort.descending, page: page.value, pageSize: PAGE_SIZE }
}

async function refreshUpdates() {
  const sequence = ++readSequence
  loading.value = true
  try {
    const view = await props.run('recordsUpdates', updatePayload())
    if (!view || sequence !== readSequence || !updatesMode.value) return
    updateView.value = view
    const maxPage = Math.max(1, Math.ceil(view.total / PAGE_SIZE))
    if (page.value > maxPage) page.value = maxPage
  } finally {
    if (sequence === readSequence) loading.value = false
  }
}

function changeChecked(next) {
  checked.value = next
  const images = new Set([...imageIds.value].filter((id) => next.has(id)))
  for (const row of updateView.value.rows) {
    if (row.images && next.has(row.id)) images.add(row.id)
  }
  imageIds.value = images
}

async function selectAllUpdates() {
  const sequence = readSequence
  const data = await props.run('recordsUpdateSelection', updatePayload())
  if (!data || !updatesMode.value || sequence !== readSequence) return
  checked.value = new Set(data.ids)
  imageIds.value = new Set(data.imageIds)
}

function clearSelection() {
  checked.value = new Set()
  imageIds.value = new Set()
}

function sortUpdates(key) {
  sort.descending = sort.key === key && !sort.descending
  sort.key = key
}

async function openResource(row) {
  if (!row?.previewable) return
  const resourceRow = await props.run('recordsOpen', { id: row.id })
  if (resourceRow && updatesMode.value) emit('open-resource', resourceRow)
}

function extractUpdates(images = false) {
  const ids = images ? [...imageIds.value] : [...checked.value]
  if (ids.length) return props.run('recordsExtract', { ids, images })
}

async function selectJob(row, resetArtifact = true) {
  const sequence = ++detailSequence
  selectedJob.value = row.id
  if (resetArtifact) {
    jobDetails.value = null
    selectedArtifactIndex.value = 0
  }
  const details = await props.run('recordsJobDetails', { id: row.id })
  if (!details || sequence !== detailSequence || updatesMode.value) return
  jobDetails.value = details
  if (selectedArtifactIndex.value >= details.artifacts.length) selectedArtifactIndex.value = 0
}

async function refreshJobs() {
  const sequence = ++readSequence
  const data = await props.run('recordsJobs')
  if (!data || sequence !== readSequence || updatesMode.value) return
  const previous = job.value
  jobs.value = data
  if (previous && job.value && previous.status !== job.value.status) {
    await selectJob(job.value, false)
  } else if (selectedJob.value && !job.value) {
    selectedJob.value = ''
    jobDetails.value = null
  }
}

async function jobAction(operation, extra = {}) {
  if (operation === 'clear') {
    try {
      await ElMessageBox.confirm('清理成功任务的历史记录，已导出的文件会保留。', '清理成功任务', {
        confirmButtonText: '清理记录', cancelButtonText: '取消', type: 'warning',
      })
    } catch {
      return
    }
  }
  await props.run('recordsJobAction', { operation, id: selectedJob.value, ...extra })
  await refreshJobs()
}

watch(() => [props.mode, props.state], () => {
  if (!updatesMode.value) {
    void refreshJobs()
    return
  }
  const index = JSON.stringify([props.state.root, props.state.revision, props.state.hours])
  if (lastIndex === index) return
  lastIndex = index
  selectedUpdate.value = ''
  clearSelection()
  void refreshUpdates()
}, { immediate: true })

watch(() => props.mode, (mode) => {
  window.clearTimeout(filterTimer)
  if (mode === 'updates') void refreshUpdates()
})

watch(filters, () => {
  if (!updatesMode.value) return
  if (props.state.root) {
    try {
      localStorage.setItem(filterStorageKey(), JSON.stringify(filters))
    } catch {
      // Keep filtering available without browser storage.
    }
  }
  window.clearTimeout(filterTimer)
  ++readSequence
  clearSelection()
  selectedUpdate.value = ''
  if (page.value !== 1) page.value = 1
  else filterTimer = window.setTimeout(refreshUpdates, 130)
})
watch(sort, () => {
  if (!updatesMode.value) return
  window.clearTimeout(filterTimer)
  if (page.value !== 1) page.value = 1
  else void refreshUpdates()
})
watch(page, () => {
  if (updatesMode.value) void refreshUpdates()
})
onUnmounted(() => window.clearTimeout(filterTimer))
</script>

<template>
  <section v-if="updatesMode" class="records-screen">
    <header class="records-heading">
      <h2>更新记录</h2>
      <span v-if="updateView.scanTime" class="muted">
        {{ fullTime(updateView.scanTime) }} · 近 {{ updateView.hours }} 小时 ·
        {{ updateView.hasBaseline ? '已有文件基线' : '首次发现，历史未知' }}
      </span>
    </header>
    <div class="records-filters">
      <el-select v-model="filters.scope" class="records-scope" aria-label="显示范围">
        <el-option v-for="scope in SCOPE_OPTIONS" :key="scope.value" v-bind="scope" />
      </el-select>
      <el-input v-model="filters.query" class="records-search" clearable
        placeholder="搜索文件名、路径或用途" aria-label="搜索更新记录" />
      <el-select v-model="filters.category" class="records-filter" aria-label="目录用途">
        <el-option label="全部用途" value="" />
        <el-option v-for="category in updateView.categories" :key="category" :label="category" :value="category" />
      </el-select>
      <el-select v-model="filters.source" class="records-filter" aria-label="资源来源">
        <el-option label="全部来源" value="" />
        <el-option v-for="source in updateView.sources" :key="source" :label="source" :value="source" />
      </el-select>
      <el-checkbox v-model="filters.abOnly">仅 .ab</el-checkbox>
      <el-checkbox v-model="filters.excludeDeleted">排除已删除文件</el-checkbox>
    </div>
    <el-alert v-if="updateView.diagnostics.length" type="warning" show-icon :closable="false"
      :title="updateView.diagnostics[0]" :description="updateView.diagnostics.slice(1).join('；')" />
    <div class="records-table">
      <WorkbenchTable :rows="updateView.rows" :columns="columns" :sort="sort" :loading="loading"
        :checked="checked" :focus-id="selectedUpdate" @sort="sortUpdates" @focus="selectedUpdate = $event.id"
        @activate="openResource" @selection="changeChecked">
        <template #empty>
          {{ updateView.scanTime ? '没有符合当前条件的更新记录。' : '扫描游戏目录后可查看写入与文件变化。' }}
        </template>
      </WorkbenchTable>
    </div>
    <footer class="records-footer">
      <span class="muted">{{ updateView.total }} 条记录 · 已勾选 {{ checked.size }} 项</span>
      <el-button link :disabled="!updateView.total || loading" @click="selectAllUpdates">全选当前结果</el-button>
      <el-button v-if="checked.size" link @click="clearSelection">清除勾选</el-button>
      <el-pagination v-model:current-page="page" :page-size="PAGE_SIZE" :total="updateView.total"
        layout="prev, pager, next" hide-on-single-page small />
      <div class="records-actions">
        <el-button :disabled="!resource?.previewable" @click="openResource(resource)">查看包内对象</el-button>
        <el-button :disabled="!checked.size" @click="extractUpdates()">解包所选文件</el-button>
        <el-button type="primary" :disabled="!imageIds.size" @click="extractUpdates(true)">导出所选包内图片</el-button>
      </div>
    </footer>
  </section>
  <section v-else class="records-screen">
    <header class="records-heading">
      <h2>任务记录</h2>
      <div class="records-actions">
        <el-button :disabled="!jobs.active" @click="jobAction('cancel')">取消当前任务</el-button>
        <el-button @click="jobAction('pause')">{{ jobs.paused ? '继续队列' : '暂停队列' }}</el-button>
        <el-button :disabled="!jobs.rows.some((row) => row.status === '成功')" @click="jobAction('clear')">清理成功任务</el-button>
      </div>
    </header>
    <div v-if="jobs.active && jobs.progress" class="records-progress">
      <el-progress v-if="progress !== null" :percentage="progress" />
      <span class="muted" role="status">{{ jobs.progress.message }}</span>
    </div>
    <div class="records-layout">
      <div class="records-table">
        <el-table :data="jobs.rows" row-key="id" height="100%" stripe highlight-current-row
          :current-row-key="selectedJob" empty-text="暂无任务记录" @row-click="selectJob($event)">
          <el-table-column label="任务" prop="title" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" prop="status" min-width="120" />
          <el-table-column label="提交时间" min-width="115">
            <template #default="{ row }">{{ shortTime(row.created) }}</template>
          </el-table-column>
          <el-table-column label="开始时间" min-width="115">
            <template #default="{ row }">{{ shortTime(row.started) }}</template>
          </el-table-column>
          <el-table-column label="输出位置" prop="output" min-width="180" show-overflow-tooltip />
        </el-table>
      </div>
      <aside v-if="job" class="records-detail">
        <h3>{{ job.title }}</h3>
        <div class="records-detail-actions">
          <el-button size="small" :disabled="!job.retryable" @click="jobAction('retry')">重试</el-button>
          <el-button size="small" :disabled="!job.output" @click="jobAction('output')">打开输出目录</el-button>
        </div>
        <div v-if="jobDetails" class="records-artifacts">
          <div v-if="jobDetails.artifacts.length">
            <el-select v-model="selectedArtifactIndex" class="artifact-select" aria-label="选择产物">
              <el-option v-for="(item, index) in jobDetails.artifacts" :key="item.path"
                :label="item.name + (item.exists ? '' : '（文件缺失）')" :value="index" />
            </el-select>
            <img v-if="artifact?.kind === 'image'" :src="artifact.url" :alt="artifact.name" class="records-image">
            <audio v-else-if="artifact?.kind === 'audio'" :key="artifact.url" :src="artifact.url" controls />
            <video v-else-if="artifact?.kind === 'video'" :key="artifact.url" :src="artifact.url" controls />
            <el-button link :disabled="!artifact?.exists"
              @click="jobAction('artifact', { path: artifact.path })">打开所选产物</el-button>
          </div>
          <p v-else class="muted">暂无可确认完整的产物。</p>
          <pre v-if="jobDetails.error" class="records-error">{{ jobDetails.error }}</pre>
          <details v-if="jobDetails.errors.length">
            <summary>失败详情（{{ jobDetails.errors.length }}）</summary>
            <pre>{{ JSON.stringify(jobDetails.errors, null, 2) }}</pre>
          </details>
          <details v-if="jobDetails.skipped.length">
            <summary>跳过详情（{{ jobDetails.skipped.length }}）</summary>
            <pre>{{ JSON.stringify(jobDetails.skipped, null, 2) }}</pre>
          </details>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.records-screen {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}
.records-heading, .records-filters, .records-footer, .records-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
}
.records-heading h2, .records-detail h3 { margin: 0 }
.records-scope { width: 173px }
.records-filter { width: 135px }
.records-search { flex: 1 1 220px }
.records-table { flex: 1; min-width: 0; min-height: 0 }
.records-footer { justify-content: flex-start }
.records-actions { margin-left: auto }
.records-layout { flex: 1; min-height: 0; display: flex; align-items: stretch; gap: 12px }
.records-detail {
  flex: 0 0 clamp(245px, 27vw, 370px);
  overflow: auto;
  border-left: 1px solid var(--el-border-color);
  padding: 8px 0 8px 12px;
}
.records-detail-actions, .records-artifacts { margin-top: 12px }
.records-image, .records-artifacts video { display: block; max-width: 100%; max-height: 320px; margin: 8px auto; object-fit: contain }
.records-artifacts audio { width: 100%; margin-top: 8px }
.artifact-select { width: 100% }
.records-error { color: var(--el-color-danger) }
.records-detail pre { margin: 8px 0; white-space: pre-wrap; overflow-wrap: anywhere }
.records-detail details { margin-top: 8px }
.records-detail summary { cursor: pointer }
.records-progress { min-height: 22px; display: grid; gap: 6px }
</style>
