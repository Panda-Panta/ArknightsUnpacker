<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Clock, Collection, Document,
  Folder, FolderOpened, Grid, MoreFilled, Operation, RefreshRight, Search, Setting, User,
} from '@element-plus/icons-vue'
import ObjectInspector from './components/ObjectInspector.vue'
import ResourceInspector from './components/ResourceInspector.vue'
import WorkbenchTable from './components/WorkbenchTable.vue'
import CharacterPage from './pages/CharacterPage.vue'
import EntityPage from './pages/EntityPage.vue'
import GameplayPage from './pages/GameplayPage.vue'
import RecordsPage from './pages/RecordsPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import { objectColumns, resourceColumns } from './format.js'
import { useWorkbench } from './useWorkbench.js'

const routes = [
  { key: 'explorer', label: '资源浏览', icon: Folder },
  { key: 'updates', label: '更新记录', icon: Clock },
  { key: 'operators', label: '干员资料', icon: User },
  { key: 'modules', label: '模组更新', icon: Collection },
  { key: 'gameplay', label: '玩法资料', icon: Grid },
  { key: 'settings', label: '设置', icon: Setting },
]

const objectTypes = [
  { key: 'image', label: '图片' },
  { key: 'audio', label: '音频' },
  { key: 'video', label: '视频' },
  { key: 'text', label: '文本' },
  { key: 'other', label: '其他' },
]

const {
  state, connected, errorMessage, location, folder, filters, sort, page, pageSize,
  list, loadingList, files, selectedFileId, checkedFiles, fileInFocus, fileIds,
  columnOrder, hiddenColumns, visibleColumns, inspectorVisible, bundle, openingBundle,
  objectDetails, objectPreview, objectQuery, objectFilter, selectedObjectId, checkedObjects,
  objectSort, activeArtifactIndex, selectedObject, activeArtifact, objectCategories, objectRows,
  objectPage, objectPageSize, currentObjectPage,
  run, navigate, goBack, goForward, canGoForward, openRow, closeBundle, focusObject, moveColumn, toggleColumn,
  chooseFile, sortFiles, sortObjects, selectAllFiles,
} = useWorkbench()

const activePage = ref('explorer')
const settingsMode = ref('settings')
const characterToken = ref('')
const menuPage = computed(() => activePage.value === 'characters' ? 'explorer' : activePage.value)
watch(() => state.value.revision, () => {
  if (activePage.value === 'characters') void selectPage('explorer')
})
const resourceTable = ref(null)
let resourceScroll
const rootName = computed(() => state.value.root.split(/[\\/]/).filter(Boolean).at(-1) || '选择游戏目录')
const crumbs = computed(() => {
  const segments = folder.value.split(/[\\/]/).filter(Boolean)
  return segments.map((name, index) => ({ name, path: segments.slice(0, index + 1).join('/') }))
})
const canBack = computed(() => Boolean(bundle.value) || location.value > 0)
const canUp = computed(() => Boolean(bundle.value) || crumbs.value.length > 0)
const fileEmpty = computed(() => {
  if (!connected.value) return errorMessage.value || '正在连接桌面程序…'
  if (state.value.restoring) return '正在恢复上次保存的资源索引…'
  if (!state.value.root) return '选择游戏目录后，扫描资源以开始浏览。'
  if (state.value.scanning) return '正在扫描资源…'
  if (filters.query || filters.category || filters.abOnly) return '没有匹配的资源，请调整筛选条件。'
  return '当前目录暂无资源。可以打开其他目录或扫描更新。'
})
const countLabel = computed(() => list.value.directoryCount + ' 个文件夹 · ' + list.value.fileCount + ' 个文件')
const statusText = computed(() => errorMessage.value || state.value.status)
const columnLabels = Object.fromEntries(resourceColumns.map((column) => [column.key, column.label]))
const filteredObjectTypes = computed(() => objectTypes.filter(({ key }) => objectCategories.value.has(key)))
const hiddenObjectCount = computed(() => {
  const visible = new Set(objectRows.value.map((row) => row.id))
  return [...checkedObjects.value].filter((id) => !visible.has(id)).length
})
const canMakeExpressions = computed(() => fileIds.value.length > 0 && fileIds.value.every((id) => {
  const row = files.value.find((entry) => entry.id === id)
  return row?.category === '剧情角色' || /(?:^|[\\/])avg[\\/]characters[\\/]/i.test(row?.path || '')
}))

