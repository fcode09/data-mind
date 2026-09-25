import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// DataMind: en dev, si no hay VITE_API_URL, las llamadas relativas
// (/ask, /conversations) se proxifican al backend local.
const apiTarget = process.env.VITE_API_URL ?? 'http://127.0.0.1:8001'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ask': { target: apiTarget, changeOrigin: true },
      '/conversations': { target: apiTarget, changeOrigin: true },
    },
  },
})
