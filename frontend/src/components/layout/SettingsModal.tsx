import React, { useState, useEffect } from "react";
import { useDialog } from "../../hooks/useDialog";
import {
  Check,
  Cpu,
  Database,
  KeyRound,
  RefreshCw,
  ShieldCheck,
  Zap,
  X,
} from "lucide-react";
import type { AppSettings, SyncStatus } from "../../types";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  settings: AppSettings | null;
  syncStatus: SyncStatus | null;
  onSaveSettings: (payload: {
    gemini_api_key?: string;
    selected_complex_model_id?: string;
    ai_provider?: string;
    gcp_project?: string;
    gcp_location?: string;
  }) => Promise<void>;
  onTriggerScryfallSync: (force: boolean) => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  settings,
  syncStatus,
  onSaveSettings,
  onTriggerScryfallSync,
}) => {
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [complexModel, setComplexModel] = useState(
    settings?.selected_complex_model_id || "gemini-3.8-flash",
  );
  const [saving, setSaving] = useState(false);
  const [savedBanner, setSavedBanner] = useState(false);

  useEffect(() => {
    if (isOpen && settings) setComplexModel(settings.selected_complex_model_id);
  }, [isOpen, settings?.selected_complex_model_id]);
  const dialog = useDialog(isOpen && !!settings, onClose);
  if (!isOpen || !settings) return null;

  const complexModels = settings.available_models.filter(
    (m) => m.tier === "complex",
  );
  const simpleModels = settings.available_models.filter(
    (m) => m.tier === "simple",
  );

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSavedBanner(false);
    try {
      const payload: Record<string, string> = {
        selected_complex_model_id: complexModel,
      };
      if (apiKeyInput.trim() !== "") {
        payload.gemini_api_key = apiKeyInput.trim();
      }
      await onSaveSettings(payload);
      setApiKeyInput("");
      setSavedBanner(true);
      setTimeout(() => setSavedBanner(false), 3000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        tabIndex={-1}
        className="bg-[#0E121B] border border-[#242E44] rounded-xl max-w-2xl w-full shadow-2xl overflow-hidden max-h-[calc(100vh-2rem)] overflow-y-auto"
      >
        {/* Header */}
        <div className="px-6 py-4 bg-[#121826] border-b border-[#1F293D] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Cpu className="w-5 h-5 text-[#C8AA6E]" />
            <h2
              id="settings-title"
              className="font-display font-bold text-base text-[#F3E5C8]"
            >
              Impostazioni
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#1C2539] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form
          onSubmit={handleSave}
          className="p-6 space-y-6 max-h-[82vh] overflow-y-auto"
        >
          {/* Gemini API Key */}
          <div className="p-4 rounded-lg bg-[#0A0D14] border border-[#1E2638] space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5 text-[#C8AA6E]" />
                <span>Gemini API Key</span>
              </label>
              {settings.has_gemini_api_key ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-mono-tech text-emerald-400 bg-emerald-950/50 border border-emerald-700/40 px-2 py-0.5 rounded">
                  <ShieldCheck className="w-3 h-3" /> Configurata (
                  {settings.masked_gemini_api_key})
                </span>
              ) : (
                <span className="text-[11px] text-amber-400 font-mono-tech">
                  Nessuna API Key salvata
                </span>
              )}
            </div>
            <input
              type="password"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder={
                settings.has_gemini_api_key
                  ? "Inserisci una nuova chiave per sostituire quella attuale..."
                  : "Incolla qui la tua Gemini API Key (AIza...)"
              }
              className="w-full px-3 py-2 rounded-lg bg-[#121723] border border-[#26314A] text-xs text-white font-mono-tech focus:outline-none focus:border-[#C8AA6E]"
            />
          </div>

          {/* Selezione Modello AI Principale */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold uppercase tracking-wider text-[#F3E5C8]">
                Modello AI Principale (Generazione Mazzi, Guide Pro & Matchup)
              </label>
            </div>

            <div className="grid grid-cols-1 gap-2.5">
              {complexModels.map((m) => {
                const selected = complexModel === m.id;
                return (
                  <button
                    type="button"
                    key={m.id}
                    aria-pressed={selected}
                    onClick={() => setComplexModel(m.id)}
                    className={`w-full text-left p-3.5 rounded-lg border transition-all cursor-pointer flex items-start justify-between gap-3 ${
                      selected
                        ? "bg-[#171F32] border-[#C8AA6E]"
                        : "bg-[#0A0D14] border-[#1E2638] hover:border-slate-600"
                    }`}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-[#F3E5C8]">
                          {m.label}
                        </span>
                        <span className="text-[11px] font-mono-tech px-1.5 py-0.5 rounded bg-[#101522] text-purple-300 border border-purple-500/30">
                          {m.id}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-300 mt-1">
                        {m.description}
                      </p>
                    </div>
                    <div
                      className={`w-4 h-4 rounded-full border flex items-center justify-center mt-0.5 shrink-0 ${
                        selected
                          ? "border-[#C8AA6E] bg-[#C8AA6E] text-black"
                          : "border-slate-600"
                      }`}
                    >
                      {selected && <Check className="w-3 h-3 stroke-[3]" />}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Info trasparente sul modello automatico Flash Lite */}
            <div className="p-3 rounded-lg bg-[#0A0D14] border border-[#1E2638] flex items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <Zap className="w-4 h-4 text-emerald-400 shrink-0" />
                <div>
                  <div className="text-xs font-semibold text-slate-200">
                    Validazione & Auto-Riparazione Rapida:{" "}
                    <span className="text-emerald-300">
                      {simpleModels[0]?.label || "Gemini Flash Lite 3.5"}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400">
                    Usato sempre in automatico per rivalutare e correggere
                    istantaneamente eventuali violazioni di set ammessi, banlist
                    o conteggio 60/15 carte.
                  </p>
                </div>
              </div>
              <span className="px-2 py-0.5 rounded text-[11px] font-mono-tech bg-emerald-950/60 text-emerald-300 border border-emerald-700/40 shrink-0">
                Sempre Attivo
              </span>
            </div>
          </div>

          {/* Stato Database Locale Scryfall */}
          <div className="p-4 rounded-lg bg-[#0A0D14] border border-[#1E2638] flex items-center justify-between">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
                <Database className="w-3.5 h-3.5 text-[#C8AA6E]" />
                <span>Database Carte Scryfall</span>
              </div>
              <p className="text-[11px] text-slate-400">
                Carte indicizzate:{" "}
                <strong className="text-white font-mono-tech">
                  {(syncStatus?.total_cards_in_db || 0).toLocaleString("it-IT")}
                </strong>{" "}
                | Set:{" "}
                <strong className="text-white font-mono-tech">
                  {syncStatus?.total_sets_in_db || 0}
                </strong>
              </p>
            </div>
            <button
              type="button"
              onClick={() => onTriggerScryfallSync(true)}
              disabled={syncStatus?.scryfall_status === "running"}
              className="px-3 py-1.5 rounded-lg bg-[#161E31] hover:bg-[#1F2A44] border border-[#2C3A5E] text-xs font-medium text-slate-200 flex items-center gap-1.5 disabled:opacity-40 cursor-pointer"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${
                  syncStatus?.scryfall_status === "running"
                    ? "animate-spin text-[#C8AA6E]"
                    : ""
                }`}
              />
              <span>Aggiorna DB Carte</span>
            </button>
          </div>

          {/* Footer actions */}
          <div className="flex items-center justify-between pt-2 border-t border-[#1E2638]">
            <div>
              {savedBanner && (
                <span className="text-xs text-emerald-400 flex items-center gap-1">
                  <Check className="w-4 h-4" /> Impostazioni salvate con
                  successo!
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-lg bg-[#151B28] hover:bg-[#1D2536] text-xs font-medium text-slate-300 cursor-pointer"
              >
                Chiudi
              </button>
              <button
                type="submit"
                disabled={saving}
                className="px-5 py-2 rounded-lg bg-gradient-to-r from-[#C8AA6E] to-[#A8894C] text-[#090B10] font-bold text-xs shadow-md hover:brightness-110 disabled:opacity-50 cursor-pointer"
              >
                {saving ? "Salvataggio..." : "Salva Impostazioni"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
