import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

const apiProxy = {
  '/backend-api': { target: 'http://127.0.0.1:8000', changeOrigin: true, rewrite: (path: string) => path.replace(/^\/backend-api/, '/api/v1') },
  '/api': {
    target: 'https://rasp.omgtu.ru',
    changeOrigin: true
  }
};

export default defineConfig({
  plugins: [svelte()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy }
});
