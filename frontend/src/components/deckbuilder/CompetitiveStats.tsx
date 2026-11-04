import type { ListAnalysis } from "../../types";

const pct = (p: number) => `${Math.round(p * 100)}%`;

/** Sources vs Karsten requirements, tapped lands and odds computed by the backend. */
export function ManaRequirements({ analysis }: { analysis: ListAnalysis | null }) {
  if (!analysis || analysis.colors.length === 0) {
    return (
      <p className="text-xs text-slate-400 py-4 text-center">
        Aggiungi carte al main per confrontare le fonti di mana con i requisiti
        di lancio.
      </p>
    );
  }
  const tapped = analysis.tapped_lands;
  return (
    <div className="space-y-2">
      <table className="w-full text-xs">
        <caption className="sr-only">Fonti per colore rispetto ai requisiti</caption>
        <thead>
          <tr className="text-slate-400">
            <th scope="col" className="text-left font-normal pb-1">Colore</th>
            <th scope="col" className="text-right font-normal pb-1">Fonti</th>
            <th scope="col" className="text-right font-normal pb-1">Richieste</th>
          </tr>
        </thead>
        <tbody>
          {analysis.colors.map((c) => (
            <tr key={c.color} title={c.driver ? `Carta più esigente: ${c.driver} (turno ${c.driver_turn})` : undefined}>
              <td className="py-0.5">
                <i className={`ms ms-${c.color.toLowerCase()} ms-cost text-xs`} aria-hidden="true" />{" "}
                <span className="text-slate-200">{c.color}</span>
                {c.driver && (
                  <span className="block text-slate-400 truncate max-w-[12rem]">{c.driver}</span>
                )}
              </td>
              <td
                className={`text-right font-mono-tech ${c.deficit ? "text-rose-300 font-bold" : "text-emerald-300"}`}
              >
                {c.sources}
                {c.deficit > 0 && <span className="sr-only"> (mancano {c.deficit})</span>}
              </td>
              <td className="text-right font-mono-tech text-slate-300">{c.required || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-slate-400">
        Terre sempre tappate: <strong className="text-slate-200">{tapped.tapped}</strong>
        {" · "}condizionali: <strong className="text-slate-200">{tapped.conditional}</strong>
      </p>
      <p className="text-xs text-slate-400">
        2–5 terre nelle 7 iniziali: <strong className="text-slate-200">{pct(analysis.odds.p_2_to_5_lands_in_7)}</strong>
        {analysis.odds.p_2_to_5_lands_within_one_mulligan != null && (
          <>
            {" "}(<strong className="text-slate-200">{pct(analysis.odds.p_2_to_5_lands_within_one_mulligan)}</strong> entro un mulligan)
          </>
        )}
        {" · "}3 terre al turno 3:{" "}
        <strong className="text-slate-200">{pct(analysis.odds.p_3_lands_by_t3_play)}</strong> play /{" "}
        <strong className="text-slate-200">{pct(analysis.odds.p_3_lands_by_t3_draw)}</strong> draw
      </p>
    </div>
  );
}

export function InteractionSummary({ analysis }: { analysis: ListAnalysis | null }) {
  if (!analysis) return null;
  const groups = Object.entries(analysis.interaction_main);
  const side = Object.entries(analysis.interaction_side);
  if (groups.length === 0 && side.length === 0) return null;
  return (
    <div className="bg-[#090C12] border border-[#192030] rounded-lg p-3 space-y-2">
      <p className="text-xs text-slate-400">
        Interazione (tag funzionali Scryfall) · main e sideboard
      </p>
      <ul className="flex flex-wrap gap-2 text-xs">
        {groups.map(([group, v]) => (
          <li key={group} title={v.cards.join(", ")} className="rounded-full border border-slate-700 px-2 py-1 text-slate-200">
            {group} <strong className="text-[#F3E5C8]">{v.copies}</strong>
          </li>
        ))}
        {side.map(([group, v]) => (
          <li key={`side-${group}`} title={v.cards.join(", ")} className="rounded-full border border-dashed border-slate-700 px-2 py-1 text-slate-300">
            side · {group} <strong>{v.copies}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** How the main deck is built and which field archetypes are built the same way. */
export function StructureSummary({ analysis }: { analysis: ListAnalysis | null }) {
  const s = analysis?.structure;
  if (!s || s.nearest.length === 0) return null;
  const v = s.values;
  return (
    <div className="bg-[#090C12] border border-[#192030] rounded-lg p-3 space-y-1 text-xs">
      <p className="text-slate-400">
        Struttura del main · creature {v.creatures} · interazione {v.interaction} · vantaggio
        carte {v.card_advantage} · sweeper {v.sweepers} · counter {v.counters}
      </p>
      <p className="text-slate-200">
        Costruita come:{" "}
        {s.nearest.map((n) => `${n.archetype} (${n.category})`).join(", ")}
      </p>
      {s.issues?.map((issue) => (
        <p key={issue} className="text-amber-200" role="status">
          {issue}
        </p>
      ))}
    </div>
  );
}
