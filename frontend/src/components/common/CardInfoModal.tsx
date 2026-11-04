import React, { useState, useEffect } from "react";
import { BarChart3, FlipHorizontal, Plus, ShieldCheck, X } from "lucide-react";
import { api } from "../../api/client";
import type { Card, CardRulingInfo, FormatId } from "../../types";
import { ManaCost, OracleTextRenderer, SetSymbol } from "./ManaCost";
import { archetypeUsageLabel } from "./metaLabels";
import { useDialog } from "../../hooks/useDialog";

interface CardInfoModalProps {
  card: Card | null;
  formatId: FormatId;
  onClose: () => void;
  onAddCard?: (card: Card, board: "main" | "side", qty: number) => void;
}

export const CardInfoModal: React.FC<CardInfoModalProps> = ({
  card,
  formatId,
  onClose,
  onAddCard,
}) => {
  const [showBackFace, setShowBackFace] = useState(false);
  const [knowledge, setKnowledge] = useState<{
    tags: string[];
    rulings: CardRulingInfo[];
  } | null>(null);

  useEffect(() => {
    setShowBackFace(false);
    setKnowledge(null);
    if (!card) return;
    let cancelled = false;
    api
      .getCardDetail(card.oracle_id, formatId)
      .then((detail) => {
        if (!cancelled)
          setKnowledge({
            tags: detail.functional_tags || [],
            rulings: detail.rulings || [],
          });
      })
      .catch(() => {
        /* rulings and tags are optional extras */
      });
    return () => {
      cancelled = true;
    };
  }, [card?.oracle_id, formatId]);
  const dialog = useDialog(!!card, onClose);
  if (!card) return null;

  const hasBackFace =
    card.card_faces &&
    card.card_faces.length > 1 &&
    Boolean(
      card.card_faces[1]?.image_uris?.normal ||
      card.image_uris?.back_face?.normal,
    );

  const frontImg =
    card.image_uris?.normal ||
    card.image_uris?.large ||
    card.card_faces?.[0]?.image_uris?.normal ||
    "";
  const backImg =
    card.card_faces?.[1]?.image_uris?.normal ||
    card.image_uris?.back_face?.normal ||
    frontImg;

  const displayImg = showBackFace && hasBackFace ? backImg : frontImg;
  const meta = card.meta_info;

  const legalityBadge = (fmt: string, status: string) => {
    const isLegal = status === "legal";
    const isBanned = status === "banned";
    return (
      <div
        key={fmt}
        className={`px-2.5 py-1.5 rounded-lg border flex items-center justify-between text-xs ${
          isLegal
            ? "bg-emerald-950/40 border-emerald-700/40 text-emerald-300"
            : isBanned
              ? "bg-rose-950/50 border-rose-700/50 text-rose-300"
              : "bg-[#111622] border-[#1F273A] text-slate-400"
        }`}
      >
        <span className="capitalize font-medium">{fmt}</span>
        <span className="font-mono-tech text-[11px] uppercase font-bold">
          {isLegal ? "LEGALE" : isBanned ? "BANDITA" : "NON LEGALE"}
        </span>
      </div>
    );
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
        aria-labelledby="card-info-title"
        tabIndex={-1}
        className="bg-[#0D111A] border border-[#26314A] rounded-xl max-w-3xl w-full shadow-2xl overflow-hidden max-h-[calc(100vh-2rem)] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top bar */}
        <div className="px-5 py-3.5 bg-[#121826] border-b border-[#1E2638] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <SetSymbol
              setCode={card.set_code}
              rarity={card.rarity}
              setName={card.set_name}
              className="text-lg"
            />
            <div>
              <div className="flex items-center gap-2.5">
                <h3 id="card-info-title" className="font-bold text-base text-white">
                  {card.name}
                </h3>
                <ManaCost cost={card.mana_cost} size="md" />
              </div>
              <p className="text-xs text-slate-400">
                {card.type_line} •{" "}
                <span className="uppercase font-mono-tech">
                  {card.set_code}
                </span>{" "}
                #{card.collector_number} ({card.rarity})
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#1C2438] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 grid grid-cols-1 md:grid-cols-12 gap-6 max-h-[80vh] overflow-y-auto">
          {/* Card Image Column */}
          <div className="md:col-span-5 flex flex-col items-center gap-3">
            <div className="relative w-full max-w-[260px] aspect-[63/88] rounded-xl overflow-hidden bg-[#07090E] border border-[#242F46] shadow-xl">
              {displayImg ? (
                <img
                  src={displayImg}
                  alt={card.name}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-xs text-slate-400 p-4 text-center">
                  {card.name}
                </div>
              )}
            </div>

            {hasBackFace && (
              <button
                onClick={() => setShowBackFace(!showBackFace)}
                className="w-full max-w-[260px] py-1.5 px-3 rounded-lg bg-[#161E31] hover:bg-[#1F2B46] border border-[#2C3B5E] text-xs font-medium text-[#F3E5C8] flex items-center justify-center gap-2 cursor-pointer"
              >
                <FlipHorizontal className="w-3.5 h-3.5 text-[#C8AA6E]" />
                <span>
                  Gira la carta (faccia {showBackFace ? "frontale" : "posteriore"})
                </span>
              </button>
            )}

            {/* Quick Add to Deck Actions */}
            {onAddCard && (
              <div className="w-full max-w-[260px] grid grid-cols-3 gap-1.5 pt-1">
                <button
                  onClick={() => onAddCard(card, "main", 1)}
                  className="py-2 px-2 rounded-lg bg-[#C8AA6E] hover:bg-[#D9BC82] text-[#090B10] font-bold text-xs flex items-center justify-center gap-1 cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" /> 1 Main
                </button>
                <button
                  onClick={() => onAddCard(card, "main", 4)}
                  className="py-2 px-2 rounded-lg bg-[#1B2438] hover:bg-[#25314C] text-[#F3E5C8] border border-[#C8AA6E]/40 font-bold text-xs flex items-center justify-center gap-1 cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" /> 4x Main
                </button>
                <button
                  onClick={() => onAddCard(card, "side", 1)}
                  className="py-2 px-2 rounded-lg bg-[#141A29] hover:bg-[#1D263B] text-sky-300 border border-sky-500/30 font-semibold text-xs flex items-center justify-center gap-1 cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" /> 1 Side
                </button>
              </div>
            )}
          </div>

          {/* Details & Meta Column */}
          <div className="md:col-span-7 space-y-4">
            {/* Oracle Rules Text */}
            <div className="p-3.5 rounded-lg bg-[#090C12] border border-[#1D2536] space-y-2">
              <div className="flex items-center justify-between text-[11px] font-mono-tech uppercase text-slate-400">
                <span>Testo Regole (Oracle)</span>
                {card.power !== null && card.power !== undefined && (
                  <span className="px-2 py-0.5 rounded bg-[#161D2B] text-[#F3E5C8] font-bold">
                    {card.power} / {card.toughness}
                  </span>
                )}
                {card.loyalty && (
                  <span className="px-2 py-0.5 rounded bg-[#161D2B] text-amber-300 font-bold">
                    Loyalty: {card.loyalty}
                  </span>
                )}
              </div>
              <OracleTextRenderer text={card.oracle_text} className="text-xs" />
              {knowledge && knowledge.tags.length > 0 && (
                <div
                  className="flex flex-wrap gap-1 pt-1"
                  aria-label="Ruoli funzionali"
                >
                  {knowledge.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.5 rounded bg-[#141B2B] border border-[#26324D] text-[11px] font-mono-tech text-slate-300"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {knowledge && knowledge.rulings.length > 0 && (
              <details className="p-3 rounded-lg bg-[#090C12] border border-[#1D2536]">
                <summary className="cursor-pointer text-[11px] font-mono-tech uppercase text-slate-300">
                  Ruling ufficiali ({knowledge.rulings.length})
                </summary>
                <ul className="mt-2 space-y-2 text-xs text-slate-300 leading-relaxed">
                  {knowledge.rulings.map((r, i) => (
                    <li key={i}>
                      <span className="text-slate-400 font-mono-tech mr-1.5">
                        {r.published_at}
                      </span>
                      {r.comment}
                    </li>
                  ))}
                </ul>
              </details>
            )}

            {/* Legalità Formati */}
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300">
                <ShieldCheck className="w-3.5 h-3.5 text-[#C8AA6E]" />
                <span>Legalità e limite di copie</span>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {legalityBadge("standard", card.legality_standard)}
                {legalityBadge("pioneer", card.legality_pioneer)}
                {legalityBadge("modern", card.legality_modern)}
              </div>
              <p className="text-[11px] text-slate-400 font-mono-tech pt-0.5">
                Limite copie in costruito:{" "}
                <strong className="text-slate-200">
                  {card.max_copies === null || card.max_copies === undefined
                    ? "Illimitate (Terra Base / Regola Speciale)"
                    : `Max ${card.max_copies} copie tra Main e Sideboard`}
                </strong>
              </p>
            </div>

            {/* Requisito 5: Info Carta nel Meta (% presenza, copie medie, archetipi principali) */}
            <div className="p-4 rounded-lg bg-[#101522] border border-[#222C42] space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-bold text-[#F3E5C8]">
                  <BarChart3 className="w-4 h-4 text-sky-400" />
                  <span className="capitalize">
                    Statistiche nel metagame ({formatId})
                  </span>
                </div>
                <span className="text-[11px] font-mono-tech text-slate-400">
                  Fonte: liste MTGTop8
                </span>
              </div>

              {meta && meta.overall_presence_pct > 0 ? (
                <>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="p-2.5 rounded bg-[#0A0D15] border border-[#1B2336]">
                      <div className="text-[11px] text-slate-400">
                        Presenza totale
                      </div>
                      <div className="text-base font-bold font-mono-tech text-sky-400">
                        {meta.overall_presence_pct.toFixed(1)}%
                      </div>
                    </div>
                    <div className="p-2.5 rounded bg-[#0A0D15] border border-[#1B2336]">
                      <div className="text-[11px] text-slate-400">
                        Main
                      </div>
                      <div className="text-sm font-bold font-mono-tech text-emerald-400">
                        {meta.main_presence_pct.toFixed(1)}%{" "}
                        <span className="text-[11px] text-slate-400">
                          ({meta.main_avg_copies.toFixed(1)}x)
                        </span>
                      </div>
                    </div>
                    <div className="p-2.5 rounded bg-[#0A0D15] border border-[#1B2336]">
                      <div className="text-[11px] text-slate-400">
                        Sideboard
                      </div>
                      <div className="text-sm font-bold font-mono-tech text-amber-400">
                        {meta.side_presence_pct.toFixed(1)}%{" "}
                        <span className="text-[11px] text-slate-400">
                          ({meta.side_avg_copies.toFixed(1)}x)
                        </span>
                      </div>
                    </div>
                  </div>

                  {meta.top_archetypes && meta.top_archetypes.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="text-[11px] font-semibold text-slate-300">
                        Uso osservato negli archetipi principali:
                      </div>
                      <div className="space-y-1">
                        {meta.top_archetypes.map((arch, idx) => (
                          <div
                            key={idx}
                            className="flex items-center justify-between gap-3 text-xs px-2.5 py-1.5 rounded bg-[#0A0D15] border border-[#182032]"
                          >
                            <span className="font-medium text-slate-200">
                              {arch.archetype}
                            </span>
                            <span className="font-mono-tech text-[11px] text-[#C8AA6E] text-right">
                              {archetypeUsageLabel(arch)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-xs text-slate-400">
                  Nessuna presenza significativa rilevata nei top tier attuali
                  di{" "}
                  <span className="capitalize text-slate-200">{formatId}</span>{" "}
                  (o sincronizzazione Metagame non ancora eseguita per questo
                  formato).
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
