import React from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import type { DeckGenerationResult, ListAnalysis, ListStructure } from "../../types";
import { ColorBadges } from "../common/ManaCost";

const pct = (p: number) => `${Math.round(p * 100)}%`;
const signed = (n: number) => (n > 0 ? `+${n}` : `${n}`);
const BOARD = { main: "Main", side: "Side" } as const;
const SEVERITY = {
  alta: "border-rose-700 bg-rose-950/50 text-rose-200",
  media: "border-amber-700 bg-amber-950/40 text-amber-200",
  bassa: "border-slate-600 bg-slate-800/60 text-slate-300",
} as const;

function TextBlock({ title, text }: { title: string; text?: string }) {
  if (!text) return null;
  return (
    <section className="panel">
      <h3>{title}</h3>
      <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line mt-3">
        {text}
      </p>
    </section>
  );
}

function Curve({ curve }: { curve: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(curve));
  return (
    <div className="flex items-end gap-2 h-24" aria-label="Curva di mana delle non-terre">
      {Object.entries(curve).map(([mv, n]) => (
        <div key={mv} className="flex-1 flex flex-col items-center justify-end h-full">
          <span className="text-xs text-slate-300">{n || ""}</span>
          <div
            className="w-full rounded-t bg-sky-500/70"
            style={{ height: `${(n / max) * 70}%` }}
          />
          <span className="text-xs text-slate-400 mt-1">{mv}</span>
        </div>
      ))}
    </div>
  );
}

