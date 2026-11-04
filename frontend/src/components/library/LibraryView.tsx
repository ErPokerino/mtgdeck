import React, { useEffect, useState } from "react";
import {
  Archive,
  BookOpen,
  Copy,
  FolderOpen,
  History,
  Search,
  Trash2,
  Download,
  X,
} from "lucide-react";
import { api } from "../../api/client";
import type { DeckDetail, DeckSummary, FormatId } from "../../types";
import { GuideReader } from "./GuideReader";
import { useDialog } from "../../hooks/useDialog";

export function LibraryView({
  formatId,
  onOpen,
  onPlaytest,
  onGuide,
  onDelete,
  onRestored,
}: {
  formatId: FormatId;
  onOpen: (d: DeckDetail) => void;
  onPlaytest: (d: DeckDetail) => void;
  onGuide: (d: DeckDetail) => void;
  onDelete: (id: number) => void;
  onRestored: (d: DeckDetail) => void;
}) {
  const [tab, setTab] = useState<"active" | "archived" | "guides">("active");
  const [decks, setDecks] = useState<DeckSummary[]>([]),
    [guides, setGuides] = useState<any[]>([]);
  const [query, setQuery] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  const [guide, setGuide] = useState<any>(null),
    [revisions, setRevisions] = useState<any[] | null>(null),
    [revisionDeck, setRevisionDeck] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{
    kind: "deck" | "guide";
    id: number;
    name: string;
  } | null>(null);
  const load = async () => {
    setLoading(true);
    try {
      const [d, g] = await Promise.all([
        api.listDecks(formatId, tab === "archived"),
        api.listGuides(formatId),
      ]);
      setDecks(d);
      setGuides(g);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    setGuide(null);
    setRevisions(null);
    setError("");
    load();
  }, [formatId, tab]);
  // Only the topmost dialog traps focus and reacts to Esc.
  const guideDialog = useDialog(!!guide && !revisions && !pendingDelete, () =>
    setGuide(null),
  );
  const revisionsDialog = useDialog(!!revisions && !pendingDelete, () =>
    setRevisions(null),
  );
  const deleteDialog = useDialog(!!pendingDelete, () => setPendingDelete(null));
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="max-w-[1500px] mx-auto p-4 md:p-7 space-y-6">
      <div className="flex flex-wrap justify-between gap-4">
        <div>
          <p className="eyebrow">Il tuo spazio di preparazione · {formatId}</p>
          <h1 className="text-3xl font-bold mt-2">Mazzi e guide</h1>
          <p className="text-slate-400 mt-3 max-w-3xl leading-relaxed">
            I mazzi salvati e generati restano nel database dell’app. Ogni
            salvataggio conserva una versione; ogni guida conserva la lista
            analizzata. Archivia per liberare i selettori senza perdere lo
            storico.
          </p>
        </div>
        <div className="panel text-sm max-w-sm">
          <strong className="text-amber-200">Dove sono i miei dati?</strong>
          <p className="text-slate-400 mt-2">
            Nel server configurato. In locale: data/mtgdeck.db. Il browser
            conserva solo bozze e preferenze. Esporta liste e PDF per portarli
            con te.
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {(["active", "archived", "guides"] as const).map((t) => (
            <button
              key={t}
              aria-pressed={tab === t}
              onClick={() => setTab(t)}
              className={tab === t ? "btn-primary" : "btn-secondary"}
            >
              {t === "active" ? (
                <FolderOpen size={16} />
              ) : t === "archived" ? (
                <Archive size={16} />
              ) : (
                <BookOpen size={16} />
              )}{" "}
              {t === "active"
                ? "Mazzi attivi"
                : t === "archived"
                  ? "Archiviati"
                  : "Guide salvate"}
            </button>
          ))}
        </div>
        <label className="flex gap-2 items-center">
          <Search size={16} />
          <input
            className="field"
            placeholder="Cerca per nome o archetipo"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      {error && (
        <p role="alert" className="notice-error">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status" className="panel">
          Caricamento archivio…
        </p>
      ) : tab === "guides" ? (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {guides
            .filter((g) =>
              (g.deck_name || "").toLowerCase().includes(query.toLowerCase()),
            )
            .map((g) => (
              <section className="panel space-y-4" key={g.id}>
                <p className="eyebrow">
                  Guida #{g.id} ·{" "}
                  {new Date(g.created_at).toLocaleString("it-IT")}
                </p>
                <h2 className="text-lg font-bold">{g.deck_name}</h2>
                <p className="text-sm text-slate-400">
                  {g.model_id} ·{" "}
                  {g.deck_id
                    ? "Associata al mazzo #" + g.deck_id
                    : "Lista conservata nella guida"}
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="btn-primary"
                    onClick={() =>
                      act(async () => setGuide(await api.getGuide(g.id)))
                    }
                  >
                    Leggi
                  </button>
                  <a
                    href={`/api/guides/${g.id}/pdf`}
                    download
                    className="btn-secondary"
                  >
                    <Download size={15} />
                    PDF
                  </a>
                  <button
                    className="btn-danger"
                    aria-label={`Elimina guida ${g.deck_name}`}
                    onClick={() =>
                      setPendingDelete({
                        kind: "guide",
                        id: g.id,
                        name: g.deck_name,
                      })
                    }
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </section>
            ))}
        </div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {decks
            .filter((d) =>
              (d.name + " " + d.archetype)
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((d) => (
              <section className="panel space-y-4" key={d.id}>
                <div className="flex justify-between gap-2">
                  <p className="eyebrow">
                    #{d.id} ·{" "}
                    {d.source === "ai_generated"
                      ? "Generato con AI"
                      : d.source === "manual"
                        ? "Creato nel builder"
                        : "Importato"}
                  </p>
                  <span
                    className={
                      d.is_valid
                        ? "text-emerald-300 text-xs"
                        : "text-amber-200 text-xs"
                    }
                  >
                    {d.is_valid ? "Legale nel DB" : "Da verificare"}
                  </span>
                </div>
                <h2 className="text-xl font-bold">{d.name}</h2>
                <p className="text-sm text-slate-300">
                  {d.color_label} · {d.archetype} · {d.mainboard_count} main /{" "}
                  {d.sideboard_count} side
                </p>
                <p className="text-xs text-slate-400">
                  {new Date(d.updated_at).toLocaleString("it-IT")} ·{" "}
                  {d.revision_count || 0}{" "}
                  {d.revision_count === 1 ? "versione" : "versioni"} ·{" "}
                  {d.guide_count || 0} {d.guide_count === 1 ? "guida" : "guide"}
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="btn-primary"
                    disabled={busy}
                    onClick={() =>
                      act(async () => onOpen(await api.getDeck(d.id)))
                    }
                  >
                    Apri builder
                  </button>
                  <button
                    className="btn-secondary"
                    disabled={busy}
                    onClick={() =>
                      act(async () => onPlaytest(await api.getDeck(d.id)))
                    }
                  >
                    Playtest
                  </button>
                  <button
                    className="btn-secondary"
                    disabled={busy}
                    onClick={() =>
                      act(async () => onGuide(await api.getDeck(d.id)))
                    }
                  >
                    Guida
                  </button>
                </div>
                <div className="flex flex-wrap gap-2 border-t border-slate-800 pt-4">
                  <button
                    className="btn-secondary"
                    disabled={busy}
                    onClick={() => act(() => api.duplicateDeck(d.id))}
                  >
                    <Copy size={14} />
                    Duplica
                  </button>
                  <button
                    className="btn-secondary"
                    disabled={busy}
                    onClick={() =>
                      act(async () => {
                        setRevisions(await api.getRevisions(d.id));
                        setRevisionDeck(d.id);
                      })
                    }
                  >
                    <History size={14} />
                    Versioni
                  </button>
                  <button
                    className="btn-secondary"
                    disabled={busy}
                    onClick={() =>
                      act(() => api.archiveDeck(d.id, tab !== "archived"))
                    }
                  >
                    <Archive size={14} />
                    {tab === "archived" ? "Ripristina" : "Archivia"}
                  </button>
                  <button
                    className="btn-danger"
                    disabled={busy}
                    onClick={() =>
                      setPendingDelete({ kind: "deck", id: d.id, name: d.name })
                    }
                    aria-label={`Elimina mazzo ${d.name}`}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </section>
            ))}
        </div>
      )}
      {!loading && !(tab === "guides" ? guides : decks).length && (
        <div className="panel py-12 text-center">
          <h2 className="text-xl font-bold">
            {tab === "guides"
              ? "Nessuna guida salvata"
              : tab === "archived"
                ? "Nessun mazzo archiviato"
                : "Il tuo archivio è pronto"}
          </h2>
          <p className="text-slate-400 mt-3">
            {tab === "guides"
              ? "Genera una guida in AI Studio: ogni versione apparirà qui, anche per una lista incollata."
              : "Crea o importa una lista nel Deck Builder, oppure genera un mazzo con AI Studio."}
          </p>
        </div>
      )}
      {guide && (
        <div className="fixed inset-0 z-50 bg-black/80 overflow-y-auto p-3 md:p-8">
          <div
            ref={guideDialog}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label="Guida salvata"
            className="max-w-6xl mx-auto bg-[#0b101a] rounded-2xl p-5 md:p-8"
          >
            <button
              className="btn-secondary sticky top-0 z-10 mb-5 bg-[#0b101a] shadow-lg"
              onClick={() => setGuide(null)}
              autoFocus
            >
              <X size={16} />
              Chiudi guida
            </button>
            <GuideReader
              guide={{ ...guide.guide, deck_name: guide.deck_name }}
              guideId={guide.id}
            />
          </div>
        </div>
      )}
      {revisions && (
        <div className="modal-backdrop">
          <div
            ref={revisionsDialog}
            tabIndex={-1}
            className="panel max-w-3xl w-full max-h-[85vh] overflow-y-auto"
            role="dialog"
            aria-modal="true"
            aria-label="Versioni del mazzo"
          >
            <div className="flex justify-between">
              <h2 className="text-xl font-bold">Versioni salvate</h2>
              <button
                className="btn-secondary"
                onClick={() => setRevisions(null)}
              >
                Chiudi
              </button>
            </div>
            <p className="text-sm text-slate-400 my-4">
              Il ripristino salva una nuova versione. Le guide precedenti
              restano nella raccolta.
            </p>
            {!revisions.length && (
              <p>
                Nessuna versione disponibile: salva il mazzo per crearne una.
              </p>
            )}
            {revisions.map((r) => (
              <details key={r.id} className="border-t border-slate-800 py-4">
                <summary className="cursor-pointer">
                  #{r.id} · {new Date(r.created_at).toLocaleString("it-IT")} ·{" "}
                  {r.snapshot.name}
                </summary>
                <div className="my-3 grid md:grid-cols-2 gap-2 text-sm">
                  {r.snapshot.cards.map((c: any, i: number) => (
                    <p key={i}>
                      {c.quantity}× {c.card_name}{" "}
                      <span className="text-slate-400">{c.board}</span>
                    </p>
                  ))}
                </div>
                <button
                  className="btn-primary"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      const restored = await api.restoreRevision(
                        revisionDeck!,
                        r.id,
                      );
                      setRevisions(null);
                      onRestored(restored);
                    })
                  }
                >
                  Ripristina questa versione
                </button>
              </details>
            ))}
          </div>
        </div>
      )}
      {pendingDelete && (
        <div className="modal-backdrop">
          <div
            ref={deleteDialog}
            tabIndex={-1}
            className="panel max-w-lg"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-title"
          >
            <h2 id="delete-title" className="text-xl font-bold">
              Eliminare {pendingDelete.name}?
            </h2>
            <p className="text-slate-400 my-4">
              {pendingDelete.kind === "deck"
                ? "Il mazzo e le sue versioni verranno eliminati. Le guide conservano la propria lista. Puoi invece archiviare il mazzo per mantenerlo."
                : "Questa versione della guida verrà eliminata definitivamente."}
            </p>
            <div className="flex gap-3">
              <button
                className="btn-secondary"
                onClick={() => setPendingDelete(null)}
              >
                Annulla
              </button>
              <button
                className="btn-danger"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    if (pendingDelete.kind === "deck") {
                      await api.deleteDeck(pendingDelete.id);
                      onDelete(pendingDelete.id);
                    } else await api.deleteGuide(pendingDelete.id);
                    setPendingDelete(null);
                  })
                }
              >
                Elimina definitivamente
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
