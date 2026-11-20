<script setup>
import { computed } from 'vue'
import { ArrowDown, Document, FolderOpened, Download } from '@element-plus/icons-vue'
import { cellText, fullTime, shortTime } from '../format.js'

const props = defineProps({
  row: { type: Object, default: undefined },
  busy: Boolean,
  opening: Boolean,
})
const emit = defineEmits(['open', 'collapse', 'extractDirectory'])
const details = computed(() => {
  const row = props.row
  if (!row || row.kind === 'directory') return []
  return [
    ['文件大小', cellText(row, 'size')],
    ['用途', cellText(row, 'category')],
    ['来源', cellText(row, 'source')],
    ['修改时间', shortTime(row.modified), fullTime(row.modified)],
    ['创建时间', shortTime(row.created), fullTime(row.created)],
    ['首次观测', shortTime(row.observed), fullTime(row.observed)],
  ]
})

const bundle = computed(() => String(props.row?.extension).toLowerCase().replace(/^\./, '') === 'ab')
</script>

<template>
  <aside class="inspector resource-inspector" aria-label="文件信息">
    <div class="inspector-heading">
      <el-button :icon="ArrowDown" text aria-label="收起文件信息" title="收起文件信息" @click="emit('collapse')" />
      <h2>文件信息</h2>
    </div>
    <div v-if="row" class="inspector-content">
      <div class="file-title">
        <el-icon :class="{ 'folder-icon': row.kind === 'directory' }">
          <component :is="row.kind === 'directory' ? FolderOpened : Document" />
        </el-icon>
        <h3 :title="row.path">{{ row.name }}</h3>
      </div>
      <el-descriptions v-if="details.length" border :column="1" size="small">
        <el-descriptions-item v-for="[label, value, title] in details" :key="label" :label="label">
          <span :title="title || value">{{ value }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <p v-if="row.kind === 'directory'" class="asset-path">{{ row.path }}</p>
      <div class="inspector-actions">
        <template v-if="row.kind === 'directory'">
          <el-button :icon="FolderOpened" type="primary" plain @click="emit('open', row)">打开文件夹</el-button>
          <el-button :icon="Download" :disabled="busy" @click="emit('extractDirectory', row)">解包此文件夹</el-button>
        </template>
        <el-button
          v-else-if="row.previewable"
          type="primary"
          plain
          :loading="opening"
          @click="emit('open', row)"
        >
          {{ bundle ? '查看包内对象' : '预览文件' }}
        </el-button>
      </div>
    </div>
    <div v-else class="inspector-placeholder">
      <el-icon :size="29"><Document /></el-icon>
      <p>选择文件或文件夹以查看信息</p>
    </div>
  </aside>
</template>
