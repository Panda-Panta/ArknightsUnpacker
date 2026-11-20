import { computed, nextTick, onMounted, onUnmounted, reactive, ref, shallowRef, watch } from 'vue'
import { connectWorkbench, invoke } from './bridge.js'
import { resourceColumns } from './format.js'

const prefKey = 'arknights-unpacker-workbench-v1'
const defaultView = { folder: '', rows: [], categories: [], total: 0, directoryCount: 0, fileCount: 0 }
const defaultState = { root: '', busy: false, scanning: false, restoring: false, status: '', taskCount: 0 }
const compareText = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' }).compare

function readPreferences() {
  try {
    return JSON.parse(window.localStorage.getItem(prefKey)) || {}
  } catch {
    return {}
  }
}

function writePreferences(preferences) {
  try {
    window.localStorage.setItem(prefKey, JSON.stringify(preferences))
  } catch {
    // The view remains usable when the embedded browser has no storage.
  }
}

function valueStatus(message) {
  return message instanceof Error ? message.message : String(message)
}

function objectGroup(row) {
  const type = row.type.toLowerCase()
  if (/texture|image|sprite|cubemap/.test(type)) return 'image'
  if (/audio|sound/.test(type)) return 'audio'
  if (/video|movie/.test(type)) return 'video'
  if (/text|script/.test(type)) return 'text'
  return 'other'
}

