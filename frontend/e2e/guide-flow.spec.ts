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
  legality: {
    status: "legal",
    format_id: "modern",
    issues: [],
    checked_at: "2026-11-02T16:30:00Z",
    catalog_synced_at: "2026-11-02T08:00:00Z",
  },
  meta_estimate: {
    status: "available",
    weighted_winrate_pct: 52,
    coverage_pct: 50,
    uncovered_share_pct: 50,
    // Older guides still carry the formula: the reader must not show it.
    formula: "Somma(quota × WR) / quote coperte",
    note: "Su 50% del meta. Stima teorica, non risultati di partite.",
    rows: [
      { archetype: "Aggro", share_pct: 30, winrate_pct: 60 },
      { archetype: "Control", share_pct: 20, winrate_pct: 40 },
    ],
  },
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("aetherdeck.onboarding.v1", "seen"),
  );
});
test.beforeAll(async ({ request }) => {
  const r = await request.post("/api/decks/import", {
    data: { name: "QA · Guide flow", format_id: "modern", text: "60 Mountain" },
  });
  expect(r.ok()).toBeTruthy();
  deck = (await r.json()).deck;
});
test.afterAll(async ({ request }) => {
  if (deck) await request.delete(`/api/decks/${deck.id}`);
});
async function openGuide(page: Page, select = true) {
  await page.route("**/api/settings", async (route) => {
    const r = await route.fetch();
    await route.fulfill({
      json: { ...(await r.json()), has_gemini_api_key: true },
    });
  });
  await page.goto("/?format=modern&tab=ai_studio");
  await page
    .getByRole("button", { name: "Guida e sideboard", exact: true })
    .click();
  if (select)
    await page
      .getByRole("combobox", { name: "Lista da analizzare" })
      .selectOption(String(deck.id));
}
function job(id = 100) {
  return {
    id,
    deck_id: deck.id,
    format_id: "modern",
    deck_name: deck.name,
    model_id: "gemini-3.8-flash",
    status: "running",
    phase: "oracle_review",
    has_draft: true,
    created_at: new Date().toISOString(),
    budget_seconds: 240,
  };
}

