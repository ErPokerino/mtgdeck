import { test, expect } from "@playwright/test";
import { faceCard, canFlip } from "../src/components/playtest/cardState";
import {
  moved,
  keep,
  newGame,
  type Instance,
} from "../src/components/playtest/playtestState";

let fixture: any, fable: any, token: any;
test.beforeAll(async ({ request }) => {
  const result = await request.post("/api/decks/import", {
    data: {
      name: "QA · Fable interaction fixture",
      format_id: "modern",
      text: "Deck\n4 Fable of the Mirror-Breaker\n56 Mountain\n\nSideboard\n15 Plains",
    },
  });
  expect(result.ok(), await result.text()).toBeTruthy();
  fixture = (await result.json()).deck;
  fable = fixture.cards.find((c: any) => c.card_name.startsWith("Fable")).card;
  token = {
    ...fable,
    oracle_id: "qa-token",
    scryfall_id: "qa-token",
    layout: "token",
    name: "Goblin Shaman",
    type_line: "Token Creature — Goblin Shaman",
    power: "2",
    toughness: "2",
    oracle_text: "Whenever this creature attacks, create a Treasure token.",
    card_faces: [],
    image_uris: {},
  };
});
test.afterAll(async ({ request }) => {
  if (fixture) await request.delete(`/api/decks/${fixture.id}`);
});

