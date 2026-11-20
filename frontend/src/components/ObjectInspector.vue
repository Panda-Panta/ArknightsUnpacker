<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowLeft, Document, Download, Picture, ZoomIn, ZoomOut } from '@element-plus/icons-vue'
import { sizeText } from '../format.js'

const props = defineProps({
  row: { type: Object, default: undefined },
  preview: { type: Object, required: true },
  artifact: { type: Object, default: undefined },
  artifactIndex: { type: Number, required: true },
})
const emit = defineEmits(['collapse', 'artifact', 'save', 'open-media'])
const zoom = ref(100)
const tab = ref('preview')
const mediaError = ref(false)
const mediaKey = computed(() => [props.preview.id, props.artifactIndex, props.artifact?.url].join('|'))
watch(mediaKey, () => {
  zoom.value = 100
  mediaError.value = false
})
watch(() => props.row?.id, () => { tab.value = 'preview' })
</script>

<template>
  <aside class="inspector object-inspector" aria-label="对象预览">
    <div class="inspector-heading">
      <h2>对象预览</h2>
      <el-button :icon="ArrowLeft" text aria-label="收起对象预览" title="收起对象预览" @click="emit('collapse')" />
    </div>
    <template v-if="row">
      <div class="inspector-content">
        <div class="file-title">
          <el-icon><Document /></el-icon>
          <h3 :title="row.name">{{ row.name }}</h3>
        </div>
        <el-tabs v-model="tab">
          <el-tab-pane label="预览" name="preview">
            <div v-if="preview.loading" v-loading="true" class="preview-placeholder" aria-label="正在准备预览"></div>
            <el-alert v-else-if="preview.error || mediaError" type="warning" :closable="false" show-icon>
              {{ preview.error || '此媒体格式无法在工作台播放。' }}
              <el-button v-if="artifact?.url" type="primary" link @click="emit('open-media')">使用系统播放器打开</el-button>
            </el-alert>
            <template v-else-if="artifact">
              <el-select
                v-if="preview.artifacts.length > 1"
                class="artifact-select"
                :model-value="artifactIndex"
                aria-label="选择预览产物"
                @change="emit('artifact', $event)"
              >
                <el-option
                  v-for="(item, index) in preview.artifacts"
                  :key="index"
                  :label="item.name"
                  :value="index"
                />
              </el-select>
              <div v-if="artifact.kind === 'image'" class="image-workspace">
                <div class="image-preview">
                  <img
                    :key="mediaKey"
                    :src="artifact.url"
                    :alt="artifact.name"
                    :style="{ width: zoom + '%' }"
                    @error="mediaError = true"
                  >
                </div>
                <div class="preview-controls">
                  <el-button :icon="ZoomOut" text aria-label="缩小" :disabled="zoom <= 25" @click="zoom -= 25" />
                  <el-button text title="适合窗口" @click="zoom = 100">{{ zoom }}%</el-button>
                  <el-button :icon="ZoomIn" text aria-label="放大" :disabled="zoom >= 400" @click="zoom += 25" />
                </div>
                <el-button class="artifact-save" :icon="Download" type="primary" plain @click="emit('save', artifactIndex)">
                  保存原图…
                </el-button>
              </div>
              <audio
                v-else-if="artifact.kind === 'audio'"
                :key="mediaKey"
                controls
                preload="metadata"
                :src="artifact.url"
                :aria-label="artifact.name"
                @error="mediaError = true"
              ></audio>
              <video
                v-else-if="artifact.kind === 'video'"
                :key="mediaKey"
                controls
                preload="metadata"
                :src="artifact.url"
                :aria-label="artifact.name"
                @error="mediaError = true"
              ></video>
              <pre v-else class="text-preview">{{ artifact.text || '没有可显示的内容' }}</pre>
            </template>
            <p v-else class="muted">此对象暂无可预览的内容。</p>
          </el-tab-pane>
          <el-tab-pane label="对象信息" name="info">
            <el-descriptions border :column="1" size="small">
              <el-descriptions-item label="类型">{{ row.type }}</el-descriptions-item>
              <el-descriptions-item label="大小">{{ sizeText(row.size) }}</el-descriptions-item>
              <el-descriptions-item label="对象 ID">{{ row.id }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
        </el-tabs>
      </div>
    </template>
    <div v-else class="inspector-placeholder">
      <el-icon :size="29"><Picture /></el-icon>
      <p>选择一个包内对象以预览</p>
    </div>
  </aside>
</template>
