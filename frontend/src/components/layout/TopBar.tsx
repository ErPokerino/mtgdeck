import React from "react";
import {
  Archive,
  CircleHelp,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Database,
  Flame,
  Layers,
  Play,
  RefreshCw,
  Settings,
  ShieldAlert,
  Sparkles,
  Swords,
} from "lucide-react";
import type {
  AppSettings,
  FormatId,
  FormatInfo,
  SyncStatus,
} from "../../types";

export type ActiveTab =
  "deckbuilder" | "format_info" | "meta" | "ai_studio" | "playtest" | "library";

interface TopBarProps {
  formats: FormatInfo[];
  selectedFormat: FormatId;
  onSelectFormat: (fmt: FormatId) => void;
  activeTab: ActiveTab;
  onSelectTab: (tab: ActiveTab) => void;
  canGoBack?: boolean;
  canGoForward?: boolean;
  onGoBack?: () => void;
  onGoForward?: () => void;
  syncStatus: SyncStatus | null;
  onTriggerSync: () => void;
  settings: AppSettings | null;
  onChangeComplexModel: (modelId: string) => void;
  onOpenSettings: () => void;
  onOpenHelp: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  formats,
  selectedFormat,
  onSelectFormat,
  activeTab,
  onSelectTab,
  canGoBack = false,
  canGoForward = false,
  onGoBack,
  onGoForward,
  syncStatus,
  onTriggerSync,
  settings,
  onChangeComplexModel,
  onOpenSettings,
  onOpenHelp,
}) => {
  const isSyncing = syncStatus?.scryfall_status === "running";
  const complexModels = (settings?.available_models || []).filter(
    (m) => m.tier === "complex",
  );

  const formatLastSync = (iso?: string | null) => {
    if (!iso) return "Mai sincronizzato";
    const d = new Date(iso);
    return d.toLocaleString("it-IT", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <header className="workspace-header sticky top-0 z-40 min-h-15 py-2 bg-[#0C0F17]/95 backdrop-blur-md border-b border-[#1E2638] px-4 flex items-center justify-between gap-4 select-none">
      {/* Left: Brand + Global Format Selector */}
      <div className="flex flex-wrap items-center gap-3 min-w-0 max-w-full">
        <div className="flex items-center gap-2.5 max-md:hidden">
          <div className="w-8 h-8 rounded bg-gradient-to-br from-[#C8AA6E] to-[#8C6D32] flex items-center justify-center shadow-[0_0_15px_rgba(200,170,110,0.3)] border border-[#E5C98B]/40">
            <Flame className="w-4 h-4 text-[#090B10] fill-[#090B10]" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-display font-bold tracking-wider text-sm text-[#F3E5C8]">
                AETHERDECK
              </span>
              <span className="text-[11px] font-mono-tech uppercase px-1.5 py-0.5 rounded bg-[#1A2130] text-[#C8AA6E] border border-[#C8AA6E]/30">
                PRO
              </span>
            </div>
            <p className="text-[11px] text-slate-400 leading-none">
              Competitive MTG Workbench
            </p>
          </div>
        </div>

        {/* Browser & In-App History Navigation (Back / Forward) */}
        <div className="flex items-center gap-1 bg-[#080A0F] p-0.5 rounded-lg border border-[#1E2638] max-md:hidden">
          <button
            type="button"
            onClick={onGoBack}
            disabled={!canGoBack}
            title="Torna indietro (Alt + Freccia Sinistra)"
            className="p-1.5 rounded-md text-slate-300 hover:text-[#F3E5C8] hover:bg-[#161E30] disabled:opacity-30 disabled:pointer-events-none transition-colors cursor-pointer"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onGoForward}
            disabled={!canGoForward}
            title="Vai avanti (Alt + Freccia Destra)"
            className="p-1.5 rounded-md text-slate-300 hover:text-[#F3E5C8] hover:bg-[#161E30] disabled:opacity-30 disabled:pointer-events-none transition-colors cursor-pointer"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="h-6 w-px bg-[#1E2638]" />

        {/* Format Selector (Requirement 1: Il formato si sceglie per primo e filtra tutto il resto) */}
        <div
          data-tour="formats"
          className="flex items-center bg-[#080A0F] p-1 rounded-lg border border-[#1E2638]"
        >
          <span className="text-[11px] font-mono-tech uppercase tracking-wider text-slate-400 px-2 max-md:hidden">
            Formato:
          </span>
          {(["standard", "pioneer", "modern"] as FormatId[]).map((fmtId) => {
            const info = formats.find((f) => f.id === fmtId);
            const active = selectedFormat === fmtId;
            return (
              <button
                key={fmtId}
                onClick={() => onSelectFormat(fmtId)}
                aria-pressed={active}
                className={`px-3 max-md:px-2.5 py-1 max-md:min-h-9 rounded-md text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer ${
                  active
                    ? "bg-gradient-to-r from-[#C8AA6E] to-[#A8894C] text-[#090B10] shadow-sm"
                    : "text-slate-300 hover:text-white hover:bg-[#141926]"
                }`}
              >
                <span className="capitalize">{fmtId}</span>
                {info && info.legal_cards_count > 0 && (
                  <span
                    className={`text-[11px] font-mono-tech px-1 rounded ${
                      active
                        ? "bg-black/20 text-[#090B10]"
                        : "bg-[#151B28] text-slate-400"
                    }`}
                  >
                    {(info.legal_cards_count / 1000).toFixed(1)}k
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Center: Workspace Navigation */}
      <nav className="flex items-center gap-1 bg-[#080A0F] p-1 rounded-lg border border-[#1E2638]">
        <button
          data-tour="deckbuilder"
          onClick={() => onSelectTab("deckbuilder")}
          className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
            activeTab === "deckbuilder"
              ? "bg-[#1A2234] text-[#F3E5C8] border border-[#C8AA6E]/40"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Layers className="w-3.5 h-3.5 text-[#C8AA6E]" />
          <span>Deck Builder</span>
        </button>

        <button
          onClick={() => onSelectTab("format_info")}
          className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
            activeTab === "format_info"
              ? "bg-[#1A2234] text-[#F3E5C8] border border-[#C8AA6E]/40"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
          <span>Set & Banlist</span>
        </button>

        <button
          data-tour="meta"
          onClick={() => onSelectTab("meta")}
          className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
            activeTab === "meta"
              ? "bg-[#1A2234] text-[#F3E5C8] border border-[#C8AA6E]/40"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Swords className="w-3.5 h-3.5 text-sky-400" />
          <span>Metagame</span>
        </button>

        <button
          data-tour="ai_studio"
          onClick={() => onSelectTab("ai_studio")}
          className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
            activeTab === "ai_studio"
              ? "bg-[#1A2234] text-[#F3E5C8] border border-[#C8AA6E]/40"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Sparkles className="w-3.5 h-3.5 text-purple-400" />
          <span>AI Studio</span>
        </button>

        <button
          data-tour="playtest"
          onClick={() => onSelectTab("playtest")}
          className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
            activeTab === "playtest"
              ? "bg-[#1A2234] text-[#F3E5C8] border border-[#C8AA6E]/40"
              : "text-slate-400 hover:text-slate-200"
          }`}
        >
          <Play className="w-3.5 h-3.5 text-emerald-400" />
          <span>Playtest</span>
        </button>
        <button
          data-tour="library"
          onClick={() => onSelectTab("library")}
          aria-current={activeTab === "library" ? "page" : undefined}
          className={`btn-secondary ${activeTab === "library" ? "border-amber-400 text-amber-200" : ""}`}
        >
          <Archive size={15} />
          Mazzi e guide
        </button>
      </nav>

      {/* Right: Scryfall DB Status + AI Model Selector + Settings */}
      <div className="flex items-center gap-2.5">
        <button
          className="btn-secondary"
          onClick={onOpenHelp}
          aria-label="Aiuto e percorso iniziale"
        >
          <CircleHelp size={16} />
          <span className="max-md:sr-only">Aiuto</span>
        </button>
        {/* Sync Status Pill */}
        <div
          className="flex items-center gap-2 bg-[#10141F] border border-[#1E2638] px-2.5 py-1 rounded-lg text-xs max-md:hidden"
          title={syncStatus?.scryfall_message || ""}
        >
          <Database className="w-3.5 h-3.5 text-[#C8AA6E]" />
          {isSyncing ? (
            <div className="flex items-center gap-2">
              <div className="w-24 bg-[#1B2234] h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-[#C8AA6E] h-full transition-all duration-300"
                  style={{
                    width: `${syncStatus?.scryfall_progress_pct || 5}%`,
                  }}
                />
              </div>
              <span className="font-mono-tech text-[11px] text-[#F3E5C8]">
                {syncStatus?.scryfall_progress_pct?.toFixed(0)}%
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="font-mono-tech text-[11px] text-slate-200">
                {syncStatus
                  ? `${syncStatus.total_cards_in_db.toLocaleString("it-IT")} carte`
                  : "Connessione…"}
              </span>
              <span className="text-[11px] text-slate-400 hidden xl:inline">
                ({formatLastSync(syncStatus?.scryfall_last_sync)})
              </span>
            </div>
          )}
          <button
            onClick={onTriggerSync}
            disabled={isSyncing}
            className="p-1 rounded hover:bg-[#1B2336] text-slate-300 disabled:opacity-40 cursor-pointer"
            title="Sincronizza ora catalogo Scryfall"
          >
            <RefreshCw
              className={`w-3 h-3 ${isSyncing ? "animate-spin text-[#C8AA6E]" : ""}`}
            />
          </button>
        </div>

        {/* Quick Complex AI Model Selector (from config/ai-models.json) */}
        {complexModels.length > 0 && (
          <div className="hidden lg:flex items-center gap-1.5 bg-[#10141F] border border-[#1E2638] px-2.5 py-1 rounded-lg text-xs">
            <Cpu className="w-3.5 h-3.5 text-purple-400" />
            <select
              value={settings?.selected_complex_model_id || ""}
              onChange={(e) => onChangeComplexModel(e.target.value)}
              className="bg-transparent text-slate-200 font-medium text-xs focus:outline-none cursor-pointer"
              title="Modello AI per task complessi (configurato in config/ai-models.json)"
            >
              {complexModels.map((m) => (
                <option
                  key={m.id}
                  value={m.id}
                  className="bg-[#0F131D] text-slate-200"
                >
                  {m.label}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Settings Button */}
        <button
          onClick={onOpenSettings}
          className="flex items-center gap-1.5 px-2.5 py-1.5 max-md:min-h-10 rounded-lg bg-[#141A29] hover:bg-[#1C2438] border border-[#26304A] text-xs font-medium text-slate-200 transition-colors cursor-pointer"
          title="Impostazioni: chiave Gemini, modelli AI e provider cloud"
          aria-label="Impostazioni"
        >
          <Settings className="w-3.5 h-3.5 text-[#C8AA6E]" />
          <span
            className={`w-2 h-2 rounded-full ${
              settings?.has_gemini_api_key ||
              settings?.ai_provider === "vertex-ai"
                ? "bg-emerald-400 shadow-[0_0_6px_#34d399]"
                : "bg-amber-400"
            }`}
          />
        </button>
      </div>
    </header>
  );
};
