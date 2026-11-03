import type { CardArchetypeUsage } from "../../types";

const pct = (v: number) => `${Math.round(v)}%`;

/** Short Italian label for how an archetype uses a card, using only observed values. */
export function archetypeUsageLabel(usage: CardArchetypeUsage): string {
  const parts: string[] = [];
  if (usage.main_inclusion_pct) {
    parts.push(
      `main ${pct(usage.main_inclusion_pct)} delle liste · ${usage.main_avg_copies ?? 0}x`,
    );
  }
  if (usage.side_inclusion_pct) {
    parts.push(
      `side ${pct(usage.side_inclusion_pct)} · ${usage.side_avg_copies ?? 0}x`,
    );
  }
  if (!parts.length && usage.sample_copies != null) {
    parts.push(`${usage.sample_copies}x nella lista di riferimento`);
  }
  return parts.join(" · ");
}
