import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, '.', '');
    return {
      server: {
        port: env.PORT ? Number(env.PORT) : 5173,
        host: '0.0.0.0',
      },
      plugins: [react(), basicSsl()],
      // No API keys are compiled into the app: each user enters their own Gemini
      // key in Settings (the kiosk reads it from ~/.config/gemini-pupper/api_key).
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      }
    };
});
