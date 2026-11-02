import type { Card } from "../../types";
export function canFlip(card: Card): boolean {
  return (
    [
      "transform",
      "modal_dfc",
      "double_faced_token",
      "reversible_card",
    ].includes(card.layout) && (card.card_faces?.length || 0) > 1
  );
}
export function faceCard(card: Card, face = 0): Card {
  const f = canFlip(card) ? card.card_faces?.[face] : null;
  return f
    ? {
        ...card,
        ...f,
        oracle_id: card.oracle_id,
        card_faces: card.card_faces,
        image_uris: f.image_uris || card.image_uris,
        name: f.name || card.name,
      }
    : card;
}
