import React, { useState } from "react";
import { Check, Copy, Download, FileText, Upload, X } from "lucide-react";
import type { FormatId } from "../../types";

interface ImportExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  formatId: FormatId;
  arenaText: string;
  mtgoText: string;
  onImportText: (text: string, deckName: string) => Promise<void>;
}

const SAMPLE_LISTS: Record<FormatId, { name: string; list: string }> = {
  standard: {
    name: "Dimir Midrange (Standard Sample)",
    list: `Deck
4 Deep-Cavern Bat (LCI) 102
4 Spyglass Siren (LCI) 78
4 Preacher of the Schism (LCI) 113
3 Enduring Curiosity (DSK) 51
2 Aclazotz, Deepest Betrayal (LCI) 88
4 Shoot the Sheriff (OTJ) 106
3 Bitter Triumph (LCI) 91
3 Phantom Interference (OTJ) 61
2 Three Steps Ahead (OTJ) 75
2 Tishana's Tidebinder (LCI) 81
4 Kaito, Bane of Nightmares (DSK) 220
2 Withering Torment (DSK) 124
4 Gloomlake Verge (DSK) 260
4 Restless Reef (LCI) 282
4 Undercity Sewers (MKM) 270
2 Fountainport (BLB) 253
5 Island (FDN) 275
4 Swamp (FDN) 277

Sideboard
3 Duress (FDN) 606
2 Negate (FDN) 710
2 Disdainful Stroke (WOE) 47
2 Deadly Cover-Up (MKM) 83
3 Ghost Vacuum (DSK) 248
2 Withering Torment (DSK) 124
1 Tishana's Tidebinder (LCI) 81`,
  },
  pioneer: {
    name: "Rakdos Midrange (Pioneer Sample)",
    list: `Deck
4 Bloodtithe Harvester (VOW) 232
4 Fable of the Mirror-Breaker (NEO) 141
4 Graveyard Trespasser (MID) 104
3 Sheoldred, the Apocalypse (DMU) 107
2 Kroxa, Titan of Death's Hunger (THB) 221
4 Thoughtseize (THS) 107
4 Fatal Push (AER) 57
2 Go for the Throat (BRO) 102
2 Dreadbore (RTR) 157
3 Reckoner Bankbuster (NEO) 255
2 Liliana of the Veil (DMU) 97
2 Invoke Despair (NEO) 101
4 Blood Crypt (RNA) 245
4 Blackcleave Cliffs (ONE) 248
4 Blightstep Pathway (KHM) 252
4 Haunted Ridge (MID) 263
2 Hive of the Eye Tyrant (AFR) 258
2 Den of the Bugbear (AFR) 254
2 Urborg, Tomb of Yawgmoth (TSR) 287
2 Swamp (FDN) 277

Sideboard
2 Duress (M21) 96
3 Unlicensed Hearse (SNC) 246
2 Extinction Event (IKO) 88
2 Rending Volley (DTK) 150
2 Hidetsugu Consumes All (NEO) 221
2 Kolaghan's Command (DTK) 224
2 Go Blank (STX) 72`,
  },
  modern: {
    name: "Boros Energy (Modern Sample)",
    list: `Deck
4 Guide of Souls (MH3) 29
4 Ocelot Pride (MH3) 38
4 Ajani, Nacatl Pariah (MH3) 237
4 Ragavan, Nimble Pilferer (MH2) 138
4 Seasoned Pyromancer (2X2) 123
4 Fable of the Mirror-Breaker (NEO) 141
4 Galvanic Discharge (MH3) 122
4 Static Prison (MH3) 44
3 Thraben Charm (MH3) 45
4 Goblin Bombardment (MH2) 279
4 Arid Mesa (MH2) 244
4 Marsh Flats (MH2) 248
4 Windswept Heath (MH3) 235
2 Sacred Foundry (GRN) 254
2 Elegant Parlor (MKM) 260
1 Arena of Glory (MH3) 215
2 Plains (MH3) 310
2 Mountain (MH3) 316

Sideboard
3 Consign to Memory (MH3) 54
2 Wrath of the Skies (MH3) 49
3 Obsidian Charmaw (MH2) 137
2 Wear // Tear (DGM) 135
2 Drannith Magistrate (IKO) 11
2 Surgical Extraction (2X2) 94
1 Suncleanser (M19) 39`,
  },
};

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

  if (!isOpen) return null;

  const currentExportText = exportType === "arena" ? arenaText : mtgoText;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(currentExportText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleLoadSample = () => {
    const sample = SAMPLE_LISTS[formatId];
    setDeckName(sample.name);
    setInputText(sample.list);
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
        className="bg-[#0D111A] border border-[#242F46] rounded-xl max-w-2xl w-full shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 bg-[#121826] border-b border-[#1E2638] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-[#C8AA6E]" />
            <h2 className="font-display font-bold text-base text-[#F3E5C8]">
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
              <div className="flex items-center justify-between gap-3">
                <input
                  type="text"
                  value={deckName}
                  onChange={(e) => setDeckName(e.target.value)}
                  placeholder={`Nome del mazzo (${formatId.toUpperCase()})...`}
                  className="flex-1 px-3 py-2 rounded-lg bg-[#090C12] border border-[#222B40] text-xs text-white focus:outline-none focus:border-[#C8AA6E]"
                />
                <button
                  type="button"
                  onClick={handleLoadSample}
                  className="px-3 py-2 rounded-lg bg-[#151D2E] hover:bg-[#1D2840] border border-[#2B3A5A] text-xs font-medium text-[#F3E5C8] cursor-pointer shrink-0"
                >
                  Carica Mazzo Esempio ({formatId.toUpperCase()})
                </button>
              </div>

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
                    : "Importa e Valida Mazzo"}
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
                    {copied ? "Copiato negli appunti!" : "Copia Lista"}
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
