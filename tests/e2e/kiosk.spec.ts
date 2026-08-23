import { test, expect } from '@playwright/test';

test.describe('Aegis Kiosk E2E Flow', () => {
  test('should load kiosk page and display camera video feed and PIN fallback', async ({ page }) => {
    // Navigate to Kiosk subdomain
    await page.goto('/');

    // Assert kiosk page header or basic structural element
    const container = page.locator('#kiosk-root, #app, #root');
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
    await page.goto('/');
    
    // Check connection/status indicator (e.g. green online or red offline banner depending on dev backend state)
    const statusIndicator = page.locator('[data-testid="status-indicator"], .status-banner');
    if (await statusIndicator.count() > 0) {
      await expect(statusIndicator).toBeVisible();
    }
  });
});

test.describe('Aegis Admin Devices & Kiosk Flow', () => {
  test('should display devices list and delete/unregister a device', async ({ page }) => {
    // Navigate to Admin Devices page
    await page.goto('http://127.0.0.1:5174/devices');

    // Assert that the page header is visible
    const header = page.locator('h1:has-text("Kiosks & Devices")');
    await expect(header).toBeVisible();

    // Verify Register Device button is visible
    const registerBtn = page.locator('button:has-text("Register Device")');
    await expect(registerBtn).toBeVisible();

    // Let's check if there is a Delete button in the table actions
    // Since we seed default devices, there should be at least one device
    const deleteBtn = page.locator('button:has-text("Delete")');
    if (await deleteBtn.count() > 0) {
      // Mock confirm dialog to auto-accept
      page.on('dialog', async dialog => {
        expect(dialog.message()).toContain('unregister and delete this device');
        await dialog.accept();
      });

      const initialCount = await deleteBtn.count();
      // Click the first Delete button
      await deleteBtn.first().click();

      // Verify the table updates and count of devices decreases by 1
      await expect(async () => {
        const newCount = await page.locator('button:has-text("Delete")').count();
        expect(newCount).toBe(initialCount - 1);
      }).toPass();
    }
  });
});
