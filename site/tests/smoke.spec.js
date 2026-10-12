import { test, expect } from '@playwright/test';

// Every page must load without an uncaught JavaScript error.
let pageErrors;
test.beforeEach(({ page }) => {
  pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));
});
test.afterEach(() => {
  expect(pageErrors, 'uncaught JavaScript errors').toEqual([]);
});

const N = '33,622';

test.describe('essay', () => {
  test('renders in English with the corpus size', async ({ page }) => {
    await page.goto('?lang=en');
    await expect(page.locator('.hero h1')).toContainText('Looks Like');
    await expect(page.locator('[data-i18n="hero_dek"]')).toContainText(N);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  });

  test('switches to Spanish', async ({ page }) => {
    await page.goto('?lang=en');
    const kicker = page.locator('[data-i18n="hero_kicker"]');
    const en = await kicker.textContent();
    await page.locator('[data-lang-btn="es"]').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'es');
    await expect(kicker).not.toHaveText(en);
    await expect(page.locator('[data-i18n="hero_dek"]')).toContainText(N);
  });

  test('studios teaser and sources link to the studios page', async ({ page }) => {
    await page.goto('?lang=en');
    await expect(page.locator('#studios-teaser .studios-card')).toHaveCount(3);
    await expect(page.locator('#studios-teaser a[href*="studios/"]').last()).toBeVisible();
    await expect(page.locator('[data-i18n="sources_reading"] a')).toHaveAttribute(
      'href',
      'studios/#st-reading-title',
    );
  });

  test('social card is published', async ({ request }) => {
    const res = await request.get('assets/og-card.jpg');
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toContain('image/jpeg');
  });
});

test.describe('autopsy', () => {
  test('opens from a deep link, shows the beats, and closes', async ({ page }) => {
    await page.goto('?id=948&lang=es');
    await expect(page.locator('body')).toHaveClass(/au-open/);
    const color = page.locator('.au-beat[data-beat="color"]');
    await expect(color).toContainText('Sangre CLIP');
    await expect(color).not.toContainText('Sangre CLIP —');
    await expect(page.locator('.au-beat[data-beat="object"] .au-beat-credit a')).toHaveAttribute(
      'href',
      /studios\/\?lang=es#/,
    );
    await page.locator('#au-close').click();
    await expect(page.locator('body')).not.toHaveClass(/au-open/);
  });

  test('switches to an alternate sheet with its own CLIP score', async ({ page }) => {
    await page.goto('?id=948&lang=en');
    await expect(page.locator('body')).toHaveClass(/au-open/);
    const alt = page.locator('#au-alts .au-alt:not(.is-measured)').first();
    await alt.click();
    await expect(alt).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.au-beat[data-beat="color"]')).not.toContainText('CLIP blood —');
  });

  test('opens from search', async ({ page }) => {
    await page.goto('?lang=en');
    // The search module mounts lazily once #lookup nears the viewport; its
    // starter picks render when it is wired.
    await page.locator('#lookup').scrollIntoViewIfNeeded();
    await expect(page.locator('#au-picks > *').first()).toBeAttached();
    await page.locator('#lk-q').pressSequentially('Halloween');
    const first = page.locator('#lk-suggest li').first();
    await expect(first).toContainText('Halloween');
    await first.click();
    await expect(page.locator('body')).toHaveClass(/au-open/);
  });
});

test.describe('studios page', () => {
  test('lists the studios and the further reading', async ({ page }) => {
    await page.goto('studios/?lang=es');
    await expect(page.locator('h1')).toHaveText('Quién diseña el miedo');
    await expect(page.locator('.st-item')).toHaveCount(27);
    await expect(page.locator('#st-books li')).toHaveCount(7);
    const toggle = page.locator('.st-toggle:not([hidden])').first();
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  test('fits a phone screen without horizontal scroll', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('studios/?lang=en');
    await expect(page.locator('.st-item')).toHaveCount(27);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(overflow).toBe(false);
  });

  test('closing an autopsy opened from studios returns to studios', async ({ page }) => {
    await page.goto('studios/?lang=en');
    await page.locator('.st-strip a').first().click();
    await expect(page.locator('body')).toHaveClass(/au-open/);
    await expect(page).toHaveURL(/from=studios/);
    await page.locator('#au-close').click();
    await expect(page).toHaveURL(/\/studios\//);
    await expect(page.locator('.st-item')).toHaveCount(27);
  });
});
