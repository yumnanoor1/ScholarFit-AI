import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, '');
  const apiBaseUrl = env.VITE_API_BASE_URL?.trim();
  let apiUrl;
  try {
    apiUrl = new URL(apiBaseUrl);
  } catch {
    apiUrl = null;
  }
  if (mode === 'production' && (
    !apiUrl
    || apiUrl.protocol !== 'https:'
    || ['localhost', '127.0.0.1', '[::1]'].includes(apiUrl.hostname)
    || apiUrl.hostname === 'example.com'
    || apiUrl.hostname.endsWith('.example.com')
  )) {
    throw new Error('Set VITE_API_BASE_URL to the deployed HTTPS backend URL before building for production.');
  }

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
    },
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
  };
});