function up() {
  if (bundle.value) void closeBundle(true)
  else navigate(crumbs.value.at(-2)?.path || '')
}

function jump(path) {
  if (bundle.value) {
    void closeBundle()
    if (path === folder.value) return
  }
  navigate(path)
}

async function selectPage(name) {
  if (name === activePage.value) return
  if (bundle.value && name !== 'explorer') await closeBundle()
  if (characterToken.value && name !== 'characters') {
    const token = characterToken.value
    characterToken.value = ''
    await run('characterClose', { token })
  }
  activePage.value = name
}

function openSettings(mode = 'settings') {
  settingsMode.value = mode
  void selectPage('settings')
}

async function headerAction(action) {
  if (action === 'scanOptions' || action === 'history') openSettings(action)
  else if (action === 'tasks') await selectPage('tasks')
  else await run(action)
}

async function openRecordedResource(row) {
  await selectPage('explorer')
  await openRow(row)
}

async function extractDirectory(row) {
  await run('extractDirectory', { folder: row.path, layer: filters.layer })
}

async function extractFiles(action = 'extract') {
  if (!fileIds.value.length) return
  const data = await run(action, { ids: fileIds.value })
  if (action === 'expressions' && data?.token) {
    characterToken.value = data.token
    await selectPage('characters')
  }
}

function extractObjects() {
  if (bundle.value && checkedObjects.value.size) {
    return run('extractObjects', { token: bundle.value.token, ids: [...checkedObjects.value] })
  }
}

async function activateObject(row) {
  inspectorVisible.value = true
  await nextTick()
  await focusObject(row)
}

watch(() => Boolean(bundle.value), async (insideBundle) => {
  if (insideBundle) {
    resourceScroll = resourceTable.value?.scrollPosition()
  } else if (resourceScroll) {
    await nextTick()
    resourceTable.value?.restoreScroll(resourceScroll)
  }
})
</script>

