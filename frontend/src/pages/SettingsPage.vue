<script setup>
import SystemFontSelect from '../components/SystemFontSelect.vue'
import { onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({ run: Function, state: Object, mode: String })
const tab = ref(props.mode || 'settings')
const saved = ref(false)
const dataRoot = ref('')
const history = ref([])
const snapshot = ref('')
const options = reactive({
  output_root: '', extraction_mode: 'auto', extraction_kinds: ['image', 'text', 'audio', 'spine'],
  formats: ['png', 'html', 'json', 'txt'], report_width: 1200, report_font_size: 28, report_font_path: '',
  report_font_index: 0, report_theme: 'dark', report_module_image_layout: 'single',
  data_locale: 'unknown', monitor: false, scan_priority: 'data_first', hours: 24, strict_scan: false,
})
const kinds = [['image', '图片'], ['text', '文本／数据'], ['audio', '音频'], ['video', '视频'], ['spine', 'Spine']]
watch(() => props.mode, mode => { tab.value = mode || 'settings' })
watch(() => props.state?.dataRevision, () => { if (tab.value === 'history') void refreshHistory() })
watch(tab, value => { if (value === 'history') void refreshHistory() })

async function load() {
  const result = await props.run('settingsGet')
  if (!result) return
  const config = result.config || result.settings || result
  for (const key of Object.keys(options)) if (key in config) options[key] = config[key]
  dataRoot.value = result.dataRoot || result.data_root || ''
}

async function save() {
  const result = await props.run('settingsSave', { ...options })
  if (result !== undefined) {
    await load()
    saved.value = true
  }
}

async function chooseOutput() {
  const result = await props.run('settingsChooseOutput', { path: options.output_root })
  if (result) options.output_root = result.path || result
}

function useFont(font) {
  options.report_font_path = font.path
  options.report_font_index = font.index
}

async function refreshHistory() {
  const result = await props.run('settingsHistory')
  history.value = Array.isArray(result) ? result : result?.items || result?.snapshots || []
  if (!history.value.some(item => (item.id || item.snapshot_id) === snapshot.value)) snapshot.value = ''
}

async function historyAction(action) {
  await props.run(action, { id: snapshot.value, snapshotId: snapshot.value })
  await refreshHistory()
}

onMounted(async () => {
  await load()
  if (tab.value === 'history') await refreshHistory()
})
</script>

<template>
  <section class="settings-page">
    <h2>设置</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="常规" name="settings">
        <el-form label-position="top" class="settings-form" @change="saved = false">
          <div class="settings-section">
            <h3>文件与输出</h3>
            <el-form-item label="输出目录">
              <div class="settings-line"><el-input v-model="options.output_root" /><el-button @click="chooseOutput">选择目录…</el-button></div>
            </el-form-item>
            <el-form-item label="解包方式">
              <el-select v-model="options.extraction_mode"><el-option value="auto" label="自动处理" /><el-option value="raw" label="原始导出" /></el-select>
            </el-form-item>
            <el-form-item label="资源类型">
              <el-checkbox-group v-model="options.extraction_kinds">
                <el-checkbox v-for="[value, label] in kinds" :key="value" :value="value">{{ label }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
          </div>
          <div class="settings-section">
            <h3>资料导出</h3>
            <el-form-item label="保存格式">
              <el-checkbox-group v-model="options.formats">
                <el-checkbox v-for="format in ['png', 'html', 'json', 'txt']" :key="format" :value="format"
                  :disabled="format === 'json' || format === 'txt'">{{ format.toUpperCase() }}</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <div class="settings-grid">
              <el-form-item label="PNG 画布宽度"><el-input-number v-model="options.report_width" :min="720" :max="3000" :step="120" /></el-form-item>
              <el-form-item label="PNG 字号"><el-input-number v-model="options.report_font_size" :min="18" :max="56" /></el-form-item>
              <el-form-item label="导出主题">
                <el-select v-model="options.report_theme"><el-option value="dark" label="暗色" /><el-option value="light" label="亮色" /></el-select>
              </el-form-item>
              <el-form-item label="模组 PNG 排版">
                <el-select v-model="options.report_module_image_layout"><el-option value="single" label="合成单张长图" /><el-option value="paged" label="按高度分页" /></el-select>
              </el-form-item>
            </div>
            <el-form-item label="导出字体">
              <SystemFontSelect :run="run" label="导出字体"
                :model-value="{ path: options.report_font_path || '', index: options.report_font_index }"
                @update:model-value="useFont" />
            </el-form-item>
          </div>
          <div class="settings-section">
            <h3>运行与历史</h3>
            <el-form-item label="数据区服">
              <el-select v-model="options.data_locale"><el-option value="unknown" label="未知，仅同一安装对比" /><el-option value="zh_CN" label="简体中文／国服" /></el-select>
            </el-form-item>
            <el-checkbox v-model="options.monitor">检测资源清单变化并重新扫描</el-checkbox>
            <div class="settings-line data-path"><span>{{ dataRoot }}</span><el-button @click="run('settingsOpenData')">打开数据目录</el-button></div>
          </div>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="扫描选项" name="scanOptions">
        <el-form class="settings-form settings-section" label-position="top">
          <el-form-item label="检查顺序">
            <el-select v-model="options.scan_priority">
              <el-option value="data_first" label="干员／模组优先" />
              <el-option value="data_only" label="仅检查干员／模组" />
              <el-option value="files_only" label="仅扫描资源文件" />
            </el-select>
          </el-form-item>
          <el-form-item label="最近更新时间（小时）">
            <el-input-number v-model="options.hours" :min="0.01" :max="876000" :precision="2" />
          </el-form-item>
          <el-checkbox v-model="options.strict_scan">严格校验文件摘要</el-checkbox>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="资料快照" name="history">
        <div class="settings-section settings-history">
          <el-select v-model="snapshot" placeholder="选择历史快照">
            <el-option v-for="item in history" :key="item.id || item.snapshot_id" :value="item.id || item.snapshot_id"
              :label="item.label || item.version || item.id || item.snapshot_id" />
          </el-select>
          <div class="settings-line">
            <el-button :disabled="!snapshot || state.busy" @click="historyAction('settingsCompareSnapshot')">比较所选快照</el-button>
            <el-button :disabled="!state.dataRevision || state.busy" @click="historyAction('settingsImportBaseline')">导入历史基线…</el-button>
            <el-button :disabled="!state.dataRevision || state.busy" @click="historyAction('settingsExportSnapshot')">导出当前快照…</el-button>
          </div>
          <el-button type="primary" plain :disabled="!state.root || state.busy" @click="run('loadData')">解析核心数据</el-button>
        </div>
      </el-tab-pane>
    </el-tabs>
    <footer v-if="tab !== 'history'" class="settings-footer">
      <span role="status">{{ saved ? '设置已保存' : '' }}</span>
      <el-button type="primary" :disabled="state.busy" @click="save">保存设置</el-button>
    </footer>
  </section>
</template>

<style scoped>
.settings-page { margin: 0 auto; max-width: 1020px; padding: 24px 30px 32px; }
h2 { margin: 0 0 16px; font-size: 23px; }
h3 { margin: 0 0 14px; font-size: 16px; }
.settings-section { border: 1px solid var(--rule); border-radius: 6px; padding: 16px 18px; margin-bottom: 14px; }
.settings-form .el-form-item { margin-bottom: 14px; }
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; }
.settings-line { display: flex; gap: 9px; align-items: center; width: 100%; }
.settings-line .el-input { flex: 1; min-width: 0; }
.settings-line .el-button { margin: 0; }
.settings-line .el-select { min-width: 175px; }
.data-path { margin-top: 12px; color: var(--muted); overflow-wrap: anywhere; justify-content: space-between; }
.settings-history { display: grid; gap: 12px; justify-items: start; }
.settings-history .el-select { min-width: 350px; }
.settings-footer { display: flex; justify-content: space-between; align-items: center; }
</style>