async function openPlaytest(page: any) {
  await page.goto("/?format=modern&tab=playtest");
  await page
    .getByRole("combobox", { name: "Mazzo playtest" })
    .selectOption(String(fixture.id));
  await expect(
    page.getByRole("button", { name: "Tieni mano (7)" }),
  ).toBeVisible();
}
async function getFable(page: any) {
  await page.getByRole("button", { name: "Tieni mano (7)" }).click();
  if (
    (await page
      .locator('[data-card-name^="Fable"][data-zone="hand"]')
      .count()) === 0
  ) {
    await page.getByRole("button", { name: /Grimorio \(/ }).click();
    await page
      .getByRole("textbox", { name: "Cerca in Grimorio" })
      .fill("Fable");
    await page
      .getByRole("button", { name: "In mano", exact: true })
      .first()
      .click();
  }
  return page.locator('[data-card-name^="Fable"][data-zone="hand"]').first();
}

test("pure state: DFC face and counters reset across zones, tokens cease", async () => {
  expect(canFlip(fable)).toBeTruthy();
  expect(faceCard(fable, 1).name).toContain("Reflection");
  const inst: Instance = {
    uid: "x",
    card: fable,
    zone: "permanents",
    face: 1,
    counters: 3,
    tapped: true,
    isToken: false,
  };
  const next = moved([inst], "x", "hand")[0];
  expect([next.face, next.counters, next.tapped]).toEqual([0, 0, false]);
  expect(moved([{ ...inst, isToken: true }], "x", "graveyard")).toEqual([]);
  expect(canFlip({ ...fable, layout: "adventure" })).toBeFalsy();
});

test("pure state: London mulligan requires exact selected hand cards", async () => {
  const game = newGame(fixture, 2);
  expect(keep(game, []).opening).toBeTruthy();
  const hand = game.cards.filter((c) => c.zone === "hand");
  const next = keep(
    game,
    hand.slice(0, 2).map((c) => c.uid),
  );
  expect(next.opening).toBeFalsy();
  expect(next.cards.filter((c) => c.zone === "hand")).toHaveLength(5);
  expect(next.cards.filter((c) => c.zone === "library")).toHaveLength(55);
});

test("library has clear storage, archive and version navigation", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/?format=modern&tab=library");
  await expect(
    page.getByRole("heading", { name: "Mazzi e guide", exact: true }),
  ).toBeVisible();
  await page
    .getByPlaceholder("Cerca per nome o archetipo")
    .fill("Fable interaction");
  const card = page.locator("section").filter({
    has: page.getByRole("heading", { name: fixture.name, exact: true }),
  });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Versioni" }).click();
  await expect(
    page.getByRole("dialog", { name: "Versioni del mazzo" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Chiudi", exact: true }).click();
  await card.getByRole("button", { name: "Archivia", exact: true }).click();
  await page.getByRole("button", { name: "Archiviati", exact: true }).click();
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Ripristina", exact: true }).click();
  await expect(card).not.toBeVisible();
  expect(errors).toEqual([]);
});

test("playtest: London mulligan cannot be bypassed by playing or drawing", async ({
  page,
}) => {
  await openPlaytest(page);
  await page.getByRole("button", { name: "Mulligan a 6" }).click();
  await expect(
    page.getByRole("button", { name: "Tieni mano (6)" }),
  ).toBeDisabled();
  await expect(page.getByRole("button", { name: /Pesca 1 \(/ })).toBeDisabled();
  const hand = page.locator('[data-testid="playtest-card"][data-zone="hand"]');
  await expect(hand).toHaveCount(7);
  await expect(
    hand.first().getByRole("button", { name: "Gioca", exact: true }),
  ).toBeDisabled();
  await hand
    .first()
    .getByRole("button", { name: /Esamina/ })
    .click();
  await page.getByRole("button", { name: "Tieni mano (6)" }).click();
  await expect(hand).toHaveCount(6);
  await expect(page.getByRole("button", { name: /Pesca 1 \(/ })).toBeEnabled();
});

test("playtest: Fable transforms and returns to its front in hand", async ({
  page,
}) => {
  await openPlaytest(page);
  const card = await getFable(page);
  await card.getByRole("button", { name: "Gioca", exact: true }).click();
  const permanent = page
    .locator('[data-card-name^="Fable"][data-zone="permanents"]')
    .first();
  await permanent.getByRole("button", { name: /Azioni/ }).click();
  const dialog = page.getByRole("dialog", { name: "Azioni carta" });
  await dialog.getByRole("button", { name: "Gira carta · retro" }).click();
  await expect(
    dialog.getByRole("heading", { name: "Reflection of Kiki-Jiki" }),
  ).toBeVisible();
  await dialog
    .getByRole("combobox", { name: "Sposta carta in" })
    .selectOption("hand");
  await expect(
    page.locator('[data-card-name^="Fable"][data-zone="hand"]'),
  ).toHaveCount(1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../tmp/qa/playtest-desktop.png",
    fullPage: true,
  });
});

test("playtest: official and custom tokens, token removal, undo", async ({
  page,
}) => {
  await page.route("**/api/cards/*/tokens", (route) =>
    route.fulfill({ json: [token] }),
  );
  await openPlaytest(page);
  const card = await getFable(page);
  await card.getByRole("button", { name: "Gioca", exact: true }).click();
  await page
    .locator('[data-card-name^="Fable"][data-zone="permanents"]')
    .first()
    .getByRole("button", { name: /Azioni/ })
    .click();
  const dialog = page.getByRole("dialog", { name: "Azioni carta" });
  await dialog.getByRole("button", { name: "Cerca pedine ufficiali" }).click();
  await dialog.getByRole("button", { name: "Crea Goblin Shaman 2/2" }).click();
  await expect(
    dialog.getByRole("heading", { name: "Goblin Shaman", level: 2 }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../tmp/qa/playtest-token.png",
    fullPage: true,
  });
  await dialog
    .getByRole("combobox", { name: "Sposta carta in" })
    .selectOption("graveyard");
  await expect(page.locator('[data-card-name="Goblin Shaman"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Annulla", exact: true }).click();
  await expect(page.locator('[data-card-name="Goblin Shaman"]')).toHaveCount(1);
  await page
    .locator('[data-card-name="Goblin Shaman"]')
    .getByRole("button", { name: /Azioni/ })
    .click();
  await dialog.getByText("Crea pedina personalizzata", { exact: true }).click();
  await dialog
    .getByRole("textbox", { name: "Nome pedina" })
    .fill("Treasure custom");
  await dialog
    .getByRole("button", { name: "Crea pedina", exact: true })
    .click();
  await expect(
    dialog.getByRole("heading", { name: "Treasure custom", level: 2 }),
  ).toBeVisible();
});

test("sideboard changes cancel without changing the ongoing configuration", async ({
  page,
}) => {
  await openPlaytest(page);
  await page
    .getByRole("button", { name: "Sideboard (15)", exact: true })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Configurazione sideboard" });
  await dialog
    .getByRole("button", { name: /Fable.*SIDE/ })
    .first()
    .click();
  await expect(
    dialog.getByRole("button", { name: "Avvia partita post-sideboard" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "Annulla modifiche" }).click();
  await expect(
    page.getByRole("button", { name: "Sideboard (15)" }).first(),
  ).toBeVisible();
});

test("AI selectors agree and expose two strategic models", async ({ page }) => {
  await page.goto("/?format=modern&tab=ai_studio");
  const studio = page.getByRole("combobox", { name: "Modello strategico" });
  await expect(studio.locator("option")).toHaveCount(2);
  await expect(studio).toHaveValue(
    await page.locator("header select").inputValue(),
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "../tmp/qa/ai-studio.png", fullPage: true });
});

test("draft name survives navigation and reload", async ({ page }) => {
  await page.goto("/?format=standard&tab=deckbuilder");
  const input = page.getByPlaceholder("Nome del mazzo...");
  await input.fill("QA browser draft");
  await page
    .getByRole("button", { name: "Mazzi e guide", exact: true })
    .click();
  await page.getByRole("button", { name: "Deck Builder", exact: true }).click();
  await expect(input).toHaveValue("QA browser draft");
  page.on("dialog", (dialog) => dialog.accept());
  await page.reload();
  await expect(input).toHaveValue("QA browser draft");
});

test("responsive library navigation remains accessible at 390px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?format=modern&tab=library");
  await expect(
    page.getByRole("heading", { name: "Mazzi e guide", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page.getByText("Caricamento archivio…")).not.toBeVisible();
  await page.screenshot({
    path: "../tmp/qa/library-mobile.png",
    fullPage: true,
  });
  const width = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(width.content).toBeLessThanOrEqual(width.viewport);
});

test("saved guide exposes weighted estimate, coverage and downloadable PDF", async ({
  page,
  request,
}) => {
  const guides = await (
    await request.get("/api/guides?format_id=modern")
  ).json();
  const g = guides.find((v: any) => v.deck_name === "QA Reference Primer");
  expect(g).toBeTruthy();
  await page.goto("/?format=modern&tab=library");
  await page
    .getByRole("button", { name: "Guide salvate", exact: true })
    .click();
  await page
    .getByPlaceholder("Cerca per nome o archetipo")
    .fill("QA Reference");
  await page.getByRole("button", { name: "Leggi", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Guida salvata" });
  await expect(dialog.getByText("52.0%", { exact: true })).toBeVisible();
  await dialog
    .getByText("Copertura 50% · Formula e matchup", { exact: true })
    .click();
  await expect(
    dialog.getByRole("cell", { name: "Aggro test", exact: true }),
  ).toBeVisible();
  const link = dialog.getByRole("link", { name: "Scarica PDF" });
  const result = await request.get((await link.getAttribute("href"))!);
  expect(result.headers()["content-type"]).toContain("application/pdf");
  expect((await result.body()).subarray(0, 4).toString()).toBe("%PDF");
});

test("playtest accepts first play and drag without a separate keep click", async ({
  page,
}) => {
  await openPlaytest(page);
  const hand = page.locator('[data-testid="playtest-card"][data-zone="hand"]');
  await hand
    .first()
    .getByRole("button", { name: "Gioca", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "Mano (6)" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Tieni mano (7)" }),
  ).toHaveCount(0);
  const next = page
    .locator('[data-testid="playtest-card"][data-zone="hand"]')
    .first();
  await next.dragTo(page.getByRole("region", { name: "Permanenti" }));
  await expect(page.getByRole("heading", { name: "Mano (5)" })).toBeVisible();
});

test("AI Studio supports selecting five colors and custom combinations", async ({
  page,
}) => {
  await page.goto("/?format=modern&tab=ai_studio");
  for (const c of ["W", "U", "B", "R", "G"])
    await expect(
      page.getByRole("button", { name: `Colore ${c}` }),
    ).toBeVisible();
  await page.getByRole("button", { name: "Colore W" }).click();
  await expect(page.getByRole("button", { name: "Colore W" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByText("Combinazione: Esper")).toBeVisible();
});

test("main sections navigate without client errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/?format=modern&tab=deckbuilder");
  await expect(page.getByPlaceholder("Nome del mazzo...")).toBeVisible();
  await page.getByRole("button", { name: "Set & Banlist" }).click();
  await expect(
    page.getByRole("heading", { name: "Formato Modern" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Metagame" }).click();
  await expect(
    page.getByText("Metagame", { exact: false }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "AI Studio" }).click();
  await expect(
    page.getByRole("heading", { name: "AI Studio", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Playtest", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Playtest", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Mazzi e guide", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Mazzi e guide", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
