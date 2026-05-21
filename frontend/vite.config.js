import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',      // bind all interfaces — required for LAN + Cloudflare Tunnel
    port: 3000,
    allowedHosts: true,   // accept requests from any hostname (aiscanner.in, tunnel, LAN)
    proxy: {
      '/api': {
        target: 'http://localhost:3010',
        changeOrigin: true,
      },
    },
  },
})
