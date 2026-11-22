<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ run: Function, modelValue: Object, inherit: Boolean, label: String })
const emit = defineEmits(['update:modelValue'])
const fonts = ref(null)
const loading = ref(false)
const fontKey = font => JSON.stringify([font.path.toLowerCase(), font.index])
const selected = computed(() => props.modelValue ? fontKey(props.modelValue) : 'inherit')
const defaultFont = { path: '', index: 0 }
const legacyFont = computed(() => props.modelValue?.path &&
  !fonts.value?.some(font => fontKey(font) === selected.value)
  ? props.modelValue.path.split(/[\\/]/).pop() : '')

async function loadFonts(open) {
  if (!open || fonts.value || loading.value) return
  loading.value = true
  try {
    const result = await props.run('settingsFonts')
    if (Array.isArray(result)) fonts.value = result
  } finally {
    loading.value = false
  }
}

function selectFont(key) {
  if (key === 'inherit') emit('update:modelValue', null)
  else if (key === fontKey(defaultFont)) emit('update:modelValue', defaultFont)
  else {
    const font = fonts.value?.find(item => fontKey(item) === key)
    if (font) emit('update:modelValue', font)
  }
}
</script>

<template>
  <el-select :model-value="selected" :aria-label="label" filterable :loading="loading"
    @visible-change="loadFonts" @change="selectFont">
    <el-option v-if="inherit" value="inherit" label="使用当前导出字体" />
    <el-option :value="fontKey(defaultFont)" label="默认字体（自动选择）" />
    <el-option v-if="legacyFont" :value="selected" :label="legacyFont" disabled />
    <el-option v-for="font in fonts" :key="fontKey(font)" :value="fontKey(font)"
      :label="[font.family, font.style].filter(Boolean).join(' · ')" />
  </el-select>
</template>
