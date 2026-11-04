import { useEffect, useState } from "react";
import { api } from "../../api/client";

const CRITERIA = [
  ["depth", "Profondità"],
  ["correctness", "Correttezza"],
  ["usefulness", "Utilità in gara"],
] as const;

type Scores = Record<(typeof CRITERIA)[number][0], number>;

/** Human evaluation (M4): 1-5 per criterion, averaged in the quality report. */
export function RatingForm({ kind, id }: { kind: "guide" | "deck"; id: number }) {
  const [scores, setScores] = useState<Scores>({ depth: 3, correctness: 3, usefulness: 3 });
  const [note, setNote] = useState("");
  const [summary, setSummary] = useState<any>(null);
  const [status, setStatus] = useState("");
  useEffect(() => {
    api.getRating(kind, id).then(setSummary).catch(() => {});
  }, [kind, id]);
  const save = async () => {
    setStatus("");
    try {
      setSummary(
        await api.addRating({ target_kind: kind, target_id: id, ...scores, note: note || undefined }),
      );
      setNote("");
      setStatus("Valutazione salvata.");
    } catch (e: any) {
      setStatus(e.message);
    }
  };
  return (
    <section className="panel space-y-3" aria-labelledby={`rating-${kind}-${id}`}>
      <h3 id={`rating-${kind}-${id}`}>La tua valutazione</h3>
      <p className="text-sm text-slate-400">
        Serve a misurare se i cambi di prompt o di modello migliorano davvero i risultati.
        {summary &&
          ` Media di ${summary.count} valutazion${summary.count === 1 ? "e" : "i"}: profondità ${summary.depth}, correttezza ${summary.correctness}, utilità ${summary.usefulness}.`}
      </p>
      <div className="grid sm:grid-cols-3 gap-3">
        {CRITERIA.map(([field, label]) => (
          <label key={field} className="text-sm text-slate-300">
            {label}
            <select
              className="field w-full mt-1"
              value={scores[field]}
              onChange={(e) => setScores((s) => ({ ...s, [field]: Number(e.target.value) }))}
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <label className="block text-sm text-slate-300">
        Nota (facoltativa)
        <input
          className="field w-full mt-1"
          value={note}
          maxLength={1000}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Es. piano contro Izzet Control generico, sidata on the draw sbagliata"
        />
      </label>
      <div className="flex items-center gap-3">
        <button type="button" className="btn-secondary" onClick={save}>
          Salva valutazione
        </button>
        {status && (
          <span role="status" className="text-sm text-slate-300">
            {status}
          </span>
        )}
      </div>
    </section>
  );
}
