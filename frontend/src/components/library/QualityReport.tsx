import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { FormatId } from "../../types";

const SKILLS: Record<string, string> = {
  deck_generation: "Generazione mazzo",
  deck_guide: "Guida",
  matchup_spot: "Analisi matchup",
};
const rating = (r: any) =>
  r ? `${r.depth} / ${r.correctness} / ${r.usefulness} (${r.count})` : "—";

function Table({
  caption,
  headers,
  rows,
}: {
  caption: string;
  headers: string[];
  rows: (string | number | null | undefined)[][];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="data-table text-xs">
        <caption className="text-left text-sm font-semibold text-slate-200 pb-2">{caption}</caption>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} scope="col" className="whitespace-nowrap font-normal text-slate-400">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((v, j) => (
                <td key={j} className={j === 0 ? "text-slate-100" : "whitespace-nowrap"}>
                  {v ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Automatic metrics (M2-M3), run log (M5) and human ratings (M4) for one format. */
export function QualityReport({ formatId }: { formatId: FormatId }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setData(null);
    setError("");
    api.getQualityReport(formatId).then(setData).catch((e) => setError(e.message));
  }, [formatId]);
  if (error)
    return (
      <p className="notice-error" role="alert">
        {error}
      </p>
    );
  if (!data)
    return (
      <p className="panel" role="status">
        Calcolo delle metriche…
      </p>
    );
  const deckRow = (d: any, name: string, extra: (string | number | null)[]) => [
    name,
    `${d.consensus_overlap_pct}%${d.nearest_archetype ? ` · ${d.nearest_archetype}` : ""}`,
    d.land_count,
    d.total_deficit ? d.color_deficits.join(", ") : "ok",
    d.always_tapped,
    d.interaction_main,
    ...extra,
  ];
  return (
    <div className="space-y-5">
      <section className="panel text-sm text-slate-300 space-y-2">
        <h2 className="text-lg font-bold text-slate-100">Qualità di mazzi e guide</h2>
        <p>
          Metriche calcolate dall'app, senza AI, per capire se un cambio di prompt o di modello
          migliora i risultati. Le liste di consenso dei primi archetipi sono il riferimento: un
          mazzo generato dovrebbe avvicinarsi ai loro valori di fonti e interazione, o motivare
          perché se ne allontana.
        </p>
        <p className="text-slate-400">
          Snapshot meta {data.snapshot.id ?? "assente"} · {data.snapshot.period ?? "periodo n/d"}.
          Valutazioni umane come profondità / correttezza / utilità (numero di voti).
        </p>
      </section>

      <section className="panel space-y-4">
        <Table
          caption="Esecuzioni AI per versione del prompt e modello"
          headers={["Skill", "Prompt", "Modello", "Esecuzioni", "Fallite", "Con avvisi", "Durata media", "Tentativi medi"]}
          rows={data.runs.map((r: any) => [
            SKILLS[r.skill] || r.skill,
            r.prompt_version,
            r.model_id,
            r.runs,
            r.failed,
            r.with_warnings,
            `${r.avg_duration_s} s`,
            r.avg_attempts,
          ])}
        />
        {data.jobs.length > 0 && (
          <p className="text-xs text-slate-400">
            Lavori in background:{" "}
            {data.jobs
              .map(
                (j: any) =>
                  `${SKILLS[j.kind] || j.kind}: ${j.completed || 0} completati, ${j.failed || 0} falliti, ${j.cancelled || 0} annullati`,
              )
              .join(" · ")}
          </p>
        )}
      </section>

      <section className="panel space-y-5">
        <Table
          caption="Riferimento: liste di consenso dei primi archetipi"
          headers={["Archetipo", "Sovrapposizione", "Terre", "Deficit fonti", "Tappate", "Interazione main", "Quota", "Liste"]}
          rows={data.reference.map((d: any) =>
            deckRow(d, d.name, [`${d.meta_share_pct}%`, d.lists_count]),
          )}
        />
        <Table
          caption="Mazzi generati"
          headers={[
            "Mazzo",
            "Consenso più vicino",
            "Terre",
            "Deficit fonti",
            "Tappate",
            "Interazione main",
            "Partenza",
            "Delta non motivati",
            "Avvisi",
            "Critico",
            "Prompt · modello",
            "Valutazione",
          ]}
          rows={data.generated_decks.map((d: any) =>
            deckRow(d, d.name, [
              d.mode === "meta" ? "consenso" : d.mode === "brew" ? "brew" : "n/d",
              d.unmotivated_deltas,
              d.open_warnings,
              d.critic_verdict ? `${d.critic_verdict}${d.revision_applied ? " · rivista" : ""}` : "—",
              d.prompt_version ? `${d.prompt_version} · ${d.model_id}` : "—",
              rating(d.rating),
            ]),
          )}
        />
      </section>

      <section className="panel">
        <Table
          caption="Guide"
          headers={[
            "Mazzo",
            "Data",
            "Matchup coperti",
            "Parole per matchup principale",
            "Carte avversarie per matchup",
            "Play/draw distinti",
            "Errori validatori",
            "Avvisi aperti",
            "Esito revisione",
            "Modello",
            "Valutazione",
          ]}
          rows={data.guides.map((g: any) => [
            `${g.deck_name}${g.legacy_schema ? " (schema precedente)" : ""}`,
            g.created_at ? new Date(g.created_at).toLocaleDateString("it-IT") : "—",
            `${g.matchups_covered}/${g.matchups_required}`,
            g.avg_words_main_matchups,
            g.avg_opponent_cards,
            g.play_draw_differentiated,
            g.validator_errors,
            g.open_issues,
            g.review_status === "passed" ? "superata" : g.review_status === "warnings" ? "con avvisi" : g.review_status,
            g.model_id,
            rating(g.rating),
          ])}
        />
      </section>
    </div>
  );
}