<template>
  <div class="workbench">
    <header class="app-header">
      <div class="app-title">
        <el-icon :size="28"><Collection /></el-icon>
        <h1>ArknightsUnpacker</h1>
      </div>
      <div class="application-actions">
        <el-button
          class="game-root"
          :title="state.root || '选择游戏目录'"
          :icon="FolderOpened"
          :disabled="!connected || state.busy"
          @click="run('chooseRoot')"
        >
          <span class="root-name">{{ rootName }}</span>
          <el-icon><ArrowDown /></el-icon>
        </el-button>
        <el-button
          type="primary"
          :icon="RefreshRight"
          :loading="state.scanning"
          :disabled="!connected || !state.root || state.busy"
          @click="run('scan')"
        >扫描更新</el-button>
        <el-dropdown :disabled="!connected" trigger="click" @command="headerAction">
          <el-button :icon="MoreFilled" aria-label="工作台操作" title="工作台操作" />
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="scanOptions" :disabled="state.busy">扫描选项</el-dropdown-item>
              <el-dropdown-item command="history" :disabled="state.busy">资源快照与历史</el-dropdown-item>
              <el-dropdown-item command="loadData" :disabled="state.busy || !state.root">解析核心数据</el-dropdown-item>
              <el-dropdown-item command="tasks" divided>任务记录</el-dropdown-item>
              <el-dropdown-item command="openOutput">打开输出目录</el-dropdown-item>
              <el-dropdown-item v-if="state.busy" command="cancel" divided>取消当前任务</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="workbench-body">
      <aside class="side-rail" aria-label="功能导航">
        <el-menu :default-active="menuPage" @select="$event === 'settings' ? openSettings() : selectPage($event)">
          <el-menu-item v-for="route in routes" :key="route.key" :index="route.key"
            :disabled="!connected && route.key !== 'explorer'"
          >
            <el-icon><component :is="route.icon" /></el-icon>
            <span>{{ route.label }}</span>
          </el-menu-item>
        </el-menu>
      </aside>

      <main class="workspace" :aria-label="activePage === 'explorer' ? (bundle ? '包内对象' : '资源浏览') : undefined">
        <template v-if="activePage === 'explorer'">
        <div class="location-bar">
          <div class="history-buttons">
            <el-button :icon="ArrowLeft" text :disabled="!canBack" aria-label="后退" title="后退" @click="goBack" />
            <el-button :icon="ArrowRight" text :disabled="!canGoForward" aria-label="前进" title="前进" @click="goForward" />
            <el-button :icon="ArrowUp" text :disabled="!canUp" aria-label="上一级" title="上一级" @click="up" />
          </div>
          <el-breadcrumb class="breadcrumb" separator="/">
            <el-breadcrumb-item>
              <button class="crumb" type="button" @click="jump('')">资源</button>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-for="entry in crumbs" :key="entry.path">
              <button class="crumb" type="button" :title="entry.path" @click="jump(entry.path)">
                {{ entry.name }}
              </button>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-if="bundle">
              <span class="bundle-crumb" :title="bundle.path">{{ bundle.name }}</span>
            </el-breadcrumb-item>
          </el-breadcrumb>
          <el-button v-if="!inspectorVisible" :icon="Document" plain @click="inspectorVisible = true">
            {{ bundle ? '对象预览' : '文件信息' }}
          </el-button>
        </div>

        <div class="workspace-body" :class="{ 'inside-bundle': bundle }">
          <section class="result-panel" :aria-label="bundle ? '包内对象列表' : '目录和资源列表'">
            <template v-if="!bundle">
              <div class="filters">
                <el-input v-model="filters.query" clearable :prefix-icon="Search" placeholder="搜索当前目录"
                  aria-label="搜索当前目录" :disabled="!connected"
                />
                <el-select v-model="filters.layer" aria-label="资源来源" :disabled="!connected">
                  <el-option label="原始文件 · 全部来源" value="raw" />
                  <el-option label="当前生效资源" value="effective" />
                </el-select>
                <el-select v-model="filters.category" aria-label="资源用途" :empty-values="[null, undefined]"
                  :disabled="!connected"
                >
                  <el-option label="全部用途" value="" />
                  <el-option v-for="category in list.categories" :key="category" :label="category" :value="category" />
                </el-select>
                <label class="filter-switch">
                  <el-switch v-model="filters.recursive" aria-label="包含子目录" :disabled="!connected" />
                  <span>包含子目录</span>
                </label>
                <el-popover trigger="click" placement="bottom-end" :width="232">
                  <template #reference>
                    <el-button type="primary" plain :icon="Operation">列设置</el-button>
                  </template>
                  <div class="columns-menu">
                    <el-checkbox v-model="filters.abOnly">仅显示 .ab 文件</el-checkbox>
                    <el-divider />
                    <div v-for="(key, index) in columnOrder" :key="key" class="column-option">
                      <el-checkbox
                        :model-value="!hiddenColumns.has(key)"
                        :disabled="key === 'name'"
                        @change="toggleColumn(key, $event)"
                      >{{ columnLabels[key] }}</el-checkbox>
                      <el-button :icon="ArrowUp" text :disabled="index === 0" :aria-label="'上移' + columnLabels[key]"
                        @click="moveColumn(key, -1)"
                      />
                      <el-button :icon="ArrowDown" text :disabled="index === columnOrder.length - 1"
                        :aria-label="'下移' + columnLabels[key]" @click="moveColumn(key, 1)"
                      />
                    </div>
                  </div>
                </el-popover>
              </div>
              <WorkbenchTable
                ref="resourceTable"
                :rows="files"
                :columns="visibleColumns"
                :sort="sort"
                :focus-id="selectedFileId"
                :checked="checkedFiles"
                :loading="loadingList"
                @sort="sortFiles"
                @focus="chooseFile"
                @activate="openRow"
                @selection="checkedFiles = $event"
              >
                <template #empty>{{ fileEmpty }}</template>
              </WorkbenchTable>
              <footer class="result-footer">
                <div class="result-summary">
                  <span>{{ countLabel }}</span>
                  <span v-if="checkedFiles.size" class="muted">已勾选 {{ checkedFiles.size }} 项</span>
                  <el-button v-if="list.total > pageSize" type="primary" link :disabled="loadingList"
                    @click="selectAllFiles">勾选全部结果</el-button>
                  <el-button v-if="checkedFiles.size" type="primary" link @click="checkedFiles = new Set()">
                    清除勾选
                  </el-button>
                </div>
                <el-pagination v-model:current-page="page" :page-size="pageSize" :total="list.total"
                  layout="prev, pager, next" :pager-count="5" hide-on-single-page small
                />
                <div class="selection-actions">
                  <el-dropdown split-button type="primary" trigger="click" :disabled="!fileIds.length"
                    @click="extractFiles()" @command="extractFiles($event)"
                  >
                    加入解包队列
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="extractImages">导出所选包内图片</el-dropdown-item>
                        <el-dropdown-item v-if="canMakeExpressions" command="expressions">表情差分制作</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </footer>
            </template>

            <template v-else>
              <div class="bundle-heading">
                <el-button :icon="ArrowLeft" text @click="closeBundle(true)">返回资源列表</el-button>
                <h2>包内对象</h2>
                <span class="muted">{{ objectDetails.rows.length }} 项</span>
              </div>
              <div class="filters object-filters">
                <el-input v-model="objectQuery" clearable :prefix-icon="Search" placeholder="搜索包内对象"
                  aria-label="搜索包内对象"
                />
                <el-select v-model="objectFilter" aria-label="对象类型" :empty-values="[null, undefined]">
                  <el-option :label="'全部对象 · ' + objectDetails.rows.length" value="" />
                  <el-option v-for="option in filteredObjectTypes" :key="option.key"
                    :label="option.label + ' · ' + objectCategories.get(option.key)" :value="option.key"
                  />
                </el-select>
              </div>
              <WorkbenchTable
                :rows="currentObjectPage"
                :columns="objectColumns"
                :sort="objectSort"
                :focus-id="selectedObjectId"
                :checked="checkedObjects"
                :loading="objectDetails.loading"
                objects
                @sort="sortObjects"
                @focus="focusObject"
                @activate="activateObject"
                @selection="checkedObjects = $event"
              >
                <template #empty>{{ objectDetails.error || '没有符合条件的包内对象' }}</template>
              </WorkbenchTable>
              <footer class="result-footer object-footer">
                <div class="result-summary">
                  <span>已勾选 {{ checkedObjects.size }} 项</span>
                  <span v-if="hiddenObjectCount" class="muted">其中 {{ hiddenObjectCount }} 项因筛选未显示</span>
                  <el-button v-if="checkedObjects.size" type="primary" link @click="checkedObjects = new Set()">
                    清除勾选
                  </el-button>
                </div>
                <el-pagination v-model:current-page="objectPage" :page-size="objectPageSize" :total="objectRows.length"
                  layout="prev, pager, next" :pager-count="5" hide-on-single-page small
                />
                <el-button type="primary" :disabled="!checkedObjects.size" @click="extractObjects()">提取勾选对象</el-button>
              </footer>
            </template>
          </section>

          <ObjectInspector
            v-if="inspectorVisible && bundle"
            :row="selectedObject"
            :preview="objectPreview"
            :artifact="activeArtifact"
            :artifact-index="activeArtifactIndex"
            @collapse="inspectorVisible = false"
            @artifact="activeArtifactIndex = $event"
            @save="run('saveArtifact', { token: bundle.token, index: $event })"
            @open-media="run('openMedia', { token: bundle.token, index: activeArtifactIndex })"
          />
          <ResourceInspector
            v-else-if="inspectorVisible"
            :row="fileInFocus"
            :busy="state.busy"
            :opening="openingBundle"
            @open="openRow"
            @collapse="inspectorVisible = false"
            @extract-directory="extractDirectory"
          />
        </div>
        </template>
        <div v-else class="workbench-section">
          <RecordsPage v-if="activePage === 'updates' || activePage === 'tasks'" :key="activePage"
            :run="run" :state="state" :mode="activePage" @open-resource="openRecordedResource" />
          <EntityPage v-else-if="activePage === 'operators' || activePage === 'modules'" :key="activePage"
            :run="run" :state="state" :kind="activePage" />
          <GameplayPage v-else-if="activePage === 'gameplay'" :run="run" :state="state" />
          <SettingsPage v-else-if="activePage === 'settings'" :run="run" :state="state" :mode="settingsMode" />
          <CharacterPage v-else-if="activePage === 'characters'" :run="run" :state="state" :token="characterToken"
            @close="selectPage('explorer')" />
        </div>

        <div class="application-status" :class="{ 'has-error': errorMessage }">
          <span role="status" :title="statusText">{{ statusText }}</span>
          <el-button v-if="state.busy" type="primary" link @click="run('cancel')">取消当前任务</el-button>
          <el-button :disabled="!connected" link @click="selectPage('tasks')">
            任务记录{{ state.taskCount ? ' · ' + state.taskCount : '' }}
          </el-button>
        </div>
      </main>
    </div>
  </div>
</template>
