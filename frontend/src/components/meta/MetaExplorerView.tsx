import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Award,
  BarChart3,
  Clock,
  Filter,
  FolderPlus,
  Grid,
  RefreshCw,
  RotateCcw,
  Search,
  Swords,
  TrendingUp,
} from "lucide-react";
import { api } from "../../api/client";
import type {
  ArchetypeDetail,
  Card,
  DeckDetail,
  FormatId,
  FormatMetaResponse,
  MetaArchetypeInfo,
} from "../../types";
import { CardInfoModal } from "../common/CardInfoModal";
import { ColorBadges, ManaCost } from "../common/ManaCost";
import { ResizableSplitPane } from "../common/ResizableSplitPane";
import { archetypeUsageLabel } from "../common/metaLabels";

interface MetaExplorerViewProps {
  formatId: FormatId;
  onLoadDeckToBuilder: (deck: DeckDetail) => void;
  onOpenMatchupSpotWithArchetype?: (arch: MetaArchetypeInfo) => void;
  onBuildFromArchetype?: (arch: MetaArchetypeInfo) => void;
}

export const MetaExplorerView: React.FC<MetaExplorerViewProps> = ({
  formatId,
  onLoadDeckToBuilder,
  onOpenMatchupSpotWithArchetype,
  onBuildFromArchetype,
}) => {
  const [metaData, setMetaData] = useState<FormatMetaResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [subTab, setSubTab] = useState<"archetypes" | "matrix" | "top_cards">(
    "archetypes",
  );
  const [inspectedCard, setInspectedCard] = useState<Card | null>(null);
  const [loadingArchetypeId, setLoadingArchetypeId] = useState<number | null>(
    null,
  );
  const [selectedArchetypeId, setSelectedArchetypeId] = useState<number | null>(
    null,
  );

  // Filters for "Carte Più Giocate"
  const [cardSearchQuery, setCardSearchQuery] = useState("");
  const [selectedColors, setSelectedColors] = useState<string[]>([]);
  const [selectedType, setSelectedType] = useState<string>("all");
  const [selectedBoard, setSelectedBoard] = useState<"all" | "main" | "side">(
    "all",
  );
  const [selectedRarity, setSelectedRarity] = useState<string>("all");
  const [selectedArchetypeFilter, setSelectedArchetypeFilter] =
    useState<string>("all");
  const [sortBy, setSortBy] = useState<
    | "overall_desc"
    | "main_desc"
    | "side_desc"
    | "copies_desc"
    | "cmc_asc"
    | "name_asc"
  >("overall_desc");

  const fetchMeta = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getFormatMeta(formatId);
      setMetaData(res);
      if (res.archetypes && res.archetypes.length > 0) {
        setSelectedArchetypeId(res.archetypes[0].id);
      }
    } catch (err) {
      console.error("Error loading meta:", err);
    } finally {
      setLoading(false);
    }
  }, [formatId]);

  useEffect(() => {
    fetchMeta();
  }, [fetchMeta]);

  const handleSyncMetaNow = async () => {
    setSyncing(true);
    try {
      await api.triggerMetaSync(formatId);
      await fetchMeta();
    } finally {
      setSyncing(false);
    }
  };

  const [loadError, setLoadError] = useState("");
  const handleLoadSampleDeck = async (
    arch: MetaArchetypeInfo,
    decklistId?: number,
  ) => {
    setLoadingArchetypeId(arch.id);
    setLoadError("");
    try {
      const deck = await api.loadArchetypeSampleDeck(
        formatId,
        arch.id,
        decklistId,
      );
      onLoadDeckToBuilder(deck);
    } catch (err: any) {
      setLoadError(err.message);
    } finally {
      setLoadingArchetypeId(null);
    }
  };

  const [archDetail, setArchDetail] = useState<ArchetypeDetail | null>(null);
  useEffect(() => {
    setArchDetail(null);
    if (selectedArchetypeId == null) return;
    let cancelled = false;
    api
      .getArchetypeDetail(formatId, selectedArchetypeId)
      .then((d) => {
        if (!cancelled) setArchDetail(d);
      })
      .catch(() => {
        /* older snapshots have no per-archetype statistics */
      });
    return () => {
      cancelled = true;
    };
  }, [formatId, selectedArchetypeId]);

  const archetypes = metaData?.archetypes || [];
  const matrix = metaData?.matchup_matrix || {};
  const topCards = metaData?.top_cards || [];

  const handleInspectCardByName = async (rawName: string) => {
    const clean = rawName.trim().toLowerCase();
    const fromTop = topCards.find(
      (tc) =>
        tc.card &&
        (tc.card_name.toLowerCase() === clean ||
          tc.card_name.toLowerCase().split(" // ")[0] ===
            clean.split(" // ")[0]),
    );
    if (fromTop?.card) {
      setInspectedCard(fromTop.card);
      return;
    }
    try {
      const res = await api.searchCards({
        format_id: formatId,
        q: rawName.trim(),
        page_size: 4,
      });
      if (res.cards.length > 0) {
        setInspectedCard(res.cards[0]);
      }
    } catch {
      // ignore
    }
  };

  const toggleColorFilter = (c: string) => {
    setSelectedColors((prev) =>
      prev.includes(c) ? prev.filter((item) => item !== c) : [...prev, c],
    );
  };

  const resetCardFilters = () => {
    setCardSearchQuery("");
    setSelectedColors([]);
    setSelectedType("all");
    setSelectedBoard("all");
    setSelectedRarity("all");
    setSelectedArchetypeFilter("all");
    setSortBy("overall_desc");
  };

  const filteredTopCards = useMemo(() => {
    const q = cardSearchQuery.trim().toLowerCase();
    const list = topCards.filter((tc) => {
      // 1. Search by card name or Oracle text
      if (q) {
        const nameMatch = tc.card_name.toLowerCase().includes(q);
        const oracleMatch = (tc.card?.oracle_text || "")
          .toLowerCase()
          .includes(q);
        const typeMatch = (tc.card?.type_line || "").toLowerCase().includes(q);
        if (!nameMatch && !oracleMatch && !typeMatch) return false;
      }

      // 2. Board filter
      if (selectedBoard === "main" && tc.main_presence_pct <= 0) return false;
      if (selectedBoard === "side" && tc.side_presence_pct <= 0) return false;

      // 3. Card Type filter
      if (selectedType !== "all") {
        const tl = (tc.card?.type_line || "").toLowerCase();
        if (!tl.includes(selectedType.toLowerCase())) return false;
      }

      // 4. Rarity filter
      if (selectedRarity !== "all") {
        const r = (tc.card?.rarity || "").toLowerCase();
        if (r !== selectedRarity.toLowerCase()) return false;
      }

      // 5. Color filter
      if (selectedColors.length > 0) {
        const cardCols = tc.card?.colors?.length
          ? tc.card.colors
          : tc.card?.color_identity || [];
        const wantsColorless = selectedColors.includes("C");
        const activeManaCols = selectedColors.filter((c) => c !== "C");
        if (wantsColorless && activeManaCols.length === 0) {
          if (cardCols.length > 0) return false;
        } else {
          const matchesMana = activeManaCols.every((c) => cardCols.includes(c));
          const matchesColorless = wantsColorless && cardCols.length === 0;
          if (!matchesMana && !matchesColorless) return false;
        }
      }

      // 6. Archetype filter
      if (selectedArchetypeFilter !== "all") {
        const usedBy = (tc.top_archetypes || []).some(
          (a) =>
            a.archetype.toLowerCase() === selectedArchetypeFilter.toLowerCase(),
        );
        if (!usedBy) return false;
      }

      return true;
    });

    list.sort((a, b) => {
      if (sortBy === "main_desc")
        return b.main_presence_pct - a.main_presence_pct;
      if (sortBy === "side_desc")
        return b.side_presence_pct - a.side_presence_pct;
      if (sortBy === "copies_desc") {
        const ca = Math.max(a.main_avg_copies, a.side_avg_copies);
        const cb = Math.max(b.main_avg_copies, b.side_avg_copies);
        return cb - ca || b.overall_presence_pct - a.overall_presence_pct;
      }
      if (sortBy === "cmc_asc") {
        return (
          (a.card?.cmc ?? 99) - (b.card?.cmc ?? 99) ||
          b.overall_presence_pct - a.overall_presence_pct
        );
      }
      if (sortBy === "name_asc") return a.card_name.localeCompare(b.card_name);
      return b.overall_presence_pct - a.overall_presence_pct;
    });

    return list;
  }, [
    topCards,
    cardSearchQuery,
    selectedBoard,
    selectedType,
    selectedRarity,
    selectedColors,
    selectedArchetypeFilter,
    sortBy,
  ]);

  if (loading && !metaData) {
    return (
      <div className="p-12 text-center text-sm text-slate-400" role="status">
        Caricamento del metagame {formatId.toUpperCase()}…
      </div>
    );
  }

  return (
    <div className="max-w-[1600px] mx-auto p-6 space-y-6">
      {/* Meta Telemetry Header */}
      <div className="p-5 rounded-xl bg-gradient-to-r from-[#101624] via-[#131C2E] to-[#0E131F] border border-[#24304A] flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <Swords className="w-5 h-5 text-[#C8AA6E]" />
            <h1 className="font-display font-bold text-xl text-[#F3E5C8]">
              Metagame & Matchup Matrix — {formatId.toUpperCase()}
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-mono-tech bg-sky-950/70 text-sky-300 border border-sky-700/40">
              {metaData?.snapshot.source || "Nessuno snapshot"}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
            <span className="flex items-center gap-1">
              <Clock className="w-3.5 h-3.5 text-[#C8AA6E]" />
              Aggiornato:{" "}
              <strong className="text-slate-200 font-mono-tech">
                {metaData?.snapshot.fetched_at
                  ? new Date(metaData.snapshot.fetched_at).toLocaleString(
                      "it-IT",
                    )
                  : "N/D"}
              </strong>
            </span>
            <span>
              Mazzi nel periodo:{" "}
              <strong className="text-[#C8AA6E] font-mono-tech">
                {(metaData?.snapshot.total_decks_analyzed || 0).toLocaleString(
                  "it-IT",
                )}
              </strong>
            </span>
            {metaData?.snapshot.decklists_count != null && (
              <span>
                Liste analizzate:{" "}
                <strong className="text-[#C8AA6E] font-mono-tech">
                  {metaData.snapshot.decklists_count}
                </strong>
              </span>
            )}
            {metaData?.snapshot.coverage_pct != null && (
              <span title="Quota del meta coperta da archetipi con liste sufficienti per le statistiche">
                Copertura:{" "}
                <strong className="text-[#C8AA6E] font-mono-tech">
                  {metaData.snapshot.coverage_pct.toFixed(0)}%
                </strong>
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Sub-Navigation Pills */}
          <div className="flex items-center bg-[#080A10] p-1 rounded-lg border border-[#1E2638]">
            <button
              onClick={() => setSubTab("archetypes")}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold flex items-center gap-1.5 cursor-pointer ${
                subTab === "archetypes"
                  ? "bg-[#C8AA6E] text-[#090B10]"
                  : "text-slate-300 hover:text-white"
              }`}
            >
              <Award className="w-3.5 h-3.5" />
              <span>Archetipi Top ({archetypes.length})</span>
            </button>
            <button
              onClick={() => setSubTab("matrix")}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold flex items-center gap-1.5 cursor-pointer ${
                subTab === "matrix"
                  ? "bg-[#C8AA6E] text-[#090B10]"
                  : "text-slate-300 hover:text-white"
              }`}
            >
              <Grid className="w-3.5 h-3.5" />
              <span>Matrice dei matchup</span>
            </button>
            <button
              onClick={() => setSubTab("top_cards")}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold flex items-center gap-1.5 cursor-pointer ${
                subTab === "top_cards"
                  ? "bg-[#C8AA6E] text-[#090B10]"
                  : "text-slate-300 hover:text-white"
              }`}
            >
              <BarChart3 className="w-3.5 h-3.5" />
              <span>Carte più giocate ({topCards.length})</span>
            </button>
          </div>

          <button
            onClick={handleSyncMetaNow}
            disabled={syncing}
            className="px-3.5 py-2 rounded-lg bg-[#161E31] hover:bg-[#1E2942] border border-[#2C3A5E] text-xs font-medium text-slate-200 flex items-center gap-1.5 disabled:opacity-40 cursor-pointer"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${syncing ? "animate-spin text-[#C8AA6E]" : ""}`}
            />
            <span>
              {syncing ? "Aggiornamento (qualche minuto)…" : "Aggiorna meta"}
            </span>
          </button>
        </div>
      </div>

      {(metaData?.snapshot.quality_warnings?.length ?? 0) > 0 && (
        <details
          className={`rounded-xl border p-4 text-sm ${
            metaData?.snapshot.quality_status === "degraded"
              ? "bg-amber-950/30 border-amber-700/50 text-amber-100"
              : "bg-[#0D111A] border-[#1E2638] text-slate-300"
          }`}
          open={metaData?.snapshot.quality_status === "degraded"}
        >
          <summary className="cursor-pointer font-semibold">
            {metaData?.snapshot.quality_status === "degraded"
              ? "Dati del metagame parziali: usali con cautela"
              : `Note sulla qualità dei dati (${metaData?.snapshot.quality_warnings?.length})`}
          </summary>
          <ul className="mt-2 space-y-1 text-xs list-disc pl-5">
            {metaData?.snapshot.quality_warnings?.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}

      {/* =====================================================================
          SUB-TAB 1: TOP ARCHETYPES & TIER LIST
         ===================================================================== */}
      {subTab === "archetypes" && (
        <ResizableSplitPane
          storageKey="meta_explorer_split"
          defaultLeftPct={64}
          minLeftPct={35}
          maxLeftPct={78}
          left={
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {archetypes.map((arch) => {
                const hasSample =
                  arch.sample_decklists && arch.sample_decklists.length > 0;
                const isSelected = selectedArchetypeId === arch.id;
                return (
                  <div
                    key={arch.id}
                    onClick={() => setSelectedArchetypeId(arch.id)}
                    className={`rounded-xl bg-[#0D111A] border transition-all p-5 flex flex-col justify-between gap-4 shadow-lg cursor-pointer ${
                      isSelected
                        ? "border-[#C8AA6E] ring-1 ring-[#C8AA6E]/60"
                        : "border-[#1E2638] hover:border-[#C8AA6E]/50"
                    }`}
                  >
                    <div className="space-y-3">
                      {/* Top Row: Tier Badge + Name + Colors */}
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span
                              className={`px-2 py-0.5 rounded text-[11px] font-mono-tech font-bold uppercase ${
                                arch.tier === 1
                                  ? "bg-[#C8AA6E]/20 text-[#F3E5C8] border border-[#C8AA6E]/50"
                                  : "bg-slate-800 text-slate-300 border border-slate-700"
                              }`}
                            >
                              Tier {arch.tier}
                            </span>
                            <span className="text-[11px] font-mono-tech uppercase text-slate-400">
                              {arch.category}
                            </span>
                          </div>
                          <h3 className="font-bold text-base text-white mt-1">
                            {arch.name}
                          </h3>
                        </div>

                        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#131928] border border-[#232E47]">
                          <ColorBadges colors={arch.colors} size="sm" />
                          <span className="text-[11px] font-medium text-slate-300">
                            {arch.color_name}
                          </span>
                        </div>
                      </div>

                      {/* Stats Row: Meta Share, Winrate, Decks/Matches */}
                      <div className="grid grid-cols-3 gap-2 pt-1">
                        <div className="p-2.5 rounded-lg bg-[#090C12] border border-[#192132]">
                          <div className="text-[11px] text-slate-400">
                            Quota meta
                          </div>
                          <div className="text-base font-bold font-mono-tech text-[#F3E5C8]">
                            {arch.meta_share_pct.toFixed(1)}%
                          </div>
                        </div>
                        <div
                          className="p-2.5 rounded-lg bg-[#090C12] border border-[#192132]"
                          title={
                            arch.winrate_pct == null
                              ? "La fonte non pubblica winrate"
                              : undefined
                          }
                        >
                          <div className="text-[11px] text-slate-400">
                            Winrate
                          </div>
                          {arch.winrate_pct == null ? (
                            <div className="text-base font-bold font-mono-tech text-slate-400">
                              n/d
                            </div>
                          ) : (
                            <div
                              className={`text-base font-bold font-mono-tech ${
                                arch.winrate_pct >= 53
                                  ? "text-emerald-400"
                                  : arch.winrate_pct >= 50
                                    ? "text-sky-400"
                                    : "text-amber-400"
                              }`}
                            >
                              {arch.winrate_pct.toFixed(0)}%
                            </div>
                          )}
                        </div>
                        <div className="p-2.5 rounded-lg bg-[#090C12] border border-[#192132]">
                          <div className="text-[11px] text-slate-400">
                            Liste analizzate
                          </div>
                          <div className="text-sm font-bold font-mono-tech text-slate-200">
                            {arch.decklists_count ??
                              arch.sample_decklists?.length ??
                              0}
                          </div>
                        </div>
                      </div>

                      {/* Key Cards with Scryfall Previews */}
                      <div
                        className="space-y-1.5"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="text-[11px] font-semibold text-slate-400">
                          Carte chiave dell&apos;archetipo:
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {arch.key_cards.map((kc, idx) => (
                            <button
                              key={idx}
                              type="button"
                              onClick={() =>
                                kc.card && setInspectedCard(kc.card)
                              }
                              className="px-2 py-1 rounded-md bg-[#121826] hover:bg-[#1B2438] border border-[#222C42] text-xs text-slate-200 flex items-center gap-1.5 cursor-pointer"
                            >
                              {kc.image_small && (
                                <img
                                  src={kc.image_small}
                                  alt=""
                                  className="w-4 h-5 rounded-xs object-cover"
                                />
                              )}
                              <span className="truncate max-w-[140px]">
                                {kc.name}
                              </span>
                              {kc.mana_cost && (
                                <ManaCost cost={kc.mana_cost} size="xs" />
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>

                    {/* Actions Footer */}
                    <div
                      className="pt-3 border-t border-[#1A2234] flex items-center gap-2"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {hasSample && (
                        <button
                          type="button"
                          disabled={loadingArchetypeId === arch.id}
                          onClick={() => handleLoadSampleDeck(arch)}
                          className="flex-1 py-2 px-3 rounded-lg bg-[#C8AA6E] hover:bg-[#DFC286] text-[#090B10] font-bold text-xs flex items-center justify-center gap-1.5 cursor-pointer"
                        >
                          <FolderPlus className="w-3.5 h-3.5" />
                          <span>
                            {loadingArchetypeId === arch.id
                              ? "Caricamento…"
                              : "Apri la lista più recente nel builder"}
                          </span>
                        </button>
                      )}
                      {onOpenMatchupSpotWithArchetype && (
                        <button
                          type="button"
                          onClick={() => onOpenMatchupSpotWithArchetype(arch)}
                          className="py-2 px-3 rounded-lg bg-[#151D2E] hover:bg-[#1E2942] border border-[#2A3958] text-xs font-medium text-sky-300 flex items-center gap-1 cursor-pointer"
                          title="Analizza il matchup contro questo archetipo con l'AI"
                        >
                          <TrendingUp className="w-3.5 h-3.5" />
                          <span>Analisi matchup AI</span>
                        </button>
                      )}
                      {onBuildFromArchetype && (
                        <button
                          type="button"
                          onClick={() => onBuildFromArchetype(arch)}
                          className="py-2 px-3 rounded-lg bg-[#151D2E] hover:bg-[#1E2942] border border-[#C8AA6E]/40 text-xs font-medium text-[#F3E5C8] flex items-center gap-1 cursor-pointer"
                          title="Genera una lista ottimizzata partendo dal consenso di questo archetipo"
                        >
                          <TrendingUp className="w-3.5 h-3.5" />
                          <span>Costruisci da questo archetipo</span>
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          }
          right={(() => {
            const selectedArch =
              archetypes.find((a) => a.id === selectedArchetypeId) ||
              archetypes[0];
            if (!selectedArch) return null;
            const sample = selectedArch.sample_decklists?.[0];
            const archMatchups = matrix[selectedArch.name] || {};
            return (
              <div className="rounded-xl bg-[#0D111A] border border-[#1E2638] p-5 space-y-4 sticky top-4">
                <div className="flex items-start justify-between gap-2 border-b border-[#1E2638] pb-3">
                  <div>
                    <span className="text-[11px] font-mono-tech uppercase text-[#C8AA6E]">
                      Ispezione Archetipo Live • Tier {selectedArch.tier}
                    </span>
                    <h3 className="font-display font-bold text-lg text-[#F3E5C8]">
                      {selectedArch.name}
                    </h3>
                    {sample && (
                      <p className="text-xs text-slate-400">
                        {sample.event} — Pilota:{" "}
                        <strong className="text-slate-200">
                          {sample.pilot}
                        </strong>
                      </p>
                    )}
                  </div>
                  <ColorBadges colors={selectedArch.colors} size="sm" />
                </div>

                {loadError && (
                  <p className="notice-error text-xs" role="alert">
                    {loadError}
                  </p>
                )}

                {archDetail && archDetail.id === selectedArch.id && (
                  <>
                    <div className="space-y-1.5">
                      <div className="text-xs font-bold uppercase text-[#C8AA6E]">
                        Carte osservate in {archDetail.decklists_count} liste
                      </div>
                      <p className="text-[11px] text-slate-400">
                        % delle liste che giocano la carta e copie medie in
                        quelle liste. Le carte sotto il 100% sono gli slot
                        flessibili dell&apos;archetipo.
                      </p>
                      <div className="max-h-64 overflow-y-auto rounded-lg border border-[#1B2336]">
                        <table className="w-full text-[11px]">
                          <thead className="sticky top-0 bg-[#0D111A]">
                            <tr className="text-slate-400 text-left">
                              <th className="px-2 py-1.5 font-medium">Carta</th>
                              <th className="px-2 py-1.5 font-medium text-right">
                                Main
                              </th>
                              <th className="px-2 py-1.5 font-medium text-right">
                                Side
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {archDetail.cards.map((c) => (
                              <tr
                                key={c.oracle_id}
                                className="border-t border-[#161D2C]"
                              >
                                <td className="px-2 py-1">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleInspectCardByName(c.card_name)
                                    }
                                    className="text-left text-slate-100 hover:text-[#F3E5C8] cursor-pointer"
                                  >
                                    {c.card_name}
                                  </button>
                                </td>
                                <td className="px-2 py-1 text-right font-mono-tech text-slate-200">
                                  {c.main_inclusion_pct
                                    ? `${Math.round(c.main_inclusion_pct)}% · ${c.main_avg_copies}x`
                                    : "—"}
                                </td>
                                <td className="px-2 py-1 text-right font-mono-tech text-sky-300">
                                  {c.side_inclusion_pct
                                    ? `${Math.round(c.side_inclusion_pct)}% · ${c.side_avg_copies}x`
                                    : "—"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {archDetail.decklists.length > 0 && (
                      <div className="space-y-1.5">
                        <div className="text-xs font-bold uppercase text-[#C8AA6E]">
                          Liste analizzate
                        </div>
                        <ul className="space-y-1 max-h-48 overflow-y-auto">
                          {archDetail.decklists.map((d) => (
                            <li
                              key={d.id}
                              className="flex items-center justify-between gap-2 px-2 py-1.5 rounded bg-[#090C12] border border-[#1B2336] text-[11px]"
                            >
                              <span className="min-w-0">
                                <span className="text-slate-100">
                                  {d.pilot || "Pilota n/d"}
                                </span>
                                <span className="block text-slate-400 truncate">
                                  {d.event}
                                  {d.placement ? ` · #${d.placement}` : ""}
                                  {d.played_on
                                    ? ` · ${new Date(d.played_on).toLocaleDateString("it-IT")}`
                                    : ""}
                                </span>
                              </span>
                              <button
                                type="button"
                                disabled={
                                  loadingArchetypeId === selectedArch.id
                                }
                                onClick={() =>
                                  handleLoadSampleDeck(selectedArch, d.id)
                                }
                                className="shrink-0 px-2 py-1 rounded bg-[#161E31] hover:bg-[#1E2942] border border-[#2C3A5E] text-[#F3E5C8] cursor-pointer disabled:opacity-40"
                                aria-label={`Apri nel builder la lista di ${d.pilot || "pilota sconosciuto"}`}
                              >
                                Apri
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}

                {/* Older snapshots only: heuristic estimates, never observed results */}
                {Object.keys(archMatchups).length > 0 && (
                  <div className="space-y-1.5">
                    <div className="text-xs font-bold uppercase text-sky-300">
                      Stime euristiche (non risultati osservati)
                    </div>
                    <div className="grid grid-cols-2 gap-1.5 max-h-40 overflow-y-auto pr-1">
                      {Object.entries(archMatchups)
                        .filter(([opp]) => opp !== selectedArch.name)
                        .slice(0, 6)
                        .map(([opp, data]) => (
                          <div
                            key={opp}
                            className="px-2.5 py-1.5 rounded bg-[#090C12] border border-[#1B2336] flex items-center justify-between text-xs"
                          >
                            <span className="truncate text-slate-300 mr-1">
                              vs {opp}
                            </span>
                            <span
                              className={`font-mono-tech font-bold ${
                                data.winrate_pct >= 52
                                  ? "text-emerald-400"
                                  : data.winrate_pct <= 48
                                    ? "text-rose-400"
                                    : "text-slate-200"
                              }`}
                            >
                              {data.winrate_pct.toFixed(0)}%
                            </span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                {/* Sample Tournament Decklist */}
                {sample?.decklist_text && (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold uppercase text-[#C8AA6E]">
                        Lista da torneo (60 main + 15 side) · clicca una carta per i dettagli
                      </span>
                      <button
                        type="button"
                        onClick={() => handleLoadSampleDeck(selectedArch)}
                        className="text-[11px] font-bold text-[#C8AA6E] hover:underline cursor-pointer"
                      >
                        Carica nel Deck Builder →
                      </button>
                    </div>
                    <div className="p-2.5 rounded-lg bg-[#080A10] border border-[#1B2336] font-mono-tech text-[11px] text-slate-200 max-h-[380px] overflow-y-auto space-y-0.5">
                      {sample.decklist_text.split("\n").map((line, lIdx) => {
                        const trimmed = line.trim();
                        if (!trimmed)
                          return <div key={lIdx} className="h-1.5" />;
                        if (/^(deck|sideboard)$/i.test(trimmed)) {
                          return (
                            <div
                              key={lIdx}
                              className="pt-1.5 pb-0.5 text-[11px] font-bold uppercase tracking-wider text-sky-400 border-b border-[#182032]"
                            >
                              {trimmed === "Deck"
                                ? "MAINBOARD (60)"
                                : "SIDEBOARD (15)"}
                            </div>
                          );
                        }
                        const m = trimmed.match(/^(\d+)x?\s+(.+)$/);
                        if (!m) {
                          return (
                            <div key={lIdx} className="text-slate-400">
                              {trimmed}
                            </div>
                          );
                        }
                        const qty = m[1];
                        const cName = m[2];
                        return (
                          <button
                            key={lIdx}
                            type="button"
                            onClick={() => handleInspectCardByName(cName)}
                            className="w-full px-1.5 py-0.5 rounded hover:bg-[#151E30] flex items-center justify-between text-left transition-colors cursor-pointer group"
                            title="Clicca per ispezionare carta e statistiche Meta"
                          >
                            <span className="truncate">
                              <strong className="text-[#C8AA6E] mr-1.5">
                                {qty}x
                              </strong>
                              <span className="text-slate-100 group-hover:text-[#F3E5C8]">
                                {cName}
                              </span>
                            </span>
                            <span className="text-[11px] text-slate-400 group-hover:text-sky-300 opacity-0 group-hover:opacity-100">
                              Info →
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        />
      )}

      {/* =====================================================================
          SUB-TAB 2: MATCHUP MATRIX (older snapshots: heuristic estimates)
         ===================================================================== */}
      {subTab === "matrix" && Object.keys(matrix).length === 0 && (
        <div className="bg-[#0D111A] border border-[#1E2638] rounded-xl p-8 text-center space-y-2">
          <h2 className="font-bold text-sm text-[#F3E5C8]">
            Nessun dato testa a testa disponibile
          </h2>
          <p className="text-sm text-slate-400 max-w-2xl mx-auto">
            La fonte del metagame pubblica quote e liste, non i risultati dei
            singoli matchup. Per studiare uno scontro usa{" "}
            <strong className="text-slate-200">Analisi matchup AI</strong> da
            una scheda archetipo: confronta le liste reali dei due mazzi.
          </p>
        </div>
      )}
      {subTab === "matrix" && Object.keys(matrix).length > 0 && (
        <div className="bg-[#0D111A] border border-[#1E2638] rounded-xl p-5 space-y-4 overflow-x-auto">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-bold text-sm text-[#F3E5C8]">
                Matrice teorica dei matchup ({formatId.toUpperCase()})
              </h2>
              <p className="text-xs text-slate-400">
                Stime euristiche da categorie e statistiche generali, senza
                partite testa a testa osservate. Non sono risultati di torneo.
                Lettura per riga: percentuale di vittoria dell&apos;archetipo
                sulla riga (sinistra) contro l&apos;archetipo sulla colonna (in
                alto).
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs font-mono-tech">
              <span className="px-2 py-0.5 rounded bg-emerald-950/70 text-emerald-300 border border-emerald-700/40">
                &gt;52% Favorevole
              </span>
              <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                48–52% Equilibrato
              </span>
              <span className="px-2 py-0.5 rounded bg-rose-950/70 text-rose-300 border border-rose-700/40">
                &lt;48% Sfavorevole
              </span>
            </div>
          </div>

          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th className="p-3 text-left bg-[#090C12] border border-[#1E2638] text-slate-400 font-mono-tech uppercase text-[11px]">
                  Pilota (Riga) \ Avversario (Col)
                </th>
                {archetypes.map((colArch) => (
                  <th
                    key={colArch.id}
                    className="p-3 text-center bg-[#090C12] border border-[#1E2638] text-slate-200 font-semibold min-w-[125px]"
                  >
                    <div className="flex flex-col items-center gap-1">
                      <ColorBadges colors={colArch.colors} size="sm" />
                      <span>{colArch.name}</span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {archetypes.map((rowArch) => (
                <tr key={rowArch.id}>
                  <td className="p-3 bg-[#090C12] border border-[#1E2638] font-semibold text-slate-100">
                    <div className="flex items-center gap-2">
                      <ColorBadges colors={rowArch.colors} size="sm" />
                      <span>{rowArch.name}</span>
                      <span className="ml-auto text-[11px] font-mono-tech text-[#C8AA6E]">
                        {rowArch.meta_share_pct.toFixed(1)}%
                      </span>
                    </div>
                  </td>
                  {archetypes.map((colArch) => {
                    if (rowArch.name === colArch.name) {
                      return (
                        <td
                          key={colArch.id}
                          className="p-3 text-center border border-[#1E2638] bg-[#080A0F] text-slate-400 font-mono-tech"
                        >
                          MIRROR (50%)
                        </td>
                      );
                    }
                    const cell = matrix[rowArch.name]?.[colArch.name];
                    const wr = cell?.winrate_pct;
                    const matches = cell?.matches_count || 0;

                    if (wr === undefined) {
                      return (
                        <td
                          key={colArch.id}
                          className="p-3 text-center border border-[#1E2638] text-slate-400 font-mono-tech"
                        >
                          —
                        </td>
                      );
                    }

                    const cellColor =
                      wr >= 55
                        ? "bg-emerald-950/65 text-emerald-300 font-bold"
                        : wr >= 52
                          ? "bg-emerald-950/35 text-emerald-200"
                          : wr <= 45
                            ? "bg-rose-950/65 text-rose-300 font-bold"
                            : wr <= 48
                              ? "bg-rose-950/35 text-rose-200"
                              : "bg-[#121724] text-slate-200";

                    return (
                      <td
                        key={colArch.id}
                        className={`p-3 text-center border border-[#1E2638] font-mono-tech ${cellColor}`}
                      >
                        <div className="text-sm">{wr.toFixed(1)}%</div>
                        <div className="text-[11px] opacity-70">
                          {matches
                            ? `${matches} match osservati`
                            : "Stima · nessun campione"}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* =====================================================================
          SUB-TAB 3: TOP PLAYED CARDS (MTGTop8 Staples — FULL POOL + FILTERS)
         ===================================================================== */}
      {subTab === "top_cards" && (
        <div className="bg-[#0D111A] border border-[#1E2638] rounded-xl overflow-hidden">
          <div className="p-4 bg-[#111726] border-b border-[#1E2638] space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-bold text-sm text-[#F3E5C8] flex items-center gap-2">
                  <span>Carte più giocate in {formatId.toUpperCase()}</span>
                  <span className="px-2 py-0.5 rounded bg-[#C8AA6E]/20 border border-[#C8AA6E]/40 text-[#F3E5C8] text-[11px] font-mono-tech">
                    {filteredTopCards.length} / {topCards.length} carte
                  </span>
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Presenza calcolata sulle liste raccolte, ponderata per la
                  quota di ogni archetipo con liste sufficienti. Filtra per
                  colore, tipo, board, rarità o archetipo.
                </p>
              </div>

              <button
                type="button"
                onClick={resetCardFilters}
                className="px-3 py-1.5 rounded-lg bg-[#090C12] hover:bg-[#161F33] border border-[#232E47] text-xs font-medium text-slate-300 flex items-center gap-1.5 cursor-pointer"
              >
                <RotateCcw className="w-3.5 h-3.5 text-[#C8AA6E]" />
                <span>Azzera filtri</span>
              </button>
            </div>

            {/* Filter & Search Bar */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-2.5 pt-1">
              {/* 1. Search by Name / Oracle Text */}
              <div className="lg:col-span-2 relative">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={cardSearchQuery}
                  onChange={(e) => setCardSearchQuery(e.target.value)}
                  placeholder="Cerca per nome carta, tipo o testo Oracle..."
                  className="w-full pl-8 pr-3 py-2 rounded-lg bg-[#080A10] border border-[#222C42] focus:border-[#C8AA6E] text-xs text-slate-100 outline-none"
                />
              </div>

              {/* 2. Card Type Filter */}
              <div>
                <select
                  value={selectedType}
                  onChange={(e) => setSelectedType(e.target.value)}
                  className="w-full px-2.5 py-2 rounded-lg bg-[#080A10] border border-[#222C42] text-xs text-slate-200 cursor-pointer"
                >
                  <option value="all">Tutti i tipi</option>
                  <option value="Creature">Creature</option>
                  <option value="Instant">Instant</option>
                  <option value="Sorcery">Sorcery</option>
                  <option value="Land">Land (Terre)</option>
                  <option value="Artifact">Artifact</option>
                  <option value="Enchantment">Enchantment</option>
                  <option value="Planeswalker">Planeswalker</option>
                </select>
              </div>

              {/* 3. Board Filter (Mainboard vs Sideboard) */}
              <div>
                <select
                  value={selectedBoard}
                  onChange={(e) =>
                    setSelectedBoard(e.target.value as "all" | "main" | "side")
                  }
                  className="w-full px-2.5 py-2 rounded-lg bg-[#080A10] border border-[#222C42] text-xs text-slate-200 cursor-pointer"
                >
                  <option value="all">Main + sideboard</option>
                  <option value="main">Giocate nel main</option>
                  <option value="side">Giocate in Sideboard</option>
                </select>
              </div>

              {/* 4. Archetype Filter */}
              <div>
                <select
                  value={selectedArchetypeFilter}
                  onChange={(e) => setSelectedArchetypeFilter(e.target.value)}
                  className="w-full px-2.5 py-2 rounded-lg bg-[#080A10] border border-[#222C42] text-xs text-slate-200 cursor-pointer"
                >
                  <option value="all">Tutti gli Archetipi</option>
                  {archetypes.map((a) => (
                    <option key={a.id} value={a.name}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* 5. Sort Order */}
              <div>
                <select
                  value={sortBy}
                  onChange={(e) =>
                    setSortBy(
                      e.target.value as
                        | "overall_desc"
                        | "main_desc"
                        | "side_desc"
                        | "copies_desc"
                        | "cmc_asc"
                        | "name_asc",
                    )
                  }
                  className="w-full px-2.5 py-2 rounded-lg bg-[#080A10] border border-[#222C42] text-xs text-slate-200 cursor-pointer"
                >
                  <option value="overall_desc">
                    Ordina: % presenza totale
                  </option>
                  <option value="main_desc">Ordina: % main</option>
                  <option value="side_desc">Ordina: % Sideboard</option>
                  <option value="copies_desc">Ordina: Copie Medie</option>
                  <option value="cmc_asc">Ordina: valore di mana</option>
                  <option value="name_asc">Ordina: nome (A-Z)</option>
                </select>
              </div>
            </div>

            {/* Color & Rarity Filter Pills Row */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] font-mono-tech uppercase text-slate-400 flex items-center gap-1 mr-1">
                  <Filter className="w-3 h-3 text-[#C8AA6E]" /> Colori:
                </span>
                {(["W", "U", "B", "R", "G", "C"] as const).map((col) => {
                  const active = selectedColors.includes(col);
                  return (
                    <button
                      key={col}
                      type="button"
                      onClick={() => toggleColorFilter(col)}
                      className={`px-2.5 py-1 rounded-lg border text-xs font-mono-tech font-bold flex items-center gap-1.5 transition-all cursor-pointer ${
                        active
                          ? "bg-[#C8AA6E]/25 border-[#C8AA6E] text-[#F3E5C8] shadow"
                          : "bg-[#080A10] border-[#1E2638] text-slate-400 hover:border-slate-600"
                      }`}
                    >
                      <ManaCost cost={`{${col}}`} size="xs" />
                      <span>{col === "C" ? "Incolore" : col}</span>
                    </button>
                  );
                })}
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] font-mono-tech uppercase text-slate-400 mr-1">
                  Rarità:
                </span>
                {[
                  { id: "all", label: "Tutte" },
                  { id: "mythic", label: "Mythic" },
                  { id: "rare", label: "Rare" },
                  { id: "uncommon", label: "Uncommon" },
                  { id: "common", label: "Common" },
                ].map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => setSelectedRarity(r.id)}
                    className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold cursor-pointer ${
                      selectedRarity === r.id
                        ? "bg-[#C8AA6E] border-[#C8AA6E] text-[#090B10]"
                        : "bg-[#080A10] border-[#1E2638] text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="overflow-x-auto max-h-[72vh] overflow-y-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead className="sticky top-0 z-10">
                <tr className="bg-[#090C12] border-b border-[#1E2638] text-[11px] font-mono-tech uppercase text-slate-400">
                  <th className="py-3 px-4">#</th>
                  <th className="py-3 px-4">Carta</th>
                  <th className="py-3 px-4">Costo / Tipo</th>
                  <th className="py-3 px-4 text-right">% presenza totale</th>
                  <th className="py-3 px-4 text-right">
                    Main (% / copie)
                  </th>
                  <th className="py-3 px-4 text-right">
                    Sideboard (% / Copie)
                  </th>
                  <th className="py-3 px-4">
                    Archetipi principali che la usano
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#182030]">
                {filteredTopCards.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="py-10 text-center text-slate-400"
                    >
                      Nessuna carta corrisponde ai filtri selezionati. Clicca su
                      &quot;Reset Filtri&quot; per mostrare tutte le{" "}
                      {topCards.length} carte.
                    </td>
                  </tr>
                ) : (
                  filteredTopCards.map((tc, idx) => {
                    const img =
                      tc.card?.image_uris?.small ||
                      tc.card?.card_faces?.[0]?.image_uris?.small ||
                      "";
                    return (
                      <tr
                        key={tc.id}
                        onClick={() => tc.card && setInspectedCard(tc.card)}
                        className="hover:bg-[#141C2E] transition-colors cursor-pointer"
                      >
                        <td className="py-2.5 px-4 font-mono-tech font-bold text-[#C8AA6E]">
                          #{idx + 1}
                        </td>
                        <td className="py-2.5 px-4">
                          <div className="flex items-center gap-3">
                            {img && (
                              <img
                                src={img}
                                alt={tc.card_name}
                                className="w-8 h-11 rounded object-cover border border-white/10"
                              />
                            )}
                            <div>
                              <span className="font-bold text-slate-100 text-sm block">
                                {tc.card_name}
                              </span>
                              {tc.card?.set_code && (
                                <span className="text-[11px] font-mono-tech uppercase text-slate-400">
                                  {tc.card.set_code} • {tc.card.rarity}
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="py-2.5 px-4">
                          <div className="flex flex-col gap-1">
                            <ManaCost cost={tc.card?.mana_cost} size="xs" />
                            <span className="text-[11px] text-slate-400">
                              {tc.card?.type_line}
                            </span>
                          </div>
                        </td>
                        <td className="py-2.5 px-4 text-right font-mono-tech">
                          <span className="text-sm font-bold text-sky-400">
                            {tc.overall_presence_pct.toFixed(1)}%
                          </span>
                        </td>
                        <td className="py-2.5 px-4 text-right font-mono-tech">
                          {tc.main_presence_pct > 0 ? (
                            <div>
                              <span className="font-bold text-emerald-400">
                                {tc.main_presence_pct.toFixed(1)}%
                              </span>
                              <span className="text-slate-400 ml-1">
                                ({tc.main_avg_copies.toFixed(1)}x)
                              </span>
                            </div>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="py-2.5 px-4 text-right font-mono-tech">
                          {tc.side_presence_pct > 0 ? (
                            <div>
                              <span className="font-bold text-amber-400">
                                {tc.side_presence_pct.toFixed(1)}%
                              </span>
                              <span className="text-slate-400 ml-1">
                                ({tc.side_avg_copies.toFixed(1)}x)
                              </span>
                            </div>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="py-2.5 px-4">
                          <div className="flex flex-wrap gap-1.5">
                            {(tc.top_archetypes || []).map((arch, aIdx) => (
                              <span
                                key={aIdx}
                                className="px-2 py-0.5 rounded bg-[#0A0D15] border border-[#222C42] text-[11px] text-slate-200 font-mono-tech"
                              >
                                {arch.archetype}
                                {archetypeUsageLabel(arch) && (
                                  <span className="text-slate-400">
                                    {" "}
                                    · {archetypeUsageLabel(arch)}
                                  </span>
                                )}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <CardInfoModal
        card={inspectedCard}
        formatId={formatId}
        onClose={() => setInspectedCard(null)}
        onAddCard={() => setInspectedCard(null)}
      />
    </div>
  );
};
