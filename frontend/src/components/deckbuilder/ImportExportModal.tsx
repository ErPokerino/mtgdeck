import React, { useEffect, useState } from "react";
import { Check, Copy, Download, FileText, Upload, X } from "lucide-react";
import type { ConsensusListText, FormatId } from "../../types";
import { api } from "../../api/client";
import { useDialog } from "../../hooks/useDialog";

interface ImportExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  formatId: FormatId;
  arenaText: string;
  mtgoText: string;
  onImportText: (text: string, deckName: string) => Promise<void>;
}

export const ImportExportModal: React.FC<ImportExportModalProps> = ({
  isOpen,
  onClose,
  formatId,
  arenaText,
  mtgoText,
  onImportText,
}) => {
  const [mode, setMode] = useState<"import" | "export">("import");
  const [exportType, setExportType] = useState<"arena" | "mtgo">("arena");
  const [deckName, setDeckName] = useState("");
  const [inputText, setInputText] = useState("");
  const [copied, setCopied] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Current consensus lists of the meta: always up to date, unlike hand-written samples.
  const [consensus, setConsensus] = useState<ConsensusListText[] | null>(null);
  const [consensusId, setConsensusId] = useState<number | "">("");
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setConsensus(null);
    api
      .getConsensusLists(formatId)
      .then((lists) => {
        if (cancelled) return;
        setConsensus(lists);
        setConsensusId(lists[0]?.archetype_id ?? "");
      })
      .catch(() => !cancelled && setConsensus([]));
    return () => {
      cancelled = true;
    };
  }, [isOpen, formatId]);

  const dialog = useDialog(isOpen, onClose);
  if (!isOpen) return null;

  const currentExportText = exportType === "arena" ? arenaText : mtgoText;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(currentExportText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleLoadConsensus = () => {
    const chosen = consensus?.find((c) => c.archetype_id === consensusId);
    if (!chosen) return;
    setDeckName(`${chosen.name} (consenso)`);
    setInputText(chosen.text);
    setError(null);
  };

  const handleImport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim()) return;
    setImporting(true);
    setError(null);
    try {
      await onImportText(
        inputText,
        deckName || `Imported ${formatId.toUpperCase()} Deck`,
      );
      onClose();
    } catch (err: any) {
      setError(err.message || "Errore durante l’importazione della lista");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-export-title"
        tabIndex={-1}
        className="bg-[#0D111A] border border-[#242F46] rounded-xl max-w-2xl w-full shadow-2xl overflow-hidden max-h-[calc(100vh-2rem)] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 bg-[#121826] border-b border-[#1E2638] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-[#C8AA6E]" />
            <h2
              id="import-export-title"
              className="font-display font-bold text-base text-[#F3E5C8]"
            >
              Import / Export Mazzo (MTG Arena & MTGO)
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#1B2336] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* Mode Tabs */}
          <div className="grid grid-cols-2 gap-2 p-1 rounded-lg bg-[#080A0F] border border-[#1E2638]">
            <button
              type="button"
              onClick={() => setMode("import")}
              className={`py-2 rounded-md text-xs font-bold flex items-center justify-center gap-2 cursor-pointer ${
                mode === "import"
                  ? "bg-[#C8AA6E] text-[#090B10]"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Upload className="w-3.5 h-3.5" />
              <span>Importa da Arena / MTGO</span>
            </button>
            <button
              type="button"
              onClick={() => setMode("export")}
              className={`py-2 rounded-md text-xs font-bold flex items-center justify-center gap-2 cursor-pointer ${
                mode === "export"
                  ? "bg-[#C8AA6E] text-[#090B10]"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Download className="w-3.5 h-3.5" />
              <span>Esporta in Arena / MTGO</span>
            </button>
          </div>

          {mode === "import" ? (
            <form onSubmit={handleImport} className="space-y-3">
              <input
                type="text"
                value={deckName}
                onChange={(e) => setDeckName(e.target.value)}
                placeholder={`Nome del mazzo (${formatId.toUpperCase()})...`}
                aria-label="Nome del mazzo"
                className="w-full px-3 py-2 rounded-lg bg-[#090C12] border border-[#222B40] text-xs text-white focus:outline-none focus:border-[#C8AA6E]"
              />
              {consensus === null ? (
                <p className="text-xs text-slate-400">Carico le liste di consenso del meta…</p>
              ) : consensus.length === 0 ? (
                <p className="text-xs text-slate-400">
                  Nessuna lista di consenso: sincronizza il metagame per partire da una lista da torneo.
                </p>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={consensusId}
                    onChange={(e) => setConsensusId(Number(e.target.value))}
                    aria-label="Archetipo del meta"
                    className="flex-1 min-w-0 px-3 py-2 rounded-lg bg-[#090C12] border border-[#222B40] text-xs text-white"
                  >
                    {consensus.map((c) => (
                      <option key={c.archetype_id} value={c.archetype_id}>
                        {c.name} · {c.meta_share_pct}% · {c.lists_count} liste
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={handleLoadConsensus}
                    className="px-3 py-2 rounded-lg bg-[#151D2E] hover:bg-[#1D2840] border border-[#2B3A5A] text-xs font-medium text-[#F3E5C8] cursor-pointer shrink-0"
                  >
                    Carica la lista di consenso
                  </button>
                </div>
              )}

              <textarea
                rows={13}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder={`Incolla qui la lista in formato MTG Arena o MTGO:\n\nDeck\n4 Sheoldred, the Apocalypse (DMU) 107\n4 Go for the Throat (BRO) 102\n...\n\nSideboard\n3 Duress (FDN) 606`}
                className="w-full p-3 rounded-lg bg-[#080A0F] border border-[#222B40] text-xs font-mono-tech text-slate-200 focus:outline-none focus:border-[#C8AA6E]"
              />

              {error && (
                <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-700/50 text-xs text-rose-200">
                  {error}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded-lg bg-[#141A28] text-xs text-slate-300 cursor-pointer"
                >
                  Annulla
                </button>
                <button
                  type="submit"
                  disabled={importing || !inputText.trim()}
                  className="px-5 py-2 rounded-lg bg-gradient-to-r from-[#C8AA6E] to-[#A8894C] text-[#090B10] font-bold text-xs disabled:opacity-40 cursor-pointer"
                >
                  {importing
                    ? "Verifica carte su Scryfall..."
                    : "Importa e valida il mazzo"}
                </button>
              </div>
            </form>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setExportType("arena")}
                    className={`px-3 py-1 rounded text-xs font-mono-tech cursor-pointer ${
                      exportType === "arena"
                        ? "bg-[#1D273D] text-[#F3E5C8] border border-[#C8AA6E]/50"
                        : "text-slate-400 hover:text-white"
                    }`}
                  >
                    Formato MTG Arena (con Set & #)
                  </button>
                  <button
                    type="button"
                    onClick={() => setExportType("mtgo")}
                    className={`px-3 py-1 rounded text-xs font-mono-tech cursor-pointer ${
                      exportType === "mtgo"
                        ? "bg-[#1D273D] text-[#F3E5C8] border border-[#C8AA6E]/50"
                        : "text-slate-400 hover:text-white"
                    }`}
                  >
                    Formato MTGO / Testo Puro
                  </button>
                </div>

                <button
                  type="button"
                  onClick={handleCopy}
                  className="px-3 py-1.5 rounded-lg bg-[#C8AA6E] hover:bg-[#D9BC82] text-[#090B10] font-bold text-xs flex items-center gap-1.5 cursor-pointer"
                >
                  {copied ? (
                    <Check className="w-3.5 h-3.5" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" />
                  )}
                  <span>
                    {copied ? "Copiato negli appunti!" : "Copia la lista"}
                  </span>
                </button>
              </div>

              <textarea
                readOnly
                rows={14}
                value={currentExportText}
                className="w-full p-3 rounded-lg bg-[#080A0F] border border-[#222B40] text-xs font-mono-tech text-slate-200 focus:outline-none"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