test("failed verification preserves draft; resume completes without generating again", async ({
  page,
}) => {
  let current: any = null,
    starts = 0,
    resumes = 0;
  await page.route("**/api/ai/guide-jobs**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST") {
      if (url.pathname.endsWith("/resume")) {
        resumes++;
        current = { ...job(101) };
      } else {
        starts++;
        current = job();
      }
      await route.fulfill({ json: current });
    } else if (/\/guide-jobs\/\d+$/.test(url.pathname))
      await route.fulfill({ json: current });
    else await route.fulfill({ json: { jobs: [], legacy_drafts: [] } });
  });
  await page.route(`**/api/decks/${deck.id}`, (route) =>
    route.fulfill({ json: { ...deck, guide_json: archivedGuide } }),
  );
  await openGuide(page);
  await expect(
    page.getByRole("heading", { name: archivedGuide.deck_name }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Genera nuova versione" }).click();
  await expect(
    page.getByRole("region", { name: "Stato generazione guida" }),
  ).toContainText("Revisione delle regole");
  await expect(page.locator(".guide-reader")).toHaveCount(0);
  current = {
    ...current,
    status: "failed",
    error: "La verifica richiede un altro passaggio.",
  };
  await expect(
    page.getByRole("button", { name: "Riprendi revisione della bozza" }),
  ).toBeVisible();
  await expect(page.locator(".guide-reader")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Riprendi revisione della bozza" })
    .click();
  current = {
    ...current,
    status: "completed",
    result: { guide: approvedGuide, meta: { guide_id: 1234 } },
  };
  await expect(
    page.getByRole("heading", { name: approvedGuide.deck_name }),
  ).toBeVisible();
  await expect(page.getByText("52%", { exact: true })).toBeVisible();
  await expect(page.getByText(/Lista legale in Modern/)).toBeVisible();
  await expect(page.getByText(/Somma\(/)).toHaveCount(0);
  expect(starts).toBe(1);
  expect(resumes).toBe(1);
  await page.screenshot({ path: "../tmp/qa/guide-job-completed.png" });
});

test("archived guide with open issues completes its review from the same text", async ({
  page,
}) => {
  const unfinished = {
    ...approvedGuide,
    deck_name: "Guida con rilievi aperti",
    quality_review: {
      status: "warnings",
      open_issues: ["Correzione proposta ma non verificata: esempio"],
    },
    legality: {
      status: "not_legal",
      format_id: "modern",
      issues: ["Mountain è bandita in Modern."],
    },
  };
  let completes = 0;
  await page.route(`**/api/decks/${deck.id}`, (route) =>
    route.fulfill({ json: { ...deck, guide_json: unfinished } }),
  );
  await page.route("**/api/guides?**", (route) =>
    route.fulfill({ json: [{ id: 77, deck_id: deck.id }] }),
  );
  await page.route("**/api/guides/77/complete-review", (route) => {
    completes++;
    return route.fulfill({ json: job(200) });
  });
  await page.route("**/api/ai/guide-jobs**", (route) =>
    /\/guide-jobs\/\d+$/.test(new URL(route.request().url()).pathname)
      ? route.fulfill({ json: job(200) })
      : route.fulfill({ json: { jobs: [], legacy_drafts: [] } }),
  );
  await openGuide(page);
  await expect(page.getByText("Mountain è bandita in Modern.")).toBeVisible();
  await expect(page.getByText(/Lista legale in/)).toHaveCount(0);
  await page.getByRole("button", { name: "Completa la revisione" }).click();
  await expect(
    page.getByRole("region", { name: "Stato generazione guida" }),
  ).toContainText("Revisione delle regole");
  expect(completes).toBe(1);
});

test("running analysis survives reload and cancellation does not show an approved guide", async ({
  page,
}) => {
  let current: any = job();
  await page.route("**/api/ai/guide-jobs**", async (route) => {
    if (route.request().method() === "POST") {
      current = { ...current, status: "cancelled" };
      await route.fulfill({ json: current });
    } else if (
      /\/guide-jobs\/\d+$/.test(new URL(route.request().url()).pathname)
    )
      await route.fulfill({ json: current });
    else await route.fulfill({ json: { jobs: [current], legacy_drafts: [] } });
  });
  await openGuide(page, false);
  await expect(
    page.getByRole("button", { name: "Annulla analisi" }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Lista da analizzare" }),
  ).toHaveValue(String(deck.id));
  await page.reload();
  await page
    .getByRole("button", { name: "Guida e sideboard", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Annulla analisi" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Annulla analisi" }).click();
  await expect(
    page.getByRole("region", { name: "Stato generazione guida" }),
  ).toContainText("Analisi annullata");
  await expect(page.locator(".guide-reader")).toHaveCount(0);
});

test("a late archived response cannot overwrite a job result", async ({
  page,
}) => {
  let release: (() => void) | undefined;
  await page.route(`**/api/decks/${deck.id}`, async (route) => {
    await new Promise<void>((resolve) => (release = resolve));
    await route.fulfill({ json: { ...deck, guide_json: archivedGuide } });
  });
  let current: any = null;
  await page.route("**/api/ai/guide-jobs**", async (route) => {
    if (route.request().method() === "POST") {
      current = {
        ...job(),
        status: "completed",
        result: { guide: approvedGuide, meta: { guide_id: 1234 } },
      };
      await route.fulfill({ json: { ...current, status: "running" } });
    } else if (
      /\/guide-jobs\/\d+$/.test(new URL(route.request().url()).pathname)
    )
      await route.fulfill({ json: current });
    else await route.fulfill({ json: { jobs: [], legacy_drafts: [] } });
  });
  await openGuide(page);
  await expect.poll(() => !!release).toBeTruthy();
  await page.getByRole("button", { name: "Genera e salva guida" }).click();
  await expect(
    page.getByRole("heading", { name: approvedGuide.deck_name }),
  ).toBeVisible();
  const response = page.waitForResponse(`**/api/decks/${deck.id}`);
  release!();
  await response;
  await expect(
    page.getByRole("heading", { name: archivedGuide.deck_name }),
  ).toHaveCount(0);
});

test("explicit identical play/draw sidata displays the complete base plan", async ({
  page,
}) => {
  const guide = {
    ...approvedGuide,
    sideboard_guide: [
      {
        opponent_archetype: "Aggro",
        expected_winrate_pct: 60,
        cards_in: [{ card_name: "Plains", quantity: 1, reason: "Mana" }],
        cards_out: [{ card_name: "Mountain", quantity: 1, reason: "Cambio" }],
        on_the_play_uses_base: true,
        on_the_draw_uses_base: true,
        on_the_play_in: [],
        on_the_play_out: [],
        on_the_draw_in: [],
        on_the_draw_out: [],
      },
    ],
  };
  await page.route("**/api/ai/guide-jobs**", async (route) => {
    if (route.request().method() === "POST")
      await route.fulfill({ json: job() });
    else if (/\/guide-jobs\/\d+$/.test(new URL(route.request().url()).pathname))
      await route.fulfill({
        json: {
          ...job(),
          status: "completed",
          result: { guide, meta: { guide_id: 1234 } },
        },
      });
    else await route.fulfill({ json: { jobs: [], legacy_drafts: [] } });
  });
  await openGuide(page);
  await page.getByRole("button", { name: "Genera e salva guida" }).click();
  const reader = page.locator(".guide-reader");
  await expect(reader).toBeVisible();
  await reader
    .getByRole("button", { name: "On the play", exact: true })
    .click();
  await expect(reader.getByText(/Stessa sidata del piano base/)).toBeVisible();
  // The sideboard matrix names the same card: the last button is the one in the plan.
  await expect(
    reader.getByRole("button", { name: "Plains", exact: true }).last(),
  ).toBeVisible();
  await reader
    .getByRole("button", { name: "On the draw", exact: true })
    .click();
  await expect(
    reader.getByRole("button", { name: "Mountain", exact: true }).last(),
  ).toBeVisible();
  await expect(
    reader.getByText(/Questa versione non contiene una sidata distinta/),
  ).toHaveCount(0);
});
