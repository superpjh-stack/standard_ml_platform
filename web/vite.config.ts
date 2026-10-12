import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// 개발 서버 5190 → API (기본 8200, D-14). API 포트는 환경변수 MLP_API_PORT 로 바꾼다(QA 전용 포트 — F19-3 · D2-10).
// 빌드는 API 가 /app/* 로 제공한다.
declare const process: {env: Record<string, string | undefined>};   // node 형 정의 없이 (의존성 추가 0)
const apiPort = /^\d{2,5}$/.test(process.env.MLP_API_PORT ?? '') ? process.env.MLP_API_PORT : '8200';

export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {port: 5190, strictPort: true, proxy: {'/api': `http://127.0.0.1:${apiPort}`}},
});
