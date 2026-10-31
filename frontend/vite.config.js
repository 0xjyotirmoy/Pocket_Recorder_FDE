import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/app/', // served by the backend at http://localhost:8000/app/
  plugins: [react(), tailwindcss()],
  server: { port: 5173, host: true },
})
