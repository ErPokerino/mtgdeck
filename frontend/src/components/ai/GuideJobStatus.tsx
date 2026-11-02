import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

const phases: Record<string, string> = {
  queued: "Avvio dell’analisi",
  draft: "Scrittura del primer",
  list_and_matchup_checks: "Controllo di lista e matchup",
  oracle_review: "Revisione Oracle e correzioni",
  corrections_applied: "Correzioni applicate",
  verify_corrections: "Verifica dei passaggi corretti",
  repair_review: "Verifica delle fonti delle correzioni",
  weighted_estimate: "Calcolo del winrate ponderato",
  ready_to_save: "Preparazione del salvataggio",
  save: "Salvataggio nell’archivio",
};
export function GuideJobStatus({
  job,
  onCancel,
  onResume,
}: {
  job: any;
  onCancel: () => void;
  onResume: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job.id]);
  const active = ["queued", "running", "publishing"].includes(job.status);
  const seconds = Math.max(
    0,
    Math.floor((now - new Date(job.created_at).getTime()) / 1000),
  );
  return (
    <section className="panel space-y-3" aria-label="Stato generazione guida">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-semibold flex items-center gap-2" role="status">
          {active && <Loader2 size={18} className="animate-spin" />}
          {active
            ? phases[job.phase] || "Analisi in corso"
            : job.status === "completed"
              ? "Guida salvata nell’archivio"
              : job.status === "cancelled"
                ? "Analisi annullata"
                : job.has_draft
                  ? "Analisi interrotta · lavoro conservato"
                  : "Analisi interrotta"}
        </p>
        {active && (
          <span className="font-mono text-sm text-slate-400">
            {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")} ·
            limite {Math.round(job.budget_seconds / 60)} min
          </span>
        )}
      </div>
      <p className="text-sm text-slate-400">
        {job.deck_name} · {job.model_id}
      </p>
      {active ? (
        <>
          <p className="text-sm text-slate-300">
            Puoi usare le altre sezioni o ricaricare la pagina: l’analisi
            continua e lo stato viene recuperato. La bozza completa viene
            conservata prima della revisione.
          </p>
          <button className="btn-secondary" type="button" onClick={onCancel}>
            Annulla analisi
          </button>
        </>
      ) : (
        job.status !== "completed" && (
          <>
            <p className="text-sm text-slate-300">
              {job.error || "Nessuna nuova guida pubblicata."}
            </p>
            <p className="text-sm text-slate-400">
              {job.has_draft
                ? "La bozza è conservata separatamente dalle guide approvate. Riprendi per verificare il testo, senza ricrearlo."
                : "Il provider non ha restituito una bozza completa. Puoi avviare un nuovo tentativo."}
            </p>
            {job.has_draft && (
              <button className="btn-primary" type="button" onClick={onResume}>
                Riprendi revisione della bozza
              </button>
            )}
          </>
        )
      )}
    </section>
  );
}
