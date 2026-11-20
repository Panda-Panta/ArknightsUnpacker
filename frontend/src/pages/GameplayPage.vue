<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'

const props = defineProps({
  run: { type: Function, required: true },
  state: { type: Object, required: true },
})

const sections = [
  { key: 'strategies', label: '策略', empty: '此赛季暂无可用策略资料。' },
  { key: 'bonds', label: '盟约', empty: '此赛季暂无可用盟约资料。' },
  { key: 'shops', label: '调度', empty: '此赛季暂无可用调度配置。普通招募概率未知。' },
  { key: 'levels', label: '关卡资料', empty: '索引中没有与所选赛季匹配的关卡。' },
  { key: 'resources', label: '资源', empty: '索引中暂无可列出的资源。' },
]
const catalog = shallowRef(null)
const catalogError = ref(false)
const modeId = ref('')
const seasonId = ref('')
const section = ref('resources')
const entryKey = ref('')
let catalogRequest = 0
let preferenceRoot = ''
let preferences = {}

function reader(action) {
  const state = shallowRef({ loading: false, error: '', detail: null })
  let request = 0
  let timer

  function clear() {
    request++
    clearTimeout(timer)
    state.value = { loading: false, error: '', detail: null }
  }

  function read(payload) {
    clear()
    state.value = { loading: true, error: '', detail: null }
    const id = request
    async function refresh(nextPayload) {
      const data = await props.run(action, nextPayload)
      if (id !== request) return
      state.value = data || { loading: false, error: '无法读取资料。', detail: null }
      if (data?.loading) timer = setTimeout(() => refresh({ ...payload, retry: false }), 500)
    }
    void refresh(payload)
  }

  return { state, read, clear }
}

const modeReader = reader('gameplayMode')
const levelReader = reader('gameplayLevel')
const modeRead = modeReader.state
const levelRead = levelReader.state
const mode = computed(() => catalog.value?.modes.find((item) => item.id === modeId.value))
const canRead = computed(() => mode.value?.supported && mode.value.available)
const seasonKey = (season) => JSON.stringify([season.activityId, season.seasonId])
const seasons = computed(() => modeRead.value.detail?.seasons || [])
const season = computed(() => seasons.value.find((item) => seasonKey(item) === seasonId.value))
const resources = computed(() => [...new Set([...(mode.value?.resources || []), ...(mode.value?.level_paths || [])])])
const activeSections = computed(() => seasons.value.length ? sections : sections.slice(-1))
const entries = computed(() => {
  if (section.value === 'levels') {
    return (mode.value?.level_paths || []).filter((path) => path.split('/').includes(season.value?.activityId))
      .map((path) => ({ key: path, name: path.split('/').at(-1) }))
  }
  return season.value?.[section.value] || []
})
const entry = computed(() => entries.value.find((item) => item.key === entryKey.value))
const emptyEntries = computed(() => sections.find((item) => item.key === section.value)?.empty)
const storageKey = (root) => `arknights-unpacker-gameplay:${root}`

function loadPreferences(root) {
  try {
    return JSON.parse(localStorage.getItem(storageKey(root))) || {}
  } catch {
    return {}
  }
}

function savePreference(update) {
  preferences = { ...preferences, ...update }
  if (!preferenceRoot) return
  try {
    localStorage.setItem(storageKey(preferenceRoot), JSON.stringify(preferences))
  } catch {
    // In-memory selection still works when persistent storage is unavailable.
  }
}

async function refreshCatalog() {
  const root = props.state.root
  const request = ++catalogRequest
  catalogError.value = false
  if (root !== preferenceRoot) {
    catalog.value = null
    modeId.value = ''
    preferences = loadPreferences(root)
    preferenceRoot = root
  }
  if (!root) return
  const result = await props.run('gameplayCatalog', {})
  if (request !== catalogRequest) return
  if (!result) {
    catalogError.value = true
    return
  }
  const preferred = modeId.value || preferences.mode
  catalog.value = result
  modeId.value = result.modes.some((item) => item.id === preferred)
    ? preferred
    : result.modes[0]?.id || ''
}

function readMode(retry = false) {
  if (canRead.value) modeReader.read({ id: modeId.value, retry })
}

function readLevel(retry = false) {
  if (section.value === 'levels' && entry.value) levelReader.read({ path: entry.value.key, retry })
}

watch([() => props.state.root, () => props.state.revision], refreshCatalog, { immediate: true })

watch(mode, (current) => {
  section.value = 'resources'
  seasonId.value = ''
  modeReader.clear()
  if (!current) return
  savePreference({ mode: current.id })
  readMode()
})

watch(seasons, (items) => {
  if (!items.length) return
  const previous = preferences.seasons?.[modeId.value]
  seasonId.value = items.some((item) => seasonKey(item) === previous) ? previous : seasonKey(items[0])
  section.value = 'strategies'
})

watch(seasonId, (value) => {
  if (value) savePreference({ seasons: { ...preferences.seasons, [modeId.value]: value } })
})

watch([section, season, entries], () => {
  entryKey.value = section.value === 'levels' ? '' : entries.value[0]?.key || ''
})

watch([section, entryKey], () => {
  levelReader.clear()
  readLevel()
})

onBeforeUnmount(() => {
  catalogRequest++
  modeReader.clear()
  levelReader.clear()
})
</script>

