import { test, expect } from '@playwright/test';

test.describe('Device Registration & Unregistration Lifecycle Flow', () => {
  test('should pair, connect, and auto-disconnect upon unregistration', async ({ page }) => {
    // 1. Navigate to Admin Devices page
    await page.goto('http://127.0.0.1:5174/devices');

    // 2. Click "Register Device" button
    await page.click('button:has-text("Register Device")');

    // 3. Select a location and submit
    await page.locator('select[name="form_factor"]').selectOption('tablet');
    await page.click('button:has-text("Generate Pairing Code")');

    // 4. Capture the pairing code from the UI
    const codeContainer = page.locator('div.font-mono.text-4xl');
    await expect(codeContainer).toBeVisible();
    const pairingCode = (await codeContainer.innerText()).trim();
    expect(pairingCode.length).toBe(8);

    // Click "Done" on the modal
    await page.click('button:has-text("Done")');

    // 5. Simulate Kiosk Pairing via API call
    const pairResponse = await page.request.post('http://127.0.0.1:8001/api/kiosk/pair', {
      data: { pairing_code: pairingCode }
    });
    expect(pairResponse.ok()).toBe(true);
    const pairData = await pairResponse.json();
    const newDeviceToken = pairData.device_token;
    const newDeviceId = pairData.device_id;

    // 6. Navigate to Kiosk and inject the paired token into localStorage
    await page.goto('http://127.0.0.1:5173');
    await page.evaluate((token) => {
      localStorage.setItem('aegis_device_token', token);
    }, newDeviceToken);

    // Reload the Kiosk page to load the new token
    await page.reload();

    // Verify it displays connected status after clicking Connect Kiosk
    const connectBtn = page.locator('button:has-text("Connect Kiosk")');
    if (await connectBtn.isVisible()) {
      await connectBtn.click();
    }
    await expect(page.locator('text=Connected')).toBeVisible();

    // 7. Go back to Admin page and Delete/Unregister the device
    await page.goto('http://127.0.0.1:5174/devices');

    // Locate the delete button for the newly created device by its ID prefix
    const deviceIdPrefix = newDeviceId.substring(0, 8);
    const row = page.locator(`tr:has-text("${deviceIdPrefix}")`);
    const deleteBtn = row.locator('button:has-text("Delete")');

    // Setup dialog handler to auto-confirm deletion
    page.on('dialog', async dialog => {
      expect(dialog.message()).toContain('unregister and delete this device');
      await dialog.accept();
    });

    await deleteBtn.click();
    // Wait for the row to disappear
    await expect(row).not.toBeVisible();

    // 8. Go back to the Kiosk, reload, and verify token exchange fails (goes back to disconnected)
    await page.goto('http://127.0.0.1:5173');
    const connectBtnAfter = page.locator('button:has-text("Connect Kiosk")');
    if (await connectBtnAfter.isVisible()) {
      await connectBtnAfter.click();
    }

    // Since the token is deleted, it should return 401, clear localStorage, and stay Offline/Disconnected
    await expect(page.locator('text=Kiosk Offline')).toBeVisible();
    
    // Verify that localStorage was reset back to default
    const storedToken = await page.evaluate(() => localStorage.getItem('aegis_device_token'));
    expect(storedToken).toBeNull(); // localStorage is cleared on 401
  });
});
