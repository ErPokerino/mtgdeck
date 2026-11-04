import React, { useState } from "react";
import {
  Ban,
  Calendar,
  CheckCircle2,
  ExternalLink,
  Layers,
  Search,
} from "lucide-react";
import type { FormatDetail } from "../../types";
import { ManaCost, SetSymbol } from "../common/ManaCost";
import { ResizableSplitPane } from "../common/ResizableSplitPane";

interface FormatExplorerViewProps {
  formatDetail: FormatDetail | null;
  loading: boolean;
  onSelectSetForBuilder: (setCode: string) => void;
}

export const FormatExplorerView: React.FC<FormatExplorerViewProps> = ({
  formatDetail,
  loading,
  onSelectSetForBuilder,
}) => {
  const [setSearch, setSetSearch] = useState("");
  const [banSearch, setBanSearch] = useState("");

  if (loading || !formatDetail) {
    return (
      <div className="p-8 text-center text-slate-400 text-sm">
        Caricamento dettagli formato, set ammessi e banlist...
      </div>
    );
  }

  const filteredSets = formatDetail.legal_sets.filter(
    (s) =>
      s.name.toLowerCase().includes(setSearch.toLowerCase()) ||
      s.code.toLowerCase().includes(setSearch.toLowerCase()),
  );

  const filteredBans = formatDetail.banned_cards.filter((b) =>
    b.name.toLowerCase().includes(banSearch.toLowerCase()),
  );

  return (
    <div className="max-w-[1600px] mx-auto p-6 space-y-6">
      <p className="panel text-sm text-slate-300">
        La legalità delle liste è verificata per carta usando i dati Scryfall
        sincronizzati, incluse rotazione e banlist. Una ristampa resta
        utilizzabile se la carta è legale nel formato. I set qui elencati sono
        indicativi, ricavati dalle stampe del catalogo Oracle; non costituiscono
        un elenco completo delle espansioni ammesse.{" "}
        <a
          className="text-sky-300 underline"
          href="https://magic.wizards.com/en/banned-restricted-list"
          target="_blank"
          rel="noreferrer"
        >
          Banlist ufficiale Wizards
        </a>
      </p>
      {/* Format Header */}
      <div className="p-6 rounded-xl bg-gradient-to-r from-[#111624] via-[#131A2B] to-[#0E1320] border border-[#232D44] flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <h1 className="font-display font-bold text-2xl text-[#F3E5C8]">
              Formato {formatDetail.name}
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono-tech bg-emerald-950/60 text-emerald-300 border border-emerald-700/40">
              Min main / max side {formatDetail.min_mainboard}/
              {formatDetail.max_sideboard}
            </span>
          </div>
          <p className="text-xs text-slate-300 max-w-3xl">
            {formatDetail.description}
          </p>
        </div>

        <div className="flex items-center gap-4">
          <div className="px-4 py-2.5 rounded-lg bg-[#090C14] border border-[#1E2638] text-center">
            <div className="text-[11px] font-mono-tech uppercase text-slate-400">
              Set indicativi
            </div>
            <div className="text-lg font-bold font-mono-tech text-[#C8AA6E]">
              {formatDetail.legal_sets_count}
            </div>
          </div>
          <div className="px-4 py-2.5 rounded-lg bg-[#090C14] border border-[#1E2638] text-center">
            <div className="text-[11px] font-mono-tech uppercase text-slate-400">
              Carte Legali
            </div>
            <div className="text-lg font-bold font-mono-tech text-emerald-400">
              {formatDetail.legal_cards_count.toLocaleString("it-IT")}
            </div>
          </div>
          <div className="px-4 py-2.5 rounded-lg bg-[#090C14] border border-[#1E2638] text-center">
            <div className="text-[11px] font-mono-tech uppercase text-slate-400">
              Carte Bandite
            </div>
            <div className="text-lg font-bold font-mono-tech text-rose-400">
              {formatDetail.banned_cards_count}
            </div>
          </div>
        </div>
      </div>

      <ResizableSplitPane
        storageKey="format_explorer"
        defaultLeftPct={58}
        minLeftPct={30}
        maxLeftPct={75}
        left={
          <div className="bg-[#0D111A] border border-[#1E2638] rounded-xl p-5 space-y-4 h-full">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-[#C8AA6E]" />
                <h2 className="font-bold text-sm text-[#F3E5C8]">
                  Set rilevati nel catalogo di {formatDetail.name} (
                  {filteredSets.length})
                </h2>
              </div>
              <div className="relative w-60">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={setSearch}
                  onChange={(e) => setSetSearch(e.target.value)}
                  placeholder="Cerca set o codice (es. DSK, MH3)..."
                  className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-[#080B11] border border-[#222B40] text-xs text-white focus:outline-none focus:border-[#C8AA6E]"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-[620px] overflow-y-auto pr-1">
              {filteredSets.map((s) => (
                <div
                  key={s.code}
                  onClick={() => onSelectSetForBuilder(s.code)}
                  className="p-3 rounded-lg bg-[#111623] hover:bg-[#171F32] border border-[#1E273C] hover:border-[#C8AA6E]/50 transition-all flex items-center justify-between gap-3 cursor-pointer group"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-8 h-8 rounded-lg bg-[#0A0D15] border border-[#20293E] flex items-center justify-center shrink-0">
                      <SetSymbol
                        setCode={s.code}
                        rarity="rare"
                        className="text-base"
                      />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-xs text-slate-100 truncate group-hover:text-[#F3E5C8]">
                          {s.name}
                        </span>
                        <span className="font-mono-tech text-[11px] uppercase px-1.5 py-0.2 rounded bg-[#090C12] text-[#C8AA6E] border border-[#26314A]">
                          {s.code}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-slate-400 mt-0.5">
                        <span className="flex items-center gap-1">
                          <Calendar className="w-3 h-3" />{" "}
                          {s.released_at || "N/D"}
                        </span>
                        <span>•</span>
                        <span className="font-mono-tech">
                          {s.card_count} carte
                        </span>
                      </div>
                    </div>
                  </div>
                  <ExternalLink className="w-3.5 h-3.5 text-slate-400 group-hover:text-[#C8AA6E] shrink-0" />
                </div>
              ))}
            </div>
          </div>
        }
        right={
          <div className="bg-[#0D111A] border border-[#1E2638] rounded-xl p-5 space-y-4 h-full">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Ban className="w-4 h-4 text-rose-400" />
                <h2 className="font-bold text-sm text-rose-200">
                  Banlist Ufficiale {formatDetail.name} ({filteredBans.length})
                </h2>
              </div>
              <div className="relative w-48">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={banSearch}
                  onChange={(e) => setBanSearch(e.target.value)}
                  placeholder="Filtra carta bandita..."
                  className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-[#080B11] border border-[#222B40] text-xs text-white focus:outline-none focus:border-rose-500"
                />
              </div>
            </div>

            {filteredBans.length === 0 ? (
              <div className="p-8 text-center text-xs text-slate-400">
                <CheckCircle2 className="w-6 h-6 text-emerald-400 mx-auto mb-2" />
                Nessuna carta bandita corrispondente al filtro.
              </div>
            ) : (
              <div className="space-y-2 max-h-[620px] overflow-y-auto pr-1">
                {filteredBans.map((b) => (
                  <div
                    key={b.oracle_id}
                    className="p-2.5 rounded-lg bg-[#13111C] border border-rose-900/40 flex items-center justify-between gap-3"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      {b.image_uris?.small && (
                        <img
                          src={b.image_uris.small}
                          alt={b.name}
                          className="w-9 h-12 rounded object-cover border border-rose-800/40 shrink-0"
                        />
                      )}
                      <div className="min-w-0">
                        <div className="font-semibold text-xs text-rose-100 truncate">
                          {b.name}
                        </div>
                        <div className="text-[11px] text-slate-400 truncate">
                          {b.type_line}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <ManaCost cost={b.mana_cost} size="xs" />
                      <span className="text-[11px] font-mono-tech uppercase px-1.5 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-700/40">
                        BANNED
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        }
      />
    </div>
  );
};
