import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import type { AIJob } from "../../types";

const PHASES: Record<AIJob["kind"], [string, string][]> = {
  deck_generation: [
    ["context", "Preparazione del meta"],
    ["generation", "Costruzione della lista"],
    ["repair", "Correzione delle regole del formato"],
    ["analysis", "Analisi della lista"],
    ["critic", "Revisione strategica"],
    ["revision", "Revisione della lista"],
    ["save", "Salvataggio nell'archivio"],
  ],
  matchup_spot: [
    ["context", "Preparazione delle liste"],
    ["analysis", "Analisi del matchup"],
    ["repair", "Correzione dei piani di sideboard"],
    ["save", "Verifica e salvataggio"],
  ],
  deck_improvement: [
    ["context", "Analisi metagame e struttura"],
    ["analysis", "Ricerca punti deboli e carte papabili"],
    ["repair", "Verifica legalità e copie dei cambi"],
    ["after_metrics", "Ricalcolo metriche prima/dopo"],
    ["save", "Salvataggio report"],
  ],
};

export function AIJobStatus({
  job,
  onCancel,
}: {
  job: AIJob;
  onCancel: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job.id]);
  const steps = PHASES[job.kind];
  const current = steps.findIndex(([id]) => id === job.phase);
  const seconds = Math.max(
    0,
    Math.floor((now - new Date(job.created_at).getTime()) / 1000),
  );
  return (
    <section className="panel space-y-3" aria-label="Stato dell'analisi">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-semibold flex items-center gap-2" role="status">
          <Loader2 size={18} className="animate-spin" />
          {current >= 0 ? steps[current][1] : "Avvio dell'analisi"}
        </p>
        <span className="font-mono text-sm text-slate-400">
          {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
        </span>
      </div>
      <ol className="flex flex-wrap gap-2 text-xs" aria-label="Fasi">
        {steps.map(([id, label], i) => (
          <li
            key={id}
            aria-current={i === current ? "step" : undefined}
            className={`rounded-full border px-2 py-1 ${
              i === current
                ? "border-sky-400 text-sky-100"
                : i < current
                  ? "border-emerald-700 text-emerald-200"
                  : "border-slate-700 text-slate-400"
            }`}
          >
            {label}
          </li>
        ))}
      </ol>
      <p className="text-sm text-slate-300">
        {job.label} · {job.model_id}. Di solito richiede qualche minuto: puoi
        usare le altre sezioni o ricaricare la pagina, il lavoro continua sul
        server e il risultato compare qui.
      </p>
      <button className="btn-secondary" type="button" onClick={onCancel}>
        Annulla analisi
      </button>
    </section>
  );
}
