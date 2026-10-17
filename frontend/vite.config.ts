import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

const apiProxy = {
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
