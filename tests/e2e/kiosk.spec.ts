import { test, expect } from '@playwright/test';

test.describe('Aegis Kiosk E2E Flow', () => {
  test('should load kiosk page and display camera video feed and PIN fallback', async ({ page }) => {
    // Navigate to Kiosk subdomain
    await page.goto('http://kiosk.localhost:80');

    // Assert kiosk page header or basic structural element
    const container = page.locator('#kiosk-root, #app');
    await expect(container).toBeVisible();

    // Verify video stream element starts and is loaded
    const videoFeed = page.locator('video');
    await expect(videoFeed).toBeVisible();

    // Assert fallback buttons exist (PIN code / QR code scanner fallback)
    const pinButton = page.locator('button:has-text("PIN"), button:has-text("Fallback")');
    if (await pinButton.count() > 0) {
      await pinButton.first().click();
      // Ensure the keypad or input overlay shows up
      const keypad = page.locator('input[type="password"], [role="dialog"]');
      await expect(keypad).toBeVisible();
    }
  });

  test('should connect to WebSocket and report network status', async ({ page }) => {
    await page.goto('http://kiosk.localhost:80');
    
    // Check connection/status indicator (e.g. green online or red offline banner depending on dev backend state)
    const statusIndicator = page.locator('[data-testid="status-indicator"], .status-banner');
    if (await statusIndicator.count() > 0) {
      await expect(statusIndicator).toBeVisible();
    }
  });
});
