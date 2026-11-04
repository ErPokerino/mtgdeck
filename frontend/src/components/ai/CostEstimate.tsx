import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { RunEstimate } from "../../types";

const tokens = (n: number) =>
  n >= 1000 ? `${Math.round(n / 1000).toLocaleString("it-IT")}k` : String(n);
const minutes = (s: number) => (s < 90 ? `${s} s` : `${Math.round(s / 60)} min`);

/** Expected duration, tokens and cost of the next run, from the latest real ones. */
export function CostEstimate({
  skill,
  modelId,
}: {
  skill: RunEstimate["skill"];
  modelId?: string;
}) {
  const [est, setEst] = useState<RunEstimate | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .getRunEstimate(skill, modelId)
      .then((e) => !cancelled && setEst(e))
      .catch(() => !cancelled && setEst(null));
    return () => {
      cancelled = true;
    };
  }, [skill, modelId]);

  if (!est) return null;
  if (est.runs === 0)
    return (
      <p className="text-xs text-slate-400">
        Stima non disponibile: nessuna esecuzione precedente di questo tipo.
      </p>
    );
  const parts = [`circa ${minutes(est.avg_duration_s ?? 0)}`];
  if (est.avg_input_tokens != null && est.avg_output_tokens != null)
    parts.push(
      `${tokens(est.avg_input_tokens)} token in ingresso e ${tokens(est.avg_output_tokens)} in uscita`,
    );
  if (est.avg_cost != null)
    parts.push(`${est.avg_cost.toFixed(2)} ${est.currency || ""}`.trim());
  return (
    <p className="text-xs text-slate-400">
      Stima: {parts.join(" · ")} (media delle ultime {est.runs} esecuzioni
      {est.same_model ? " con questo modello" : " con altri modelli"}).
      {est.avg_cost == null &&
        est.avg_input_tokens != null &&
        " Imposta la tariffa del modello in config/ai-models.json per vedere il costo."}
    </p>
  );
}