export function useWorkbench() {
  const saved = readPreferences()
  const darkTheme = ref(saved.theme === 'dark')
  watch(darkTheme, (enabled) => {
    document.documentElement.classList.toggle('dark', enabled)
  }, { immediate: true, flush: 'sync' })
  const state = shallowRef(defaultState)
  const connected = ref(false)
  const errorMessage = ref('')
  const connectedRoot = ref('')
  const history = ref([''])
  const location = ref(0)
  const folder = computed(() => history.value[location.value] || '')
  const filters = reactive({
    query: '',
    layer: saved.layer === 'effective' ? 'effective' : 'raw',
    category: '',
    recursive: false,
    abOnly: false,
  })
  const sort = reactive({
    key: resourceColumns.some((column) => column.key === saved.sort?.key) ? saved.sort.key : 'name',
    descending: saved.sort?.descending === true,
  })
  const page = ref(1)
  const pageSize = ref(100)
  const list = shallowRef(defaultView)
  const loadingList = ref(false)
  const selectedFileId = ref('')
  const checkedFiles = ref(new Set())
  const files = computed(() => list.value.rows)
  const fileInFocus = computed(() => files.value.find((row) => row.id === selectedFileId.value))
  const fileIds = computed(() => [...checkedFiles.value])
  const validColumns = resourceColumns.map((column) => column.key)
  const columnOrder = ref([...new Set((Array.isArray(saved.columnOrder) ? saved.columnOrder : [])
    .filter((key) => validColumns.includes(key)).concat(validColumns))])
  const hiddenColumns = ref(new Set(Array.isArray(saved.hiddenColumns) ? saved.hiddenColumns : []))
  const visibleColumns = computed(() => columnOrder.value
    .filter((key) => key === 'name' || !hiddenColumns.value.has(key))
    .map((key) => resourceColumns.find((column) => column.key === key)))
  const inspectorVisible = ref(saved.inspectorVisible !== false)
  const bundle = shallowRef(null)
  const forwardBundle = shallowRef(null)
  const openingBundle = ref(false)
  const objectDetails = shallowRef({ loading: false, error: '', rows: [] })
  const objectPreview = shallowRef({ loading: false, error: '', id: '', artifacts: [] })
  const objectQuery = ref('')
  const objectFilter = ref('')
  const objectPage = ref(1)
  const objectPageSize = 100
  const selectedObjectId = ref('')
  const checkedObjects = ref(new Set())
  const objectSort = reactive({ key: 'name', descending: false })
  const activeArtifactIndex = ref(0)
  const selectedObject = computed(() => objectDetails.value.rows.find((row) => row.id === selectedObjectId.value))
  const activeArtifact = computed(() => objectPreview.value.artifacts[activeArtifactIndex.value])
  const objectCategories = computed(() => {
    const counts = new Map()
    for (const row of objectDetails.value.rows) {
      const group = objectGroup(row)
      counts.set(group, (counts.get(group) || 0) + 1)
    }
    return counts
  })
  const objectRows = computed(() => {
    const query = objectQuery.value.trim().toLowerCase()
    const { key, descending } = objectSort
    return objectDetails.value.rows.filter((row) => {
      if (objectFilter.value && objectGroup(row) !== objectFilter.value) return false
      return !query || [row.name, row.type, row.id].some((value) => String(value).toLowerCase().includes(query))
    }).sort((left, right) => {
      if (key === 'size' && (left.size == null || right.size == null)) {
        return Number(left.size == null) - Number(right.size == null) || compareText(left.id, right.id)
      }
      const comparison = key === 'size' ? left.size - right.size : compareText(left[key], right[key])
      return comparison * (descending ? -1 : 1) || compareText(left.id, right.id)
    })
  })
  const currentObjectPage = computed(() => {
    const start = (objectPage.value - 1) * objectPageSize
    return objectRows.value.slice(start, start + objectPageSize)
  })

  let bridge
  let listTimer
  let changeTimer
  let listSequence = 0
  let stateSequence = 0
  let objectSequence = 0
  let previewSequence = 0

  function persist() {
    if (!connected.value) return
    writePreferences({
      root: connectedRoot.value,
      folder: folder.value,
      layer: filters.layer,
      sort: { ...sort },
      columnOrder: columnOrder.value,
      hiddenColumns: [...hiddenColumns.value],
      inspectorVisible: inspectorVisible.value,
      theme: darkTheme.value ? 'dark' : 'light',
    })
  }

  function fileQuery() {
    return { folder: folder.value, ...filters, sort: sort.key, descending: sort.descending }
  }

  async function selectAllFiles() {
    const sequence = listSequence
    const ids = await run('matchingResources', fileQuery())
    if (sequence === listSequence && ids) checkedFiles.value = new Set(ids)
  }

  async function refreshList() {
    const sequence = ++listSequence
    loadingList.value = true
    const requestedPage = page.value
    try {
      const data = await invoke(bridge, 'list', {
        ...fileQuery(),
        page: requestedPage,
        pageSize: pageSize.value,
      })
      if (sequence !== listSequence) return
      const maxPage = Math.max(1, Math.ceil(data.total / pageSize.value))
      if (requestedPage > maxPage) {
        page.value = maxPage
        return
      }
      list.value = data
      if (data.folder !== folder.value) {
        history.value[location.value] = data.folder
      }
      const visibleIds = new Set(data.rows.map((row) => row.id))
      if (selectedFileId.value && !visibleIds.has(selectedFileId.value)) selectedFileId.value = ''
      persist()
    } catch (error) {
      if (sequence !== listSequence) return
      errorMessage.value = valueStatus(error)
    } finally {
      if (sequence === listSequence) loadingList.value = false
    }
  }

  function scheduleList(delay = 0) {
    ++listSequence
    window.clearTimeout(listTimer)
    if (bridge && !state.value.restoring) {
      listTimer = window.setTimeout(refreshList, delay)
    } else {
      loadingList.value = false
    }
  }

  function resetFileSelection() {
    selectedFileId.value = ''
    checkedFiles.value = new Set()
  }

  async function refreshState() {
    const sequence = ++stateSequence
    const data = await invoke(bridge, 'state')
    if (sequence !== stateSequence) return
    const rootChanged = data.root !== connectedRoot.value
    const revisionChanged = data.revision !== state.value.revision
    if (rootChanged || revisionChanged) {
      resetFileSelection()
      forwardBundle.value = null
      if (bundle.value) {
        // The host invalidates bundle tokens when the resource binding changes.
        bundle.value = null
        resetObjects()
      }
    }
    if (rootChanged) {
      connectedRoot.value = data.root
      list.value = defaultView
      history.value = [saved.root === data.root && typeof saved.folder === 'string' ? saved.folder : '']
      location.value = 0
      page.value = 1
      resetFileSelection()
    }
    const refresh = state.value === defaultState || rootChanged || revisionChanged
      || data.restoring !== state.value.restoring
    state.value = data
    if (refresh) scheduleList()
  }

  function changeSelection(setRef, id, checked) {
    const next = new Set(setRef.value)
    if (checked) next.add(id)
    else next.delete(id)
    setRef.value = next
  }

  function navigate(folderPath) {
    if (folderPath === folder.value) return
    forwardBundle.value = null
    history.value = history.value.slice(0, location.value + 1).concat(folderPath)
    location.value += 1
    page.value = 1
    resetFileSelection()
    scheduleList()
  }

  function travel(offset) {
    const target = location.value + offset
    if (target < 0 || target >= history.value.length) return
    forwardBundle.value = null
    location.value = target
    page.value = 1
    resetFileSelection()
    scheduleList()
  }

  function setSort(target, key) {
    if (target.key === key) {
      target.descending = !target.descending
    } else {
      target.key = key
      target.descending = false
    }
  }

  function moveColumn(key, offset) {
    const index = columnOrder.value.indexOf(key)
    const target = index + offset
    if (index < 0 || target < 0 || target >= columnOrder.value.length) return
    const reordered = [...columnOrder.value]
    reordered.splice(index, 1)
    reordered.splice(target, 0, key)
    columnOrder.value = reordered
  }

  function toggleColumn(key, visible) {
    if (key !== 'name') changeSelection(hiddenColumns, key, !visible)
  }

  async function run(action, payload) {
    if (!bridge) return
    errorMessage.value = ''
    try {
      return await invoke(bridge, action, payload)
    } catch (error) {
      errorMessage.value = valueStatus(error)
    }
  }

  function resetObjects() {
    ++objectSequence
    ++previewSequence
    objectDetails.value = { loading: false, error: '', rows: [] }
    objectPreview.value = { loading: false, error: '', id: '', artifacts: [] }
    objectQuery.value = ''
    objectFilter.value = ''
    objectPage.value = 1
    selectedObjectId.value = ''
    checkedObjects.value = new Set()
    activeArtifactIndex.value = 0
  }

  async function refreshObjects() {
    const token = bundle.value?.token
    if (!token) return
    const sequence = ++objectSequence
    try {
      const data = await invoke(bridge, 'objectState', { token })
      if (sequence === objectSequence) objectDetails.value = data
    } catch (error) {
      if (sequence === objectSequence) {
        objectDetails.value = { loading: false, error: valueStatus(error), rows: [] }
      }
    }
  }

  async function refreshPreview() {
    const token = bundle.value?.token
    const objectId = selectedObjectId.value
    if (!token || !objectId || !selectedObject.value?.previewable) return
    const sequence = ++previewSequence
    try {
      const data = await invoke(bridge, 'objectPreview', { token })
      if (sequence === previewSequence && data.id === objectId) {
        objectPreview.value = data
      }
    } catch (error) {
      if (sequence === previewSequence) {
        objectPreview.value = { loading: false, error: valueStatus(error), id: objectId, artifacts: [] }
      }
    }
  }

  async function openRow(row) {
    if (row.kind === 'directory') {
      navigate(row.path)
    } else if (row.previewable && !openingBundle.value && !bundle.value) {
      selectedFileId.value = row.id
      openingBundle.value = true
      const startedRoot = connectedRoot.value
      const startedRevision = state.value.revision
      try {
        const data = await run('objects', { id: row.id })
        if (!data?.token) return
        if (startedRoot !== connectedRoot.value || startedRevision !== state.value.revision) return
        resetObjects()
        bundle.value = { token: data.token, name: row.name, path: row.path, id: row.id }
        forwardBundle.value = null
        objectDetails.value = { loading: true, error: '', rows: [] }
        await refreshObjects()
      } finally {
        openingBundle.value = false
      }
    }
  }

  async function closeBundle(remember = false) {
    const current = bundle.value
    if (remember && current) forwardBundle.value = files.value.find((row) => row.id === current.id) ?? null
    bundle.value = null
    resetObjects()
    if (current?.token) {
      await nextTick()
      await run('closeObjects', { token: current.token })
    }
  }

  function goBack() {
    if (bundle.value) return closeBundle(true)
    travel(-1)
  }

  function goForward() {
    if (bundle.value) return
    if (forwardBundle.value) {
      const row = forwardBundle.value
      forwardBundle.value = null
      return openRow(row)
    }
    travel(1)
  }

  function sideButtonPress(event) {
    if (event.button !== 3 && event.button !== 4) return
    event.preventDefault()
    if (event.button === 3) void goBack()
    else void goForward()
  }

  function suppressSideDefault(event) {
    if (event.button === 3 || event.button === 4) event.preventDefault()
  }

  async function focusObject(row) {
    if (selectedObjectId.value === row.id) return
    ++previewSequence
    const token = bundle.value?.token
    selectedObjectId.value = row.id
    activeArtifactIndex.value = 0
    objectPreview.value = { loading: row.previewable, error: '', id: row.id, artifacts: [] }
    if (!row.previewable || !token) return
    try {
      await nextTick()
      if (bundle.value?.token !== token || selectedObjectId.value !== row.id) return
      await invoke(bridge, 'previewObject', { token, id: row.id })
      if (bundle.value?.token === token && selectedObjectId.value === row.id) await refreshPreview()
    } catch (error) {
      if (bundle.value?.token === token && selectedObjectId.value === row.id) {
        objectPreview.value = { loading: false, error: valueStatus(error), id: row.id, artifacts: [] }
      }
    }
  }

  async function onChanged() {
    try {
      await refreshState()
      if (bundle.value) {
        await refreshObjects()
        await refreshPreview()
      }
    } catch (error) {
      errorMessage.value = valueStatus(error)
    }
  }

  function scheduleChange() {
    window.clearTimeout(changeTimer)
    changeTimer = window.setTimeout(onChanged, 110)
  }

  onMounted(async () => {
    window.addEventListener('pointerdown', sideButtonPress, true)
    window.addEventListener('pointerup', suppressSideDefault, true)
    window.addEventListener('auxclick', suppressSideDefault, true)
    try {
      bridge = await connectWorkbench()
      bridge.changed.connect(scheduleChange)
      connected.value = true
      await onChanged()
    } catch (error) {
      errorMessage.value = valueStatus(error)
    }
  })
  onUnmounted(() => {
    window.removeEventListener('pointerdown', sideButtonPress, true)
    window.removeEventListener('pointerup', suppressSideDefault, true)
    window.removeEventListener('auxclick', suppressSideDefault, true)
    window.clearTimeout(listTimer)
    window.clearTimeout(changeTimer)
    if (bridge) bridge.changed.disconnect(scheduleChange)
  })

  watch(() => ({ ...filters }), () => {
    page.value = 1
    forwardBundle.value = null
    resetFileSelection()
    scheduleList(140)
  })
  watch([page, pageSize], () => {
    selectedFileId.value = ''
    scheduleList()
  })
  watch(sort, () => {
    page.value = 1
    scheduleList()
    persist()
  })
  watch([columnOrder, hiddenColumns, inspectorVisible, darkTheme], persist)
  watch([objectQuery, objectFilter, objectSort], () => { objectPage.value = 1 })

  return {
    state, connected, errorMessage, darkTheme, history, location, folder, filters, sort, page, pageSize,
    list, loadingList, files, selectedFileId, checkedFiles, fileInFocus, fileIds,
    columnOrder, hiddenColumns, visibleColumns, inspectorVisible, bundle, openingBundle,
    objectDetails, objectPreview, objectQuery, objectFilter, selectedObjectId, checkedObjects,
    objectSort, activeArtifactIndex, selectedObject, activeArtifact, objectCategories, objectRows,
    objectPage, objectPageSize, currentObjectPage,
    run, navigate, goBack, goForward, openRow, closeBundle, focusObject, moveColumn, toggleColumn, selectAllFiles,
    canGoForward: computed(() => !bundle.value && (Boolean(forwardBundle.value) || location.value < history.value.length - 1)),
    windowAction: (action) => bridge?.windowAction(action),
    moveWindow: (fraction, offsetY) => bridge?.moveWindow(fraction, offsetY),
    chooseFile: (row) => { selectedFileId.value = row.id },
    sortFiles: (key) => setSort(sort, key),
    sortObjects: (key) => setSort(objectSort, key),
  }
}
