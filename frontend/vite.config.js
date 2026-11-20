import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  base: './',
  plugins: [vue()],
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: fileURLToPath(new URL('../resources/workbench', import.meta.url)),
    emptyOutDir: true,
    target: 'chrome122',
    lib: {
      entry: fileURLToPath(new URL('./src/main.js', import.meta.url)),
      name: 'ArknightsWorkbench',
      formats: ['iife'],
      fileName: () => 'workbench.js',
      cssFileName: 'workbench',
    },
  },
})
