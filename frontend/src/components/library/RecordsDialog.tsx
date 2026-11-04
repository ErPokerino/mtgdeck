import { useEffect, useState } from "react";
import { Trash2, X } from "lucide-react";
import { api } from "../../api/client";
import type { FormatId } from "../../types";
import { useDialog } from "../../hooks/useDialog";

/** The user's real matches with a deck (M6): they reach the next guide's context. */
export function RecordsDialog({
  deck,
  formatId,
  onClose,
}: {
  deck: { id: number; name: string };
  formatId: FormatId;
  onClose: () => void;
}) {
  const dialog = useDialog(true, onClose);
  const [data, setData] = useState<any>({ records: [], summary: [] });
  const [archetypes, setArchetypes] = useState<string[]>([]);
  const [opponent, setOpponent] = useState("");
  const [won, setWon] = useState(2),
    [lost, setLost] = useState(0);
  const [onPlay, setOnPlay] = useState<"" | "play" | "draw">("");
  const [playedOn, setPlayedOn] = useState(new Date().toISOString().slice(0, 10));
  const [event, setEvent] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api.listRecords(deck.id).then(setData).catch((e) => setError(e.message));
    api
      .getFormatMeta(formatId)
      .then((m) => {
        const names = (m.archetypes || []).map((a) => a.name);
        setArchetypes(names);
        setOpponent((o) => o || names[0] || "");
      })
      .catch(() => {});
  }, [deck.id, formatId]);
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      setData(
        await api.addRecord(deck.id, {
          opponent_archetype: opponent.trim(),
          games_won: won,
          games_lost: lost,
          on_the_play: onPlay === "" ? null : onPlay === "play",
          played_on: playedOn || null,
          event: event.trim() || null,
        }),
      );
    } catch (e: any) {
      setError(e.message);
    }
  };
  const games = [0, 1, 2, 3];
  return (
    <div className="modal-backdrop">
      <div
        ref={dialog}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="records-title"
        className="panel max-w-3xl w-full max-h-[85vh] overflow-y-auto space-y-4"
      >
        <div className="flex justify-between gap-3">
          <div>
            <h2 id="records-title" className="text-xl font-bold">
              Risultati reali · {deck.name}
            </h2>
            <p className="text-sm text-slate-400 mt-1">
              I tuoi match entrano nel contesto della prossima guida, che li confronta con le stime.
            </p>
          </div>
          <button className="btn-secondary h-fit" onClick={onClose} aria-label="Chiudi risultati">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={add} className="grid sm:grid-cols-6 gap-3 items-end">
          <label className="sm:col-span-2 text-sm text-slate-300">
            Avversario
            <input
              className="field w-full mt-1"
              list="records-archetypes"
              value={opponent}
              onChange={(e) => setOpponent(e.target.value)}
              required
            />
            <datalist id="records-archetypes">
              {archetypes.map((a) => (
                <option key={a} value={a} />
              ))}
            </datalist>
          </label>
          <label className="text-sm text-slate-300">
            Game vinti
            <select className="field w-full mt-1" value={won} onChange={(e) => setWon(Number(e.target.value))}>
              {games.map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-300">
            Game persi
            <select className="field w-full mt-1" value={lost} onChange={(e) => setLost(Number(e.target.value))}>
              {games.map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-300">
            Game 1
            <select
              className="field w-full mt-1"
              value={onPlay}
              onChange={(e) => setOnPlay(e.target.value as "" | "play" | "draw")}
            >
              <option value="">n/d</option>
              <option value="play">on the play</option>
              <option value="draw">on the draw</option>
            </select>
          </label>
          <label className="text-sm text-slate-300">
            Data
            <input
              type="date"
              className="field w-full mt-1"
              value={playedOn}
              onChange={(e) => setPlayedOn(e.target.value)}
            />
          </label>
          <label className="sm:col-span-4 text-sm text-slate-300">
            Evento (facoltativo)
            <input className="field w-full mt-1" value={event} maxLength={128} onChange={(e) => setEvent(e.target.value)} />
          </label>
          <button type="submit" className="btn-primary sm:col-span-2">
            Aggiungi risultato
          </button>
        </form>
        {error && (
          <p className="notice-error" role="alert">
            {error}
          </p>
        )}
        {data.summary.length > 0 && (
          <div className="overflow-x-auto">
            <table className="data-table">
              <caption className="text-left text-sm text-slate-300 pb-2">Riepilogo per archetipo</caption>
              <thead>
                <tr>
                  <th scope="col">Avversario</th>
                  <th scope="col">Match</th>
                  <th scope="col">Game</th>
                </tr>
              </thead>
              <tbody>
                {data.summary.map((r: any) => (
                  <tr key={r.opponent_archetype}>
                    <td>{r.opponent_archetype}</td>
                    <td>
                      {r.matches_won}-{r.matches_lost}
                      {r.matches_drawn ? `-${r.matches_drawn}` : ""}
                    </td>
                    <td>
                      {r.games_won}-{r.games_lost}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <ul className="space-y-2 text-sm">
          {data.records.map((r: any) => (
            <li key={r.id} className="flex items-center justify-between gap-3 border-b border-slate-800 pb-2">
              <span>
                {r.played_on || "senza data"} · {r.opponent_archetype} · {r.games_won}-{r.games_lost}
                {r.on_the_play != null && ` · G1 ${r.on_the_play ? "on the play" : "on the draw"}`}
                {r.event && ` · ${r.event}`}
              </span>
              <button
                className="btn-secondary"
                aria-label={`Elimina il risultato contro ${r.opponent_archetype} del ${r.played_on || "giorno non indicato"}`}
                onClick={async () => setData(await api.deleteRecord(r.id))}
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