<template>
  <section class="gameplay-page" aria-label="玩法资料">
    <header class="gameplay-heading">
      <h2>玩法资料</h2>
      <p v-if="catalog?.scanned">
        已识别 {{ catalog.modes.length }} 种玩法 · 资源版本 {{ catalog.resourceVersion }}
      </p>
      <details v-if="catalog?.diagnostics.length">
        <summary>扫描诊断</summary>
        <p v-for="(note, index) in catalog.diagnostics" :key="index">{{ note }}</p>
      </details>
    </header>

    <p v-if="catalogError" class="gameplay-notice" role="status">
      无法读取玩法列表。<el-button text type="primary" @click="refreshCatalog">重新读取</el-button>
    </p>
    <p v-else-if="!catalog?.scanned" class="gameplay-notice" role="status">
      {{ state.restoring ? '正在恢复玩法资料…' : '请扫描游戏资源以识别玩法。' }}
    </p>
    <p v-else-if="!catalog.modes.length" class="gameplay-notice">本次扫描未识别到特殊玩法。</p>

    <template v-if="mode">
      <el-tabs v-model="modeId" aria-label="玩法">
        <el-tab-pane v-for="item in catalog.modes" :key="item.id" :label="item.name" :name="item.id" />
      </el-tabs>

      <p v-if="!mode.available" class="gameplay-notice">当前安装缺少该玩法的数据资源。</p>
      <p v-else-if="!mode.supported" class="gameplay-notice">已识别该玩法，详情待适配。可查看索引中的资源。</p>
      <p v-else-if="modeRead.loading" class="gameplay-notice" role="status">正在读取玩法资料…</p>
      <p v-else-if="modeRead.error" class="gameplay-notice" role="status">
        玩法资料读取失败 · {{ modeRead.error }}
        <el-button text type="primary" @click="readMode(true)">重试解析</el-button>
      </p>

      <div v-if="season" class="season-controls">
        <el-select v-model="seasonId" aria-label="玩法赛季">
          <el-option
            v-for="item in seasons" :key="seasonKey(item)" :value="seasonKey(item)"
            :label="`${item.title || item.activityId} · ${item.seasonId}`"
          />
        </el-select>
        <span>游戏数据 {{ modeRead.detail.version }} · {{ seasons.length }} 个赛季</span>
      </div>
      <details v-if="modeRead.detail?.diagnostics?.length || season?.diagnostics?.length" class="season-diagnostics">
        <summary>资料诊断</summary>
        <p v-for="(note, index) in [...(modeRead.detail?.diagnostics || []), ...(season?.diagnostics || [])]" :key="index">{{ note }}</p>
      </details>

      <el-tabs v-model="section" aria-label="资料分类" class="gameplay-sections">
        <el-tab-pane v-for="item in activeSections" :key="item.key" :label="item.label" :name="item.key" />
      </el-tabs>

      <template v-if="section === 'resources'">
        <ul v-if="resources.length" class="gameplay-resources">
          <li v-for="path in resources" :key="path"><code>{{ path }}</code></li>
        </ul>
        <p v-else class="gameplay-notice">{{ emptyEntries }}</p>
      </template>
      <div v-else-if="entries.length" class="gameplay-details">
        <div class="gameplay-entry-list">
          <button
            v-for="item in entries" :key="item.key" type="button" :aria-pressed="entryKey === item.key"
            @click="entryKey = item.key"
          >{{ item.name }}</button>
        </div>
        <div class="gameplay-entry-detail">
          <template v-if="section === 'levels'">
            <p v-if="!entry" class="gameplay-notice">选择一项查看地图尺寸、路线、波次和敌人 ID。</p>
            <p v-else-if="levelRead.loading" class="gameplay-notice" role="status">正在读取关卡资料…</p>
            <p v-else-if="levelRead.error" class="gameplay-notice" role="status">
              关卡资料读取失败 · {{ levelRead.error }}
              <el-button text type="primary" @click="readLevel(true)">重试</el-button>
            </p>
            <p v-else-if="levelRead.detail">{{ levelRead.detail.text }}</p>
          </template>
          <p v-else-if="entry">{{ entry.text }}</p>
        </div>
      </div>
      <p v-else class="gameplay-notice">{{ emptyEntries }}</p>
    </template>
  </section>
</template>

<style scoped>
.gameplay-page {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: 18px 22px 22px;
  background: var(--surface);
}

.gameplay-heading h2 {
  margin: 0 0 6px;
  font-size: 20px;
}

.gameplay-heading p,
.gameplay-notice,
.season-controls span,
.season-diagnostics {
  color: var(--muted);
}

.gameplay-heading p,
.gameplay-notice,
details p {
  margin: 6px 0;
  line-height: 1.6;
}

.gameplay-heading details,
.season-diagnostics {
  margin: 7px 0;
}

.gameplay-heading summary,
.season-diagnostics summary {
  cursor: pointer;
}

.season-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin: 5px 0 10px;
}

.season-controls .el-select {
  width: min(420px, 100%);
}

.gameplay-details {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: minmax(150px, 25%) minmax(0, 1fr);
  min-height: 190px;
  border: 1px solid var(--rule);
  border-radius: 4px;
}

.gameplay-entry-list {
  overflow: auto;
  border-right: 1px solid var(--rule);
}

.gameplay-entry-list button {
  display: block;
  width: 100%;
  padding: 9px 12px;
  border: 0;
  border-bottom: 1px solid var(--rule);
  background: var(--surface);
  color: var(--ink);
  text-align: left;
  overflow-wrap: anywhere;
  cursor: pointer;
}

.gameplay-entry-list button:hover,
.gameplay-entry-list button[aria-pressed="true"] {
  background: var(--light-blue);
}

.gameplay-entry-detail {
  overflow: auto;
  padding: 14px 18px;
}

.gameplay-entry-detail p {
  margin: 0;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.gameplay-resources {
  overflow: auto;
  padding: 0;
  margin: 0;
  list-style: none;
}

.gameplay-resources li {
  padding: 8px 10px;
  border-bottom: 1px solid var(--rule);
  overflow-wrap: anywhere;
}
</style>
