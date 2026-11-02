import { test, expect } from "@playwright/test";

test("first visit offers a tour, dismissal persists and Help reopens it", async ({
  page,
}) => {
  await page.goto("/?format=modern&tab=deckbuilder");
  const welcome = page.getByRole("dialog", {
    name: "Dalla lista al piano per il torneo",
  });
  await expect(welcome).toBeVisible();
  await welcome.getByRole("button", { name: "Esploro da solo" }).click();
  await page.reload();
  await expect(welcome).toHaveCount(0);
  await page.getByRole("button", { name: "Aiuto e percorso iniziale" }).click();
  await expect(welcome).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(welcome).toHaveCount(0);
});

test("tour navigates real sections, keeps the app interactive and preserves its step across settings", async ({
  page,
}) => {
  await page.goto("/?format=modern&tab=playtest");
  await page.getByRole("button", { name: "Inizia il percorso" }).click();
  const tour = page.getByRole("dialog", { name: "Parti dal formato" });
  await expect(tour).toBeVisible();
  await expect(page).toHaveURL(/tab=format_info/);
  await page.getByRole("button", { name: /^pioneer/i }).click();
  await expect(page).toHaveURL(/format=pioneer/);
  await expect(
    page.locator('[data-tour="formats"][data-tour-active]'),
  ).toBeVisible();
  for (const tab of ["deckbuilder", "meta", "ai_studio"]) {
    await page.getByRole("button", { name: "Avanti", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`tab=${tab}`));
  }
  await page
    .getByRole("button", { name: "Apri impostazioni AI", exact: true })
    .click();
  await expect(
    page.getByText("Impostazioni", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.locator(".onboarding-coach")).toHaveCount(0);
  await page.getByRole("button", { name: "Chiudi", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Usa l’AI con un obiettivo concreto" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Avanti", exact: true }).click();
  await expect(page).toHaveURL(/tab=playtest/);
  await page.getByRole("button", { name: "Avanti", exact: true }).click();
  await expect(page).toHaveURL(/tab=library/);
  await page.getByRole("button", { name: "Fine", exact: true }).click();
  await expect(page.locator(".onboarding-coach")).toHaveCount(0);
  expect(
    await page.evaluate(() => localStorage.getItem("aetherdeck.onboarding.v1")),
  ).toBe("seen");
});

test("mobile tour fits viewport and all navigation remains reachable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?format=modern&tab=deckbuilder");
  await page.getByRole("button", { name: "Inizia il percorso" }).click();
  await page.getByRole("button", { name: "Vai alla tappa 5" }).click();
  await expect(page).toHaveURL(/tab=playtest/);
  const coach = page.locator(".onboarding-coach");
  const box = await coach.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await expect(
    page.getByRole("button", { name: "Avanti", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: "../tmp/qa/onboarding-mobile.png" });
  await page.getByRole("button", { name: "Chiudi percorso" }).click();
  await expect(coach).toHaveCount(0);
});
