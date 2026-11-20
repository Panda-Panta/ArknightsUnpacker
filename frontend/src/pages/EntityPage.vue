<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({ run: Function, state: Object, kind: String })
const operator = computed(() => props.kind === 'operators')
const title = computed(() => operator.value ? '干员资料' : '模组更新')
const query = ref('')
const status = ref('')
const rows = ref([])
const version = ref('')
const hasBaseline = ref(false)
const focused = ref('')
const selected = ref([])
const profile = ref(null)
const listBusy = ref(false)
const profileBusy = ref(false)
const page = ref(1)
const pageSize = 60
const visibleRows = computed(() => rows.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const currentProfileRow = computed(() => rows.value.find(row => row.id === focused.value))
const spec = reactive({ phase: null, level: undefined, potential: undefined, trust: 200, module_id: '', module_level: 3 })
const reportIds = computed(() => selected.value.length ? selected.value : focused.value ? [focused.value] : [])
const labels = { current: '当前', added: '新增', modified: '已变化', removed: '已移除' }
const tabSection = ref('')
const detailBox = ref(null)
const groups = computed(() => [...new Set((profile.value?.blocks || []).map(block => block.group))].filter(Boolean))
const previewOpen = ref(false)
const previewLoading = ref(false)
const previewToken = ref('')
const previewFiles = ref([])
const previewItem = ref(0)
const previewError = ref('')
const previewRequest = ref(null)
const previewTheme = ref('')
const previewFont = ref(null)
const currentArtifact = computed(() => previewFiles.value[previewItem.value])
let listVersion = 0
let profileVersion = 0
let previewVersion = 0
let listTimer
let profileTimer
let previewTimer

function refreshList() {
  clearTimeout(listTimer)
  const request = ++listVersion
  listTimer = setTimeout(async () => {
    listBusy.value = true
    const result = await props.run('entitiesList', { kind: props.kind, query: query.value, status: status.value })
    if (request !== listVersion) return
    listBusy.value = false
    if (!result) return
    rows.value = result.rows
    version.value = result.version
    hasBaseline.value = result.baseline
    page.value = 1
    const ids = new Set(rows.value.map(row => row.id))
    selected.value = selected.value.filter(id => ids.has(id))
    if (!ids.has(focused.value)) selectRow(rows.value[0])
    else loadProfile()
  }, 110)
}

function loadProfile() {
  clearTimeout(profileTimer)
  const request = ++profileVersion
  if (!focused.value) {
    profile.value = null
    profileBusy.value = false
    return
  }
  profileTimer = setTimeout(async () => {
    profileBusy.value = true
    const result = await props.run('entitiesProfile', { kind: props.kind, id: focused.value, spec: { ...spec } })
    if (request !== profileVersion) return
    profileBusy.value = false
    profile.value = result || null
  }, 100)
}

function selectRow(row) {
  focused.value = row?.id || ''
  spec.module_id = ''
  tabSection.value = ''
  loadProfile()
}

function toggle(id, enabled) {
  selected.value = enabled ? [...new Set([...selected.value, id])] : selected.value.filter(key => key !== id)
}

async function jumpTo(section) {
  await nextTick()
  const block = [...(detailBox.value?.querySelectorAll('[data-group]') || [])].find(item => item.dataset.group === section)
  if (block && detailBox.value) detailBox.value.scrollTop += block.getBoundingClientRect().top - detailBox.value.getBoundingClientRect().top
}

function requestPayload(onlyNew = false) {
  return { kind: props.kind, ids: [...reportIds.value], spec: { ...spec }, onlyNew }
}

async function exportReport(onlyNew = false) {
  await props.run('entitiesReport', requestPayload(onlyNew))
}

async function releasePreview() {
  clearTimeout(previewTimer)
  ++previewVersion
  const token = previewToken.value
  previewToken.value = ''
  if (token) await props.run('entitiesClosePreview', { token })
}

async function renderPreview() {
  await releasePreview()
  const request = ++previewVersion
  previewLoading.value = true
  previewFiles.value = []
  previewError.value = ''
  previewItem.value = 0
  const options = {}
  if (previewTheme.value) options.theme = previewTheme.value
  if (previewFont.value) {
    options.font_path = previewFont.value.path
    options.font_index = previewFont.value.index
  }
  const result = await props.run('entitiesReport', { ...previewRequest.value, preview: true, options })
  if (request !== previewVersion) {
    if (result?.token) await props.run('entitiesClosePreview', { token: result.token })
    return
  }
  if (!result?.token) {
    previewLoading.value = false
    previewError.value = '无法生成资料预览。'
    return
  }
  previewToken.value = result.token
  async function refresh() {
    const report = await props.run('entitiesPreview', { token: result.token })
    if (request !== previewVersion) return
    previewLoading.value = Boolean(report?.loading)
    previewError.value = report?.error || (!report ? '无法读取资料预览。' : '')
    previewFiles.value = report?.files || []
    if (previewLoading.value) previewTimer = setTimeout(refresh, 190)
    else previewItem.value = Math.max(0, previewFiles.value.findIndex(item => item.format === 'png'))
  }
  await refresh()
}

async function previewReport() {
  previewRequest.value = requestPayload()
  previewOpen.value = true
  previewTheme.value = ''
  previewFont.value = null
  await renderPreview()
}

async function changeFont() {
  const font = await props.run('settingsChooseFont', { path: previewFont.value?.path || '' })
  if (font) {
    previewFont.value = font
    await renderPreview()
  }
}

async function exportPreview() {
  if (!previewRequest.value) return
  const options = {}
  if (previewTheme.value) options.theme = previewTheme.value
  if (previewFont.value) {
    options.font_path = previewFont.value.path
    options.font_index = previewFont.value.index
  }
  await props.run('entitiesReport', { ...previewRequest.value, options })
}

watch([query, status, () => props.state.dataRevision], refreshList)
watch(spec, loadProfile)
watch(tabSection, jumpTo)
watch(previewOpen, open => { if (!open) void releasePreview() })
onMounted(refreshList)
onBeforeUnmount(() => {
  clearTimeout(listTimer)
  clearTimeout(profileTimer)
  ++listVersion
  ++profileVersion
  void releasePreview()
})
</script>

<template>
  <section class="entity-page">
    <header class="entity-header">
      <h2>{{ title }}</h2>
      <span v-if="version" class="muted">{{ version }}</span>
      <el-button :disabled="!state.root || state.busy" @click="run('loadData')">解析核心数据</el-button>
    </header>
    <div class="entity-main">
      <div class="entity-list">
        <div class="entity-filters">
          <el-input v-model="query" clearable :placeholder="operator ? '搜索干员姓名或编号' : '搜索干员或模组'" />
          <el-select v-model="status" aria-label="资料状态" :empty-values="[null, undefined]">
            <el-option value="" label="全部状态" />
            <el-option value="added" label="仅看新增" />
            <el-option value="modified" label="仅看变化" />
          </el-select>
        </div>
        <p v-if="version && !hasBaseline" class="muted">历史未知 · 需要可比快照才能确认新增</p>
        <el-table v-loading="listBusy" :data="visibleRows" row-key="id" height="100%" stripe
          :row-class-name="({ row }) => focused === row.id ? 'is-checked-row' : ''" @row-click="selectRow"
          :empty-text="version ? '没有符合条件的资料' : '请先解析核心数据'">
          <el-table-column width="42" align="center">
            <template #header>
              <el-checkbox aria-label="勾选全部筛选结果" :disabled="!rows.length"
                :model-value="Boolean(rows.length) && selected.length === rows.length"
                :indeterminate="selected.length > 0 && selected.length < rows.length"
                @change="selected = $event ? rows.map(row => row.id) : []" />
            </template>
            <template #default="{ row }">
              <span @click.stop><el-checkbox :model-value="selected.includes(row.id)" :aria-label="'勾选 ' + row.name"
                @change="toggle(row.id, $event)" /></span>
            </template>
          </el-table-column>
          <el-table-column v-if="!operator" prop="char_name" label="干员" min-width="80" show-overflow-tooltip />
          <el-table-column prop="name" :label="operator ? '干员' : '模组'" min-width="135" show-overflow-tooltip />
          <el-table-column label="状态" width="72">
            <template #default="{ row }">{{ labels[row.status] ?? row.status }}</template>
          </el-table-column>
        </el-table>
        <div class="entity-pagination">
          <span>{{ rows.length }} 项<span v-if="selected.length"> · 已勾选 {{ selected.length }} 项</span></span>
          <el-pagination v-model:current-page="page" :page-size="pageSize" :total="rows.length" small
            layout="prev, pager, next" :pager-count="5" hide-on-single-page />
        </div>
      </div>
      <div class="entity-detail">
        <div v-if="currentProfileRow" class="entity-options">
          <template v-if="operator">
            <el-select v-model="spec.phase" aria-label="精英阶段" placeholder="最高精英阶段" clearable :value-on-clear="null">
              <el-option :value="0" label="精英 0" /><el-option :value="1" label="精英 1" /><el-option :value="2" label="精英 2" />
            </el-select>
            <el-input-number v-model="spec.level" aria-label="等级" placeholder="最高等级" :min="1" :max="90" :controls="false" />
            <el-input-number v-model="spec.potential" aria-label="潜能" placeholder="满潜" :min="1" :max="6" :controls="false" />
            <label>信赖 <el-input-number v-model="spec.trust" :min="0" :max="200" :controls="false" /></label>
            <el-select v-model="spec.module_id" aria-label="佩戴模组" :empty-values="[null, undefined]">
              <el-option value="" label="不佩戴模组" />
              <el-option v-for="module in profile?.modules || []" :key="module.id" :value="module.id" :label="module.name" />
            </el-select>
            <el-select v-if="spec.module_id" v-model="spec.module_level" aria-label="模组等级">
              <el-option v-for="level in [1, 2, 3]" :key="level" :value="level" :label="'模组 ' + level + ' 级'" />
            </el-select>
          </template>
          <el-select v-if="groups.length" v-model="tabSection" aria-label="资料目录" placeholder="跳转至章节">
            <el-option v-for="group in groups" :key="group" :value="group" :label="group" />
          </el-select>
        </div>
        <div ref="detailBox" v-loading="profileBusy" class="entity-details">
          <el-empty v-if="!profile && !profileBusy" description="选择资料以查看详情" />
          <template v-else-if="profile">
            <article v-for="(block, index) in profile.blocks" :key="index" :data-group="block.group" class="profile-block">
              <h3>{{ block.title }}</h3>
              <dl v-if="block.rows.length">
                <template v-for="([key, text], row) in block.rows" :key="row"><dt>{{ key }}</dt><dd>{{ text }}</dd></template>
              </dl>
              <table v-if="block.columns?.length">
                <thead><tr><th v-for="(column, col) in block.columns" :key="col">{{ column }}</th></tr></thead>
                <tbody><tr v-for="(cells, row) in block.cells" :key="row"><td v-for="(cell, col) in cells" :key="col">{{ cell }}</td></tr></tbody>
              </table>
              <dl v-if="block.notes?.length" class="muted">
                <template v-for="([key, text], row) in block.notes" :key="row"><dt>{{ key }}</dt><dd>{{ text }}</dd></template>
              </dl>
            </article>
          </template>
        </div>
      </div>
    </div>
    <footer class="entity-actions">
      <el-button :disabled="!hasBaseline || !rows.some(row => row.status === 'added')" @click="exportReport(true)">导出新增资料</el-button>
      <el-button :disabled="!reportIds.length" @click="previewReport">预览选中资料</el-button>
      <el-button type="primary" :disabled="!reportIds.length" @click="exportReport()">导出选中资料</el-button>
    </footer>
    <el-dialog v-model="previewOpen" title="资料预览" width="min(92vw, 1050px)" destroy-on-close>
      <div class="preview-actions">
        <el-select v-model="previewTheme" aria-label="预览主题" :empty-values="[null, undefined]" @change="renderPreview">
          <el-option value="" label="当前导出主题" /><el-option value="light" label="亮色" /><el-option value="dark" label="暗色" />
        </el-select>
        <el-button @click="changeFont">切换预览字体…</el-button>
        <el-select v-if="previewFiles.length" v-model="previewItem" aria-label="预览文件">
          <el-option v-for="(item, index) in previewFiles" :key="item.path" :value="index" :label="item.name" />
        </el-select>
      </div>
      <el-alert v-if="previewError" type="warning" :closable="false" :title="previewError" />
      <div v-loading="previewLoading" class="report-preview">
        <img v-if="currentArtifact?.format === 'png'" :src="currentArtifact.url" :alt="currentArtifact.name" />
        <el-button v-else-if="currentArtifact" @click="run('entitiesOpenArtifact', { token: previewToken, index: previewItem })">
          打开 {{ currentArtifact.name }}
        </el-button>
      </div>
      <template #footer>
        <el-button v-if="currentArtifact?.format === 'png'" @click="run('entitiesSaveImage', { token: previewToken, index: previewItem })">保存原图…</el-button>
        <el-button type="primary" :disabled="previewLoading || !previewFiles.length" @click="exportPreview">正式导出</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.entity-page { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.entity-header, .entity-actions { display: flex; align-items: center; gap: 14px; padding: 14px 20px; background: var(--wash); border-bottom: 1px solid var(--rule); }
.entity-header h2 { margin: 0; font-size: 23px; }
.entity-header .el-button { margin-left: auto; }
.entity-main { flex: 1; display: grid; grid-template-columns: minmax(290px, 30%) minmax(0, 1fr); min-height: 0; }
.entity-list, .entity-detail { display: flex; flex-direction: column; min-height: 0; }
.entity-list { padding: 14px; border-right: 1px solid var(--rule); }
.entity-filters, .entity-options, .preview-actions { display: flex; align-items: center; gap: 9px; }
.entity-filters { margin-bottom: 10px; }
.entity-filters .el-select { flex: 0 0 118px; }
.entity-list p { margin: 0 0 8px; font-size: 12px; }
.entity-list .el-table { min-height: 0; flex: 1; }
.entity-pagination { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
.entity-options { padding: 12px 16px; flex-wrap: wrap; border-bottom: 1px solid var(--rule); }
.entity-options .el-select { width: 134px; }
.entity-options .el-input-number { width: 82px; }
.entity-options label { white-space: nowrap; }
.entity-details { min-height: 0; flex: 1; overflow: auto; padding: 16px; }
.profile-block { margin-bottom: 14px; border: 1px solid var(--rule); border-radius: 4px; overflow: auto; }
.profile-block h3 { margin: 0; padding: 8px 12px; background: var(--wash); font-size: 16px; }
.profile-block dl { display: grid; grid-template-columns: minmax(82px, max-content) minmax(0, 1fr); margin: 0; }
.profile-block dt, .profile-block dd, .profile-block th, .profile-block td { margin: 0; padding: 7px 10px; border-bottom: 1px solid var(--rule); white-space: pre-wrap; }
.profile-block dt { background: #f8fbff; }
.profile-block table { width: 100%; border-collapse: collapse; text-align: left; }
.entity-actions { justify-content: flex-end; border-top: 1px solid var(--rule); border-bottom: 0; }
.entity-actions .el-button { margin-left: 0; }
.preview-actions { margin-bottom: 12px; }
.preview-actions .el-select { width: 160px; }
.report-preview { min-height: 160px; max-height: 58vh; overflow: auto; text-align: center; background: var(--wash); }
.report-preview img { display: block; max-width: 100%; margin: 0 auto; }
</style>