function Interaction({
  title,
  data,
}: {
  title: string;
  data: ListAnalysis["interaction_main"];
}) {
  const rows = Object.entries(data);
  return (
    <div>
      <p className="eyebrow">{title}</p>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-400 mt-2">Nessuna carta etichettata.</p>
      ) : (
        <ul className="mt-2 space-y-1 text-sm">
          {rows.map(([group, v]) => (
            <li key={group}>
              <span className="text-slate-100 font-medium">
                {group} · {v.copies}
              </span>{" "}
              <span className="text-slate-400">{v.cards.join(", ")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const STRUCTURE_LABELS: Array<[keyof ListStructure["values"], string]> = [
  ["creatures", "Creature"],
  ["interaction", "Interazione"],
  ["card_advantage", "Vantaggio carte"],
  ["sweepers", "Sweeper"],
  ["counters", "Counter"],
];

/** How the list is built, and which field archetypes are built the same way. */
function Structure({ s }: { s: ListStructure }) {
  return (
    <div>
      <p className="eyebrow">Struttura del main</p>
      <p className="mt-2 text-sm text-slate-300">
        {STRUCTURE_LABELS.map(([k, label]) => `${label} ${s.values[k]}`).join(" · ")}
      </p>
      {s.nearest.length > 0 && (
        <p className="mt-1 text-sm text-slate-400">
          Costruita come:{" "}
          {s.nearest.map((n) => `${n.archetype} (${n.category})`).join(", ")}
          {s.requested && ` · archetipo richiesto: ${s.requested}`}
        </p>
      )}
    </div>
  );
}

function AnalysisPanel({ a }: { a: ListAnalysis }) {
  return (
    <section className="panel space-y-5">
      <div>
        <h3>Analisi della lista</h3>
        <p className="text-xs text-slate-400 mt-1">
          Calcolata sulla lista finale.
        </p>
      </div>
      <div className="grid sm:grid-cols-3 gap-4 text-sm">
        <div>
          <p className="eyebrow">Terre</p>
          <p className="text-2xl font-bold mt-1">
            {a.land_count}
            {a.mdfc_land_count > 0 && (
              <span className="text-sm text-slate-400"> + {a.mdfc_land_count} MDFC</span>
            )}
          </p>
        </div>
        <div>
          <p className="eyebrow">MV medio</p>
          <p className="text-2xl font-bold mt-1">{a.avg_mana_value_nonland}</p>
        </div>
        <div>
          <p className="eyebrow">Terre sempre tappate</p>
          <p className="text-2xl font-bold mt-1">{a.tapped_lands.tapped}</p>
          <p className="text-xs text-slate-400">
            {a.tapped_lands.conditional} condizionali, {a.tapped_lands.untapped} stappate
          </p>
        </div>
      </div>
      <Curve curve={a.curve} />
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Colore</th>
              <th scope="col">Fonti</th>
              <th scope="col">Richieste</th>
              <th scope="col">Carta più esigente</th>
            </tr>
          </thead>
          <tbody>
            {a.colors.map((c) => (
              <tr key={c.color}>
                <td>
                  <ColorBadges colors={[c.color]} size="md" />
                </td>
                <td className={c.deficit ? "text-rose-300 font-semibold" : ""}>
                  {c.sources}
                  {c.deficit > 0 && ` (−${c.deficit})`}
                </td>
                <td>{c.required || "—"}</td>
                <td className="text-slate-400">
                  {c.driver ? `${c.driver}, turno ${c.driver_turn}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <Interaction title="Interazione nel main" data={a.interaction_main} />
        <Interaction title="Interazione in sideboard" data={a.interaction_side} />
      </div>
      {a.structure && <Structure s={a.structure} />}
      <div>
        <p className="eyebrow">Probabilità</p>
        <ul className="mt-2 text-sm text-slate-300 space-y-1">
          <li>
            Da 2 a 5 terre nelle 7 iniziali: {pct(a.odds.p_2_to_5_lands_in_7)}
            {a.odds.p_2_to_5_lands_within_one_mulligan != null &&
              `, ${pct(a.odds.p_2_to_5_lands_within_one_mulligan)} entro un mulligan (London)`}
          </li>
          <li>
            3 terre entro il turno 3: {pct(a.odds.p_3_lands_by_t3_play)} on the play,{" "}
            {pct(a.odds.p_3_lands_by_t3_draw)} on the draw
          </li>
          <li>
            Almeno una copia nelle 7 iniziali:{" "}
            {Object.entries(a.odds.copies)
              .map(([n, o]) => `${n} copi${n === "1" ? "a" : "e"} ${pct(o.opening_7)}`)
              .join(" · ")}
          </li>
          {a.key_card_odds.map((k) => (
            <li key={k.card}>
              {k.card} ({k.copies}): {pct(k.opening_7)} nelle 7 iniziali,{" "}
              {pct(k.by_t3_draw)} entro il turno 3 on the draw
            </li>
          ))}
        </ul>
      </div>
      <ul className="text-xs text-slate-400 space-y-1">
        {a.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </section>
  );
}

export function GenerationReport({
  generation,
  onInspect,
}: {
  generation: DeckGenerationResult;
  onInspect: (name: string) => void;
}) {
  const { ai_result: out, starting_point: start, critic, revision, warnings } =
    generation;
  return (
    <div className="space-y-4">
      <section className="panel text-sm">
        <p className="eyebrow">Punto di partenza</p>
        {start.mode === "meta" ? (
          <p className="mt-2 text-slate-200">
            Lista di consenso di <strong>{start.archetype}</strong>: {start.lists_count}{" "}
            liste, {start.meta_share_pct}% del meta. Le differenze sono motivate più
            sotto.
          </p>
        ) : (
          <p className="mt-2 text-slate-200">
            Brew dalla tua tesi.{" "}
            {start.references.length > 0
              ? `Liste di riferimento: ${start.references
                  .map(
                    (r) =>
                      `${r.archetype} (${r.meta_share_pct}%${r.role ? `, ${r.role}` : ""})`,
                  )
                  .join("; ")}.`
              : "Nessuna lista di riferimento compatibile."}
          </p>
        )}
      </section>

      {warnings.length > 0 && (
        <section
          className="rounded-lg border border-amber-700 bg-amber-950/40 p-4 text-sm text-amber-100"
          role="status"
        >
          <p className="font-semibold flex items-center gap-2">
            <AlertTriangle size={16} /> Da verificare
          </p>
          <ul className="mt-2 list-disc pl-5 space-y-1">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </section>
      )}

      {critic && (
        <section className="panel space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2">
              {critic.verdict === "solida" ? (
                <CheckCircle2 size={18} className="text-emerald-300" />
              ) : (
                <ShieldAlert size={18} className="text-amber-300" />
              )}
              Revisione strategica
            </h3>
            <span className="text-xs text-slate-400">
              {revision.applied
                ? "Lista rivista dopo la revisione"
                : revision.attempted
                  ? revision.note || "Revisione non applicata"
                  : "Nessuna revisione necessaria"}
            </span>
          </div>
          <p className="text-sm text-slate-300 leading-relaxed">{critic.summary}</p>
          {critic.issues.length > 0 && (
            <ul className="space-y-2">
              {critic.issues.map((i, n) => (
                <li key={n} className={`rounded-lg border p-3 text-sm ${SEVERITY[i.severity]}`}>
                  <p className="font-semibold">
                    {i.severity} · {i.area}
                  </p>
                  <p className="mt-1">{i.finding}</p>
                  <p className="mt-1 opacity-80">→ {i.recommendation}</p>
                </li>
              ))}
            </ul>
          )}
          {critic.oracle_errors.length > 0 && (
            <div>
              <p className="eyebrow">Errori di regole segnalati</p>
              <ul className="mt-2 list-disc pl-5 text-sm text-rose-200 space-y-1">
                {critic.oracle_errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          {critic.swaps.length > 0 && (
            <div>
              <p className="eyebrow">
                Cambi proposti{revision.applied ? " (valutati nella revisione)" : ""}
              </p>
              <ul className="mt-2 text-sm space-y-2">
                {critic.swaps.map((s, n) => (
                  <li key={n}>
                    <span className="text-rose-300">−{s.quantity} {s.card_out}</span>{" "}
                    <span className="text-emerald-300">+{s.quantity} {s.card_in}</span>{" "}
                    <span className="text-slate-400">({BOARD[s.board]})</span>
                    <span className="block text-slate-400">{s.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <TextBlock title="Tesi competitiva" text={out.strategy_overview} />
      <TextBlock title="Concessioni" text={out.concessions} />
      <AnalysisPanel a={generation.analysis} />

      {start.mode === "meta" && (
        <section className="panel">
          <h3>Differenze dalla lista di consenso</h3>
          {out.deltas.length === 0 ? (
            <p className="text-sm text-slate-400 mt-3">
              Nessuna: la lista coincide con il consenso.
            </p>
          ) : (
            <div className="overflow-x-auto mt-3">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Carta</th>
                    <th scope="col">Cambio</th>
                    <th scope="col">Motivo</th>
                  </tr>
                </thead>
                <tbody>
                  {out.deltas.map((d, n) => (
                    <tr key={n}>
                      <td>
                        <button
                          className="text-left text-sky-200 hover:underline"
                          onClick={() => onInspect(d.card_name)}
                        >
                          {d.card_name}
                        </button>
                      </td>
                      <td
                        className={`whitespace-nowrap ${d.change > 0 ? "text-emerald-300" : "text-rose-300"}`}
                      >
                        {signed(d.change)} {BOARD[d.board]}
                      </td>
                      <td className="text-slate-300">
                        {d.reason}
                        {d.matchups.length > 0 && (
                          <span className="block text-xs text-slate-400 mt-1">
                            {d.matchups.join(", ")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {out.matchup_plans.length > 0 && (
        <section className="panel">
          <h3>Piani contro il meta</h3>
          <div className="mt-3 divide-y divide-slate-800">
            {out.matchup_plans.map((p) => (
              <details key={p.opponent_archetype} className="py-3">
                <summary className="cursor-pointer font-medium">
                  {p.opponent_archetype}
                  <span className="text-slate-400 text-sm">
                    {" "}
                    · {p.sideboard_in.reduce((s, c) => s + c.quantity, 0)} cambi
                  </span>
                </summary>
                <p className="text-sm text-slate-300 mt-2 leading-relaxed">{p.plan}</p>
                <div className="grid sm:grid-cols-2 gap-3 mt-3 text-sm">
                  {(
                    [
                      ["IN", p.sideboard_in, "text-emerald-300"],
                      ["OUT", p.sideboard_out, "text-rose-300"],
                    ] as const
                  ).map(([label, rows, color]) => (
                    <div key={label}>
                      <p className={`font-semibold ${color}`}>{label}</p>
                      {rows.length === 0 ? (
                        <p className="text-slate-400">Nessun cambio</p>
                      ) : (
                        <ul>
                          {rows.map((c) => (
                            <li key={c.card_name}>
                              {c.quantity} {c.card_name}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            ))}
          </div>
        </section>
      )}

      {out.flex_rules.length > 0 && (
        <section className="panel">
          <h3>Quando cambiare i flex slot</h3>
          <ul className="mt-3 list-disc pl-5 text-sm text-slate-300 space-y-1">
            {out.flex_rules.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      <TextBlock title="Manabase" text={out.mana_curve_notes} />
      <TextBlock title="Progetto della sideboard" text={out.sideboard_mapping_notes} />
      <TextBlock title="Sinergie" text={out.key_synergies?.join("\n\n")} />
      <TextBlock title="Alternative escluse" text={out.excluded_cards_or_traps?.join("\n\n")} />

      <div className="grid lg:grid-cols-2 gap-4">
        {(["mainboard", "sideboard"] as const).map((board) => (
          <section className="panel" key={board}>
            <h3 className="capitalize">
              {board} ({out[board].reduce((n, c) => n + c.quantity, 0)})
            </h3>
            {out[board].map((slot, i) => (
              <details className="py-3 border-b border-slate-800 text-sm" key={i}>
                <summary className="cursor-pointer">
                  {slot.quantity}× {slot.card_name}{" "}
                  <span className="text-slate-400">· {slot.role}</span>
                </summary>
                <p className="text-slate-300 mt-2">{slot.reason}</p>
                <button
                  className="text-sky-200 mt-3"
                  onClick={() => onInspect(slot.card_name)}
                >
                  Esamina carta
                </button>
              </details>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
