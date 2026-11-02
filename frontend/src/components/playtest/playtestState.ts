import type { Card, DeckDetail } from "../../types";
import { faceCard } from "./cardState";
export type Zone =
  | "library"
  | "hand"
  | "permanents"
  | "lands"
  | "graveyard"
  | "exile"
  | "sideboard";
export interface Instance {
  uid: string;
  card: Card;
  zone: Zone;
  tapped: boolean;
  counters: number;
  face: number;
  isToken: boolean;
}
export interface Game {
  cards: Instance[];
  turn: number;
  life: number;
  opponent: number;
  mulligans: number;
  opening: boolean;
  log: string[];
}
export const battlefield = (zone: Zone) =>
  zone === "lands" || zone === "permanents";
export function shuffled<T>(items: T[]): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}
export function newGame(
  deck: DeckDetail,
  mulligans = 0,
  configuration?: Instance[],
): Game {
  const pool: Instance[] = configuration
    ? configuration
        .filter((c) => !c.isToken)
        .map((c) => ({
          ...c,
          zone: c.zone === "sideboard" ? "sideboard" : "library",
          tapped: false,
          counters: 0,
          face: 0,
        }))
    : deck.cards.flatMap((e) =>
        Array.from(
          { length: e.quantity },
          (_, i) =>
            ({
              uid: `${e.board}-${e.oracle_id}-${i}`,
              card: e.card,
              zone: e.board === "main" ? "library" : "sideboard",
              tapped: false,
              counters: 0,
              face: 0,
              isToken: false,
            }) as Instance,
        ),
      );
  const main = shuffled(pool.filter((c) => c.zone !== "sideboard")).map(
    (c, i) => ({ ...c, zone: i < 7 ? "hand" : "library" }) as Instance,
  );
  return {
    cards: [...main, ...pool.filter((c) => c.zone === "sideboard")],
    turn: 1,
    life: 20,
    opponent: 20,
    mulligans,
    opening: true,
    log: [`Nuova mano da 7 · London mulligan ${mulligans}.`],
  };
}
export function moved(
  cards: Instance[],
  uid: string,
  zone: Zone,
  position: "top" | "bottom" = "bottom",
  preserveFace = false,
): Instance[] {
  const card = cards.find((c) => c.uid === uid);
  if (!card) return cards;
  const rest = cards.filter((c) => c.uid !== uid);
  if (card.isToken && !battlefield(zone)) return rest;
  const stays = battlefield(card.zone) && battlefield(zone);
  const next = {
    ...card,
    zone,
    tapped: stays ? card.tapped : false,
    counters: stays ? card.counters : 0,
    face: stays || (preserveFace && battlefield(zone)) ? card.face : 0,
  };
  return zone === "library" && position === "top"
    ? [next, ...rest]
    : [...rest, next];
}
export function played(cards: Instance[], uid: string): Instance[] {
  const card = cards.find((c) => c.uid === uid);
  if (!card) return cards;
  const type = faceCard(card.card, card.face).type_line.split("//")[0];
  return moved(
    cards,
    uid,
    type.includes("Land")
      ? "lands"
      : type.includes("Instant") || type.includes("Sorcery")
        ? "graveyard"
        : "permanents",
    "bottom",
    true,
  );
}
export function keep(game: Game, bottom: string[]): Game {
  if (
    bottom.length !== game.mulligans ||
    new Set(bottom).size !== bottom.length ||
    bottom.some(
      (uid) => !game.cards.some((c) => c.uid === uid && c.zone === "hand"),
    )
  )
    return game;
  let cards = game.cards;
  for (const uid of bottom) cards = moved(cards, uid, "library");
  return {
    ...game,
    cards,
    opening: false,
    log: [`Mano tenuta a ${7 - game.mulligans}.`, ...game.log],
  };
}
