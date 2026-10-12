import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// 개발 서버 5190 → API 8200 (D-14). 빌드는 API 가 /app/* 로 제공한다.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {port: 5190, strictPort: true, proxy: {'/api': 'http://127.0.0.1:8200'}},
});
