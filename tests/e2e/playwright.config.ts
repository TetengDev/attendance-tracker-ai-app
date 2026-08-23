import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for E2E Kiosk and Admin flow tests.
 * Launches Chromium with fake webcam options using a Y4M camera video stream.
 */
export default defineConfig({
  testDir: '.',
  timeout: 30 * 1000,
  expect: {
    timeout: 5000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium-fake-camera',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          args: [
            '--use-fake-ui-for-media-stream',
            '--use-fake-device-for-media-stream',
            // Pass fake camera y4m file if available
            '--use-file-for-fake-video-capture=fixtures/fake_camera.y4m',
          ],
        },
      },
    },
  ],
});
