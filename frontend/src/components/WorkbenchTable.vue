<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Document, Files, Folder } from '@element-plus/icons-vue'
import { cellText, fullTime } from '../format.js'

const props = defineProps({
  rows: { type: Array, required: true },
  columns: { type: Array, required: true },
  sort: { type: Object, required: true },
  checked: { type: Set, required: true },
  focusId: { type: String, default: '' },
  loading: Boolean,
  objects: Boolean,
})
const emit = defineEmits(['sort', 'focus', 'activate', 'selection'])
const container = ref(null)
const selectionBox = ref(null)
const selectableRows = computed(() => props.rows.filter(selectable))
const allChecked = computed(() => selectableRows.value.length > 0
  && selectableRows.value.every((row) => props.checked.has(row.id)))
const someChecked = computed(() => selectableRows.value.some((row) => props.checked.has(row.id)))
let anchorId = ''
let drag = null
let suppressClick = false

function selectable(row) {
  return props.objects || row.extractable
}

function replaceVisibleSelection(rows, additive, original = props.checked) {
  const next = new Set(original)
  if (!additive) {
    for (const row of selectableRows.value) next.delete(row.id)
  }
  for (const row of rows) {
    if (selectable(row)) next.add(row.id)
  }
  emit('selection', next)
}

function toggle(row, checked) {
  if (!selectable(row)) return
  const next = new Set(props.checked)
  if (checked) next.add(row.id)
  else next.delete(row.id)
  emit('selection', next)
  anchorId = row.id
}

function toggleAll(checked) {
  replaceVisibleSelection(checked ? selectableRows.value : [], false)
}

function choose(row, _column, event) {
  if (suppressClick) return
  const additive = event.ctrlKey || event.metaKey
  if (event.shiftKey && selectable(row)) {
    const end = props.rows.findIndex((entry) => entry.id === row.id)
    const anchor = props.rows.findIndex((entry) => entry.id === anchorId)
    const start = anchor < 0 ? end : anchor
    replaceVisibleSelection(props.rows.slice(Math.min(start, end), Math.max(start, end) + 1), additive)
    if (anchor < 0) anchorId = row.id
  } else if (additive && selectable(row)) {
    toggle(row, !props.checked.has(row.id))
  } else {
    anchorId = row.id
  }
  emit('focus', row)
}

function activate(row) {
  if (!suppressClick) emit('activate', row)
}

function pointerDown(event) {
  suppressClick = false
  if (event.button !== 0 || event.shiftKey || props.loading || !selectableRows.value.length) return
  if (event.target.closest('.el-checkbox, .el-scrollbar__bar')) return
  const scrollBody = event.target.closest('.el-table__body-wrapper')
  if (!scrollBody) return
  const viewport = scrollBody.querySelector('.el-scrollbar__wrap') || scrollBody
  drag = {
    pointer: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    viewport,
    check: new Set(props.checked),
    additive: event.ctrlKey || event.metaKey,
    started: false,
  }
}

function pointerMove(event) {
  if (!drag || event.pointerId !== drag.pointer) return
  if (!drag.started && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 6) return
  drag.started = true
  suppressClick = true
  event.preventDefault()

  const viewport = drag.viewport.getBoundingClientRect()
  const area = container.value.getBoundingClientRect()
  const x = Math.max(viewport.left, Math.min(viewport.right, event.clientX))
  const y = Math.max(viewport.top, Math.min(viewport.bottom, event.clientY))
  const left = Math.min(drag.x, x)
  const top = Math.min(drag.y, y)
  const right = Math.max(drag.x, x)
  const bottom = Math.max(drag.y, y)
  selectionBox.value = {
    left: left - area.left + 'px',
    top: top - area.top + 'px',
    width: Math.max(1, right - left) + 'px',
    height: Math.max(1, bottom - top) + 'px',
  }

  const hitRows = []
  const rendered = drag.viewport.querySelectorAll('.el-table__row')
  for (const [index, element] of rendered.entries()) {
    const bounds = element.getBoundingClientRect()
    if (bounds.bottom > top && bounds.top < bottom && bounds.right > left && bounds.left < right) {
      if (props.rows[index]) hitRows.push(props.rows[index])
    }
  }
  replaceVisibleSelection(hitRows, drag.additive, drag.check)
}

