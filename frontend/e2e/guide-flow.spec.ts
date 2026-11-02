import { test, expect, type Page } from "@playwright/test";

let deck: any;
const archivedGuide = {
  deck_name: "Guida storica di prova",
  pro_score: 7,
  executive_summary: "Contenuto della precedente versione",
  rules_warnings: ["Errore della versione storica"],
};
const approvedGuide = {
  deck_name: "Nuova guida revisionata",
  format_id: "modern",
  pro_score: 7,
  executive_summary: "Contenuto corretto dopo la revisione",
  generated_at: "2026-11-02T16:30:00Z",
  quality_review: { status: "passed", revision_count: 2 },
  meta_estimate: {
    status: "available",
    weighted_winrate_pct: 52,
    coverage_pct: 50,
    uncovered_share_pct: 50,
    formula: "Somma(quota × WR) / quote coperte",
    note: "Stima teorica AI, non risultati di partite.",
    rows: [
      { archetype: "Aggro", share_pct: 30, winrate_pct: 60 },
      { archetype: "Control", share_pct: 20, winrate_pct: 40 },
    ],
  },
};

test.beforeAll(async ({ request }) => {
  const result = await request.post("/api/decks/import", {
    data: { name: "QA · Guide flow", format_id: "modern", text: "60 Mountain" },
  });
  expect(result.ok()).toBeTruthy();
  deck = (await result.json()).deck;
});
test.afterAll(async ({ request }) => {
  if (deck) await request.delete(`/api/decks/${deck.id}`);
});

async function openGuide(page: Page) {
  await page.route("**/api/settings", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      json: { ...(await response.json()), has_gemini_api_key: true },
    });
  });
  await page.goto("/?format=modern&tab=ai");
  await page.getByRole("button", { name: "AI Studio", exact: true }).click();
  await page
    .getByRole("button", { name: "Guida e sideboard", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Lista da analizzare" })
    .selectOption(String(deck.id));
}

test("failed regeneration removes the old guide; retry shows only the approved weighted result", async ({
  page,
}) => {
  await page.route(`**/api/decks/${deck.id}`, (route) =>
    route.fulfill({ json: { ...deck, guide_json: archivedGuide } }),
  );
  let complete: (() => void) | undefined;
  let attempts = 0;
  await page.route("**/api/ai/deck-guide", async (route) => {
    attempts++;
    await new Promise<void>((resolve) => {
      complete = resolve;
    });
    await route.fulfill(
      attempts === 1
        ? {
            status: 400,
            json: { detail: "Guida non salvata: revisione non superata" },
          }
        : { json: { guide: approvedGuide, meta: { guide_id: 1234 } } },
    );
  });
  await openGuide(page);
  await expect(
    page.getByRole("heading", { name: archivedGuide.deck_name }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Genera nuova versione" }).click();
  await expect(page.getByText("Preparazione della nuova guida")).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Lista da analizzare" }),
  ).toBeDisabled();
  await expect(page.locator(".guide-reader")).toHaveCount(0);
  await expect.poll(() => !!complete).toBeTruthy();
  complete!();
  await expect(page.getByRole("alert")).toContainText(
    "Nessuna nuova versione salvata",
  );
  await expect(page.locator(".guide-reader")).toHaveCount(0);
  complete = undefined;
  await page.getByRole("button", { name: "Genera e salva guida" }).click();
  await expect.poll(() => !!complete).toBeTruthy();
  complete!();
  await expect(
    page.getByRole("heading", { name: approvedGuide.deck_name }),
  ).toBeVisible();
  await expect(page.getByText("52.0%", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("2 cicli di correzione");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("Non disponibile", { exact: true })).toHaveCount(
    0,
  );
  await page.getByText("Copertura 50% · Formula e matchup").click();
  await expect(
    page.getByRole("cell", { name: "Aggro", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../tmp/qa/guide-approved.png",
    fullPage: true,
  });
});

test("a late response loading an archived guide cannot replace the newly generated guide", async ({
  page,
}) => {
  let releaseArchive: (() => void) | undefined;
  await page.route(`**/api/decks/${deck.id}`, async (route) => {
    await new Promise<void>((resolve) => {
      releaseArchive = resolve;
    });
    await route.fulfill({ json: { ...deck, guide_json: archivedGuide } });
  });
  await page.route("**/api/ai/deck-guide", (route) =>
    route.fulfill({ json: { guide: approvedGuide, meta: { guide_id: 1234 } } }),
  );
  await openGuide(page);
  await expect.poll(() => !!releaseArchive).toBeTruthy();
  await page.getByRole("button", { name: "Genera e salva guida" }).click();
  await expect(
    page.getByRole("heading", { name: approvedGuide.deck_name }),
  ).toBeVisible();
  const lateResponse = page.waitForResponse(`**/api/decks/${deck.id}`);
  releaseArchive!();
  await lateResponse;
  await expect(
    page.getByRole("heading", { name: archivedGuide.deck_name }),
  ).toHaveCount(0);
  await expect(page.getByText("52.0%", { exact: true })).toBeVisible();
});
