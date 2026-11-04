import React, { useState } from "react";
import { Download, ChevronDown } from "lucide-react";

export function GuideReader({
  guide,
  guideId,
  onInspect,
}: {
  guide: any;
  guideId?: number;
  onInspect?: (name: string) => void;
}) {
  const [side, setSide] = useState<"base" | "play" | "draw">("base");
  const estimate = guide.meta_estimate;
  const plans: any[] = guide.sideboard_guide || [];
  const swapFields = (plan: any) => {
    const usesBase = side === "base" || plan[`on_the_${side}_uses_base`];
    return {
      usesBase,
      inf: usesBase ? "cards_in" : `on_the_${side}_in`,
      outf: usesBase ? "cards_out" : `on_the_${side}_out`,
    };
  };
  // Card x matchup matrix for the selected play/draw view: +n in, -n out.
  const matrix = new Map<string, Map<number, number>>();
  plans.forEach((plan, i) => {
    const { inf, outf } = swapFields(plan);
    for (const [field, sign] of [
      [inf, 1],
      [outf, -1],
    ] as const) {
      for (const c of plan[field] || []) {
        const row = matrix.get(c.card_name) || new Map<number, number>();
        row.set(i, (row.get(i) || 0) + sign * c.quantity);
        matrix.set(c.card_name, row);
      }
    }
  });
  const matrixRows = [...matrix.entries()].sort(
    ([a, ra], [b, rb]) =>
      Math.min(...ra.values()) - Math.min(...rb.values()) || a.localeCompare(b),
  );
  const section = (title: string, value: string) =>
    value && (
      <section className="panel space-y-3">
        <h3>{title}</h3>
        <p className="whitespace-pre-line leading-relaxed text-slate-300">
          {value}
        </p>
      </section>
    );
  const cardName = (name: string) =>
    onInspect ? (
      <button
        className="text-sky-300 underline decoration-dotted text-left"
        onClick={() => onInspect(name)}
      >
        {name}
      </button>
    ) : (
      name
    );
  return (
    <article className="space-y-5 guide-reader">
      {guide.rules_warnings?.length > 0 && (
        <div role="alert" className="notice-error">
          <strong>
            Attenzione: possibile errore di regole in questa guida.
          </strong>
          <p>Questa versione archiviata richiede revisione prima dell’uso.</p>
          {guide.rules_warnings.map((w: string, i: number) => (
            <p key={i}>{w}</p>
          ))}
        </div>
      )}
      <div className="flex flex-wrap justify-between items-center gap-3">
        <div>
          <p className="eyebrow">
            Guida competitiva · {guide.format_id?.toUpperCase()}
          </p>
          <h2 className="text-2xl font-bold">
            {guide.deck_name || "Guida al mazzo"}
          </h2>
        </div>
        {guideId && (
          <a
            className="btn-primary"
            href={`/api/guides/${guideId}/pdf`}
            download
          >
            <Download size={16} />
            Scarica PDF
          </a>
        )}
      </div>
      {guide.quality_review?.status === "warnings" && (
        <div
          role="status"
          className="rounded-lg border border-amber-700 bg-amber-950/40 p-4 text-sm text-amber-100"
        >
          <strong>Pubblicata con punti da verificare.</strong>
          <p className="mt-1">
            La revisione non ha potuto chiudere questi rilievi: controllali prima
            di usare le parti interessate.
          </p>
          <ul className="mt-2 list-disc pl-5 space-y-1">
            {guide.quality_review.open_issues?.map((w: string, i: number) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
      {guide.quality_review?.status === "passed" && (
        <p className="text-sm text-emerald-200" role="status">
          Versione salvata dopo i controlli di lista, sidate, copertura dei
          matchup e revisione Oracle
          {guide.quality_review.revision_count > 0 &&
            ` · ${guide.quality_review.revision_count} ${guide.quality_review.revision_count === 1 ? "ciclo" : "cicli"} di correzione`}
          {guide.generated_at &&
            ` · ${new Date(guide.generated_at).toLocaleString("it-IT")}`}
          .
        </p>
      )}
      <div className="grid md:grid-cols-3 gap-4">
        <section className="panel">
          <p className="eyebrow">Posizione nel campo atteso</p>
          {guide.tier_assessment ? (
            <p className="text-sm text-slate-300 mt-3 leading-relaxed">
              {guide.tier_assessment}
            </p>
          ) : (
            <>
              <p className="text-3xl text-amber-200 font-bold my-3">
                {guide.pro_score ?? "—"}/10
              </p>
              <p className="text-sm text-slate-300">
                {guide.pro_score_rationale}
              </p>
              <p className="text-xs text-slate-400 mt-2">
                Punteggio di una versione precedente, senza evidenza misurata.
              </p>
            </>
          )}
        </section>
        <section className="panel md:col-span-2">
          <p className="eyebrow">
            Stima del modello Bo3 · ponderata sulle quote osservate
          </p>
          <p className="text-3xl text-emerald-300 font-bold my-3">
            {estimate?.weighted_winrate_pct != null
              ? `${estimate.weighted_winrate_pct.toFixed(1)}%`
              : "Non disponibile"}
          </p>
          <p className="text-xs text-slate-400">
            Opinione teorica del modello, non un risultato di partite: nessuna
            fonte pubblica dati testa a testa.
          </p>
          <p className="text-sm text-slate-300 mt-2">
            {estimate?.note ||
              "Versione storica senza dati di ponderazione registrati. Il valore non è ricostruibile da questa versione."}
          </p>
          {estimate && (
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer text-sky-300">
                Copertura {estimate.coverage_pct}% · Formula e matchup
              </summary>
              <p className="my-3">{estimate.formula}</p>
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Archetipo</th>
                      <th>Quota</th>
                      <th>WR teorico</th>
                    </tr>
                  </thead>
                  <tbody>
                    {estimate.rows?.map((r: any) => (
                      <tr key={r.archetype}>
                        <td>{r.archetype}</td>
                        <td>{r.share_pct}%</td>
                        <td>{r.winrate_pct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3">
                Meta non coperto: {estimate.uncovered_share_pct}%.{" "}
                {estimate.missing_archetypes?.join(", ")}
              </p>
              <p className="text-slate-400 mt-2">
                {estimate.source} ·{" "}
                {estimate.fetched_at &&
                  new Date(estimate.fetched_at).toLocaleString("it-IT")}
              </p>
            </details>
          )}
        </section>
      </div>
      {guide.evidence && (
        <details className="panel text-sm text-slate-400">
          <summary className="cursor-pointer">
            Fonti, modello e data dell’analisi
          </summary>
          <p className="mt-3">{guide.evidence}</p>
          <p className="mt-2">
            Modello: {guide.model_id} ·{" "}
            {guide.generated_at &&
              new Date(guide.generated_at).toLocaleString("it-IT")}
          </p>
        </details>
      )}
      <nav
        aria-label="Sezioni della guida"
        className="flex flex-wrap gap-2 text-sm"
      >
        <a className="btn-secondary" href="#guide-strategy">
          Strategia
        </a>
        <a className="btn-secondary" href="#guide-mulligan">
          Mulligan
        </a>
        <a className="btn-secondary" href="#guide-cards">
          Carte e sinergie
        </a>
        <a className="btn-secondary" href="#guide-matchups">
          Matchup e sideboard
        </a>
      </nav>
      <div id="guide-strategy" className="space-y-4 scroll-mt-32">
        {section("Tesi del mazzo", guide.executive_summary)}
        {section("Posizionamento", guide.meta_positioning)}
        {section(
          "Soglie e interazioni del formato",
          guide.format_context_and_magic_numbers,
        )}
        {section(
          "Manabase e probabilità",
          guide.manabase_and_probability_analysis,
        )}
        <div className="grid lg:grid-cols-3 gap-4">
          {section("Turni 1–3", guide.early_game_plan)}
          {section("Turni 4–6", guide.mid_game_plan)}
          {section("Finale", guide.late_game_plan)}
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          {section("Punti di forza", guide.strengths?.join("\n"))}
          {section("Vulnerabilità", guide.weaknesses?.join("\n"))}
        </div>
      </div>
      <div id="guide-mulligan" className="space-y-4 scroll-mt-32">
        {section("Mulligan e London mulligan", guide.mulligan_heuristics)}
        <div className="grid md:grid-cols-2 gap-4">
          {guide.mulligan_examples?.map((ex: any, i: number) => (
            <section className="panel" key={i}>
              <p className="eyebrow">{ex.context}</p>
              <h3 className="my-2 text-amber-200">{ex.verdict}</h3>
              <p className="text-sm text-sky-200 mb-3">
                {ex.hand_cards?.join(" · ")}
              </p>
              <p className="text-slate-300 text-sm leading-relaxed">
                {ex.analysis}
              </p>
            </section>
          ))}
        </div>
      </div>
      <div id="guide-cards" className="space-y-4 scroll-mt-32">
        <section className="panel">
          <h3>Scelte carta per carta</h3>
          {guide.card_roles?.map((c: any, i: number) => (
            <details className="py-3 border-b border-slate-800" key={i}>
              <summary className="cursor-pointer">
                {c.quantity}× {c.card_name}{" "}
                <span className="text-slate-400 text-sm">
                  · {c.role_category}
                </span>
              </summary>
              <p className="text-sm text-slate-300 mt-3 leading-relaxed">
                {c.explanation}
              </p>
              {c.alternatives_considered && (
                <p className="text-sm text-slate-400 mt-2">
                  <strong className="text-slate-300">Alternative:</strong>{" "}
                  {c.alternatives_considered}
                </p>
              )}
              <div className="mt-2">{cardName(c.card_name)}</div>
            </details>
          ))}
        </section>
        {guide.flex_slots?.length > 0 && (
          <section className="panel">
            <h3>Flex slot e quando cambiarli</h3>
            <ul className="mt-3 space-y-2 text-sm text-slate-300">
              {guide.flex_slots.map((f: any, i: number) => (
                <li key={i}>
                  <strong className="text-slate-100">
                    {cardName(f.card_name)}
                  </strong>{" "}
                  — {f.trigger}
                </li>
              ))}
            </ul>
          </section>
        )}
        {guide.synergies?.map((s: any, i: number) => (
          <section className="panel" key={i}>
            <h3>{s.cards_involved?.join(" + ")}</h3>
            <p className="text-slate-300 mt-3 leading-relaxed">
              {s.description}
            </p>
          </section>
        ))}
        {section(
          "Tips e micro-interazioni",
          guide.tips_and_tricks?.join("\n\n"),
        )}
        <section className="panel">
          <h3>Alternative escluse e trappole</h3>
          {guide.excluded_cards_and_donts?.map((c: any, i: number) => (
            <p className="mt-4 text-sm text-slate-300" key={i}>
              <strong className="text-slate-100">{c.card_name}</strong> —{" "}
              {c.why_excluded}
            </p>
          ))}
        </section>
      </div>
      <section id="guide-matchups" className="space-y-4 scroll-mt-32">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-xl font-bold">Matchup e sideboard</h3>
          <div className="flex gap-2">
            {(["base", "play", "draw"] as const).map((s) => (
              <button
                className={side === s ? "btn-primary" : "btn-secondary"}
                key={s}
                onClick={() => setSide(s)}
                aria-pressed={side === s}
              >
                {s === "base"
                  ? "Piano base"
                  : s === "play"
                    ? "On the play"
                    : "On the draw"}
              </button>
            ))}
          </div>
        </div>
        {matrixRows.length > 0 && (
          <section className="panel">
            <h3>Matrice di sideboard</h3>
            <p className="text-xs text-slate-400 mt-1">
              Copie in entrata (+) e in uscita (−) per matchup ·{" "}
              {side === "base"
                ? "piano base"
                : side === "play"
                  ? "on the play"
                  : "on the draw"}
            </p>
            <div className="overflow-x-auto mt-3">
              <table className="data-table text-xs">
                <thead>
                  <tr>
                    <th scope="col">Carta</th>
                    {plans.map((p, i) => (
                      <th scope="col" key={i} className="whitespace-nowrap">
                        {p.opponent_archetype}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matrixRows.map(([name, row]) => (
                    <tr key={name}>
                      <th scope="row" className="font-normal whitespace-nowrap">
                        {cardName(name)}
                      </th>
                      {plans.map((_, i) => {
                        const v = row.get(i) || 0;
                        return (
                          <td
                            key={i}
                            className={`text-center ${v > 0 ? "text-emerald-300" : v < 0 ? "text-rose-300" : "text-slate-400"}`}
                          >
                            {v > 0 ? `+${v}` : v < 0 ? `−${-v}` : "·"}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        {plans.map((plan: any, i: number) => {
          const { usesBase, inf, outf } = swapFields(plan);
          const hasPlan = plan[inf]?.length || plan[outf]?.length;
          return (
            <details className="panel" key={i} open={i === 0}>
              <summary className="cursor-pointer flex justify-between gap-3">
                <strong>{plan.opponent_archetype}</strong>
                <span className="text-amber-200 text-sm">
                  {plan.matchup_difficulty} · {plan.expected_winrate_pct}% stimato
                  {plan.confidence && ` · confidenza ${plan.confidence}`}{" "}
                  <ChevronDown className="inline w-4" />
                </span>
              </summary>
              <div className="space-y-4 mt-5 text-sm leading-relaxed">
                <p className="text-slate-400">{plan.estimate_rationale}</p>
                {(plan.role_pre_side || plan.role_post_side) && (
                  <div className="grid md:grid-cols-2 gap-4">
                    <p>
                      <strong>Ruolo pre-side:</strong> {plan.role_pre_side}
                    </p>
                    <p>
                      <strong>Ruolo post-side:</strong> {plan.role_post_side}
                    </p>
                  </div>
                )}
                {plan.opponent_key_cards?.length > 0 && (
                  <div>
                    <strong>Carte avversarie da rispettare</strong>
                    <ul className="mt-2 space-y-2">
                      {plan.opponent_key_cards.map((k: any, j: number) => (
                        <li key={j} className="rounded-lg bg-black/20 p-3">
                          <span className="text-slate-100">
                            {cardName(k.card_name)}
                          </span>
                          <span className="block text-slate-400">
                            {k.why_it_matters}
                          </span>
                          <span className="block text-sky-200">
                            → {k.our_answer}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {plan.expected_opponent_sideboard?.length > 0 && (
                  <p>
                    <strong>Loro sideboard prevista:</strong>{" "}
                    {plan.expected_opponent_sideboard.join(", ")}
                  </p>
                )}
                <p>
                  <strong>Game 1:</strong> {plan.gameplan_pre_side}
                </p>
                <p>
                  <strong>Game 2/3:</strong> {plan.gameplan_post_side}
                </p>
                <div className="grid md:grid-cols-2 gap-4">
                  <p>
                    <strong>On the play:</strong> {plan.on_the_play_notes}
                  </p>
                  <p>
                    <strong>On the draw:</strong> {plan.on_the_draw_notes}
                  </p>
                </div>
                <p>
                  <strong>Mulligan target:</strong> {plan.mulligan_target}
                </p>
                {side !== "base" && usesBase && (
                  <p className="text-sky-200">
                    Stessa sidata del piano base; applica le note tattiche per{" "}
                    {side === "play" ? "on the play" : "on the draw"}.
                  </p>
                )}
                {side !== "base" && !usesBase && !hasPlan ? (
                  <p className="text-amber-200">
                    Questa versione non contiene una sidata distinta per {side}.
                    Consulta le note tattiche e il piano base.
                  </p>
                ) : (
                  <div className="grid md:grid-cols-2 gap-4">
                    {[
                      [inf, "IN · dalla sideboard", "text-emerald-300"],
                      [outf, "OUT · dal mainboard", "text-rose-300"],
                    ].map(([field, label, color]) => (
                      <div key={field} className="rounded-lg bg-black/20 p-4">
                        <h4 className={`${color} font-bold mb-3`}>
                          {label} (
                          {plan[field]?.reduce(
                            (a: number, c: any) => a + c.quantity,
                            0,
                          ) || 0}
                          )
                        </h4>
                        {plan[field]?.map((c: any, j: number) => (
                          <div className="mt-3" key={j}>
                            <p>
                              {c.quantity}× {cardName(c.card_name)}
                            </p>
                            <p className="text-slate-400 mt-1">{c.reason}</p>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
                {plan.pro_tips?.map((tip: string, j: number) => (
                  <p key={j} className="text-sky-200">
                    • {tip}
                  </p>
                ))}
              </div>
            </details>
          );
        })}
      </section>
    </article>
  );
}