function finishDrag(event) {
  if (!drag || event.pointerId !== drag.pointer) return
  drag = null
  selectionBox.value = null
}

function resetDrag() {
  drag = null
  selectionBox.value = null
  suppressClick = false
}

function rowClass({ row }) {
  return [
    row.id === props.focusId ? 'is-focused-row' : '',
    props.checked.has(row.id) ? 'is-checked-row' : '',
    row.kind === 'directory' ? 'is-directory-row' : '',
  ].join(' ')
}

function rowIcon(row) {
  if (row.kind === 'directory') return Folder
  return props.objects ? Files : Document
}

function tooltip(row, key) {
  if (key === 'name') return row.path || row.name
  if (key === 'modified' || key === 'created' || key === 'observed') return fullTime(row[key])
  return cellText(row, key)
}

function scrollArea() {
  return container.value?.querySelector('.el-table__body-wrapper .el-scrollbar__wrap')
}

defineExpose({
  scrollPosition() {
    const element = scrollArea()
    return element && { top: element.scrollTop, left: element.scrollLeft }
  },
  restoreScroll(position) {
    scrollArea()?.scrollTo(position)
  },
})

watch(() => props.rows, resetDrag)
onMounted(() => {
  window.addEventListener('pointermove', pointerMove, { passive: false })
  window.addEventListener('pointerup', finishDrag)
  window.addEventListener('pointercancel', finishDrag)
  window.addEventListener('blur', resetDrag)
})
onUnmounted(() => {
  window.removeEventListener('pointermove', pointerMove)
  window.removeEventListener('pointerup', finishDrag)
  window.removeEventListener('pointercancel', finishDrag)
  window.removeEventListener('blur', resetDrag)
})
</script>

<template>
  <div ref="container" class="table-shell" @pointerdown="pointerDown">
    <el-table
      v-loading="loading"
      :data="rows"
      row-key="id"
      height="100%"
      table-layout="fixed"
      stripe
      :row-class-name="rowClass"
      @row-click="choose"
      @row-dblclick="activate"
    >
      <el-table-column width="50" align="center" class-name="checkbox-cell">
        <template #header>
          <el-checkbox
            :model-value="allChecked"
            :indeterminate="someChecked && !allChecked"
            :disabled="selectableRows.length === 0"
            aria-label="勾选本页结果"
            @change="toggleAll"
          />
        </template>
        <template #default="{ row }">
          <span class="table-check" @click.stop>
            <el-checkbox
              :model-value="checked.has(row.id)"
              :disabled="!selectable(row)"
              :aria-label="'勾选 ' + row.name"
              @change="toggle(row, $event)"
            />
          </span>
        </template>
      </el-table-column>
      <el-table-column
        v-for="column in columns"
        :key="column.key"
        :prop="column.key"
        :min-width="column.minWidth"
        resizable
      >
        <template #header>
          <button
            class="sort-header"
            type="button"
            :aria-label="'按' + column.label + '排序'"
            @click="emit('sort', column.key)"
          >
            {{ column.label }}
            <el-icon v-if="sort.key === column.key" class="sort-indicator" aria-hidden="true">
              <component :is="sort.descending ? ArrowDown : ArrowUp" />
            </el-icon>
            <span v-else class="sort-carets" aria-hidden="true"></span>
          </button>
        </template>
        <template #default="{ row }">
          <button
            v-if="column.key === 'name'"
            class="row-name"
            type="button"
            :title="tooltip(row, column.key)"
            @dblclick.stop="activate(row)"
            @keydown.enter.stop.prevent="activate(row)"
          >
            <el-icon :class="{ 'folder-icon': row.kind === 'directory' }">
              <component :is="rowIcon(row)" />
            </el-icon>
            <span>{{ row.name }}</span>
          </button>
          <span v-else class="data-cell" :title="tooltip(row, column.key)">{{ cellText(row, column.key) }}</span>
        </template>
      </el-table-column>
      <template #empty>
        <slot name="empty">没有符合条件的结果</slot>
      </template>
    </el-table>
    <div v-if="selectionBox" class="selection-box" :style="selectionBox" aria-hidden="true"></div>
  </div>
</template>
