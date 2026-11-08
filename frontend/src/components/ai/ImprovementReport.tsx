import React, { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Copy,
  Layers,
  Sparkles,
  Wrench,
} from "lucide-react";
import { api } from "../../api/client";
import type { DeckImprovementResult, ListAnalysis } from "../../types";
import { ColorBadges } from "../common/ManaCost";

const SEVERITY_BADGE: Record<string, string> = {
  alta: "border-rose-700 bg-rose-950/50 text-rose-200",
  media: "border-amber-700 bg-amber-950/40 text-amber-200",
  bassa: "border-slate-600 bg-slate-800/60 text-slate-300",
};

const PRIORITY_BADGE: Record<string, string> = {
  alta: "border-emerald-700 bg-emerald-950/50 text-emerald-200",
  media: "border-sky-700 bg-sky-950/50 text-sky-200",
  opzionale: "border-slate-600 bg-slate-800/60 text-slate-300",
};

const VERDICT_LABEL: Record<string, { label: string; style: string }> = {
  ottimizzato: {
    label: "Lista già ottimizzata",
    style: "border-emerald-600 bg-emerald-950/50 text-emerald-200",
  },
  migliorabile: {
    label: "Migliorabile con interventi mirati",
    style: "border-amber-600 bg-amber-950/50 text-amber-200",
  },
  da_ristrutturare: {
    label: "Richiede ristrutturazione",
    style: "border-rose-600 bg-rose-950/50 text-rose-200",
  },
};

function AnalysisDeltaCard({
  title,
  before,
  after,
}: {
  title: string;
  before: ListAnalysis;
  after: ListAnalysis;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 space-y-3">
      <p className="eyebrow">{title}</p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div>
          <span className="text-xs text-slate-400 block">Terre</span>
          <span className="font-semibold text-slate-100">
            {before.land_count} → {after.land_count}
          </span>
        </div>
        <div>
          <span className="text-xs text-slate-400 block">MV medio non-terre</span>
          <span className="font-semibold text-slate-100">
            {before.avg_mana_value_nonland} → {after.avg_mana_value_nonland}
          </span>
        </div>
        <div>
          <span className="text-xs text-slate-400 block">Terre sempre stappate</span>
          <span className="font-semibold text-slate-100">
            {before.tapped_lands.untapped} → {after.tapped_lands.untapped}
          </span>
        </div>
        <div>
          <span className="text-xs text-slate-400 block">Terre condizionali / tappate</span>
          <span className="font-semibold text-slate-100">
            {before.tapped_lands.conditional}/{before.tapped_lands.tapped} →{" "}
            {after.tapped_lands.conditional}/{after.tapped_lands.tapped}
          </span>
        </div>
      </div>

      {after.colors.length > 0 && (
        <div className="pt-2 border-t border-slate-800/80">
          <p className="text-xs text-slate-400 mb-2">
            Fonti per colore rispetto ai requisiti Karsten (Prima → Dopo):
          </p>
          <div className="flex flex-wrap gap-2">
            {after.colors.map((cAfter) => {
              const cBefore = before.colors.find((b) => b.color === cAfter.color);
              const beforeSrc = cBefore ? cBefore.sources : 0;
              const ok = cAfter.deficit === 0;
              return (
                <span
                  key={cAfter.color}
                  className={`text-xs rounded border px-2.5 py-1 ${
                    ok
                      ? "border-emerald-800/80 bg-emerald-950/30 text-emerald-200"
                      : "border-amber-700/80 bg-amber-950/30 text-amber-200"
                  }`}
                >
                  <strong>{cAfter.color}</strong>: {beforeSrc} → {cAfter.sources} /{" "}
                  {cAfter.required} rich.
                  {cAfter.driver ? ` (${cAfter.driver})` : ""}
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export const ImprovementReport: React.FC<{
  result: DeckImprovementResult;
  onInspectCard: (name: string) => void;
  onOpenDeckInBuilder?: (deckId: number) => void;
}> = ({ result, onInspectCard, onOpenDeckInBuilder }) => {
  const { improvement, source_deck, improved_deck_preview, comparison, warnings } =
    result;
  const [applying, setApplying] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const verdictInfo =
    VERDICT_LABEL[improvement.verdict] || VERDICT_LABEL.migliorabile;

  const handleApplyToExistingDeck = async () => {
    if (!source_deck.id) return;
    setApplying(true);
    setStatusMsg(null);
    try {
      await api.updateDeck(source_deck.id, {
        name: source_deck.name,
        format_id: source_deck.format_id,
        archetype: improvement.archetype || source_deck.archetype,
        colors: improved_deck_preview.colors,
        cards: improved_deck_preview.cards.map((c) => ({
          oracle_id: c.oracle_id,
          card_name: c.card_name,
          board: c.board,
          quantity: c.quantity,
        })),
      });
      setStatusMsg(
        "Migliorie applicate al mazzo! È stata creata una nuova revisione nello storico.",
      );
      if (onOpenDeckInBuilder) {
        onOpenDeckInBuilder(source_deck.id);
      }
    } catch (e: any) {
      setStatusMsg(`Errore: ${e.message}`);
    } finally {
      setApplying(false);
    }
  };

  const handleSaveAsNewDeck = async () => {
    setApplying(true);
    setStatusMsg(null);
    try {
      const created = await api.createDeck({
        name: improved_deck_preview.name,
        format_id: improved_deck_preview.format_id,
        archetype: improved_deck_preview.archetype,
        colors: improved_deck_preview.colors,
        description: `Versione migliorata da AI Studio. ${improvement.overall_assessment.slice(0, 240)}`,
        cards: improved_deck_preview.cards.map((c) => ({
          oracle_id: c.oracle_id,
          card_name: c.card_name,
          board: c.board,
          quantity: c.quantity,
        })),
      });
      setStatusMsg(`Nuovo mazzo "${created.name}" salvato in libreria!`);
      if (onOpenDeckInBuilder) {
        onOpenDeckInBuilder(created.id);
      }
    } catch (e: any) {
      setStatusMsg(`Errore: ${e.message}`);
    } finally {
      setApplying(false);
    }
  };

  const handleCopyArena = async () => {
    try {
      await navigator.clipboard.writeText(improved_deck_preview.exports.arena);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard errors
    }
  };

  return (
    <div className="space-y-4">
      {/* Header & Quick Actions */}
      <section className="panel space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="eyebrow">Analisi & Miglioramento Mazzo</span>
              <span
                className={`text-xs font-medium rounded-full border px-2.5 py-0.5 ${verdictInfo.style}`}
              >
                {verdictInfo.label}
              </span>
            </div>
            <h2 className="mt-1 flex items-center gap-2.5">
              <span>{source_deck.name}</span>
              <ColorBadges colors={improved_deck_preview.colors} />
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Archetipo: <strong className="text-slate-200">{improvement.archetype}</strong> ·{" "}
              {improvement.suggested_swaps.length} cambi consigliati ·{" "}
              {improvement.candidate_cards.length} ulteriori carte papabili
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {source_deck.id && (
              <button
                type="button"
                onClick={handleApplyToExistingDeck}
                disabled={applying || improvement.suggested_swaps.length === 0}
                className="btn-primary text-xs"
              >
                <Wrench size={14} />
                Applica migliorie al mazzo
              </button>
            )}
            <button
              type="button"
              onClick={handleSaveAsNewDeck}
              disabled={applying}
              className="btn-secondary text-xs"
            >
              <Sparkles size={14} />
              Salva come nuovo mazzo
            </button>
            <button
              type="button"
              onClick={handleCopyArena}
              className="btn-secondary text-xs"
            >
              <Copy size={14} />
              {copied ? "Copiata!" : "Copia lista Arena"}
            </button>
          </div>
        </div>

        {statusMsg && (
          <div className="rounded-lg border border-sky-700/70 bg-sky-950/40 px-3 py-2 text-xs text-sky-200">
            {statusMsg}
          </div>
        )}

        {warnings && warnings.length > 0 && (
          <div className="rounded-lg border border-amber-700/70 bg-amber-950/30 p-3 text-xs text-amber-200 space-y-1">
            <p className="font-semibold flex items-center gap-1.5">
              <AlertTriangle size={14} /> Note di validazione sui cambi:
            </p>
            <ul className="list-disc list-inside space-y-0.5">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}

        <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-line">
          {improvement.overall_assessment}
        </p>

        <AnalysisDeltaCard
          title="Prima e dopo i cambi"
          before={comparison.before_analysis}
          after={comparison.after_analysis}
        />
      </section>

      {/* Diagnosi per Area */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <section className="panel space-y-2">
          <h3 className="text-base">Manabase e Fonti</h3>
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">
            {improvement.manabase_diagnosis}
          </p>
        </section>
        <section className="panel space-y-2">
          <h3 className="text-base">Curva e Interazione</h3>
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">
            {improvement.curve_and_interaction_diagnosis}
          </p>
        </section>
        <section className="panel space-y-2">
          <h3 className="text-base">Posizionamento nel Meta</h3>
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">
            {improvement.meta_positioning_diagnosis}
          </p>
        </section>
      </div>

      {/* Punti di forza da preservare */}
      {improvement.strengths_to_preserve.length > 0 && (
        <section className="panel space-y-3">
          <h3 className="flex items-center gap-2 text-base">
            <CheckCircle2 size={17} className="text-emerald-400" />
            Punti di forza da preservare
          </h3>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-slate-300">
            {improvement.strengths_to_preserve.map((s, idx) => (
              <li
                key={idx}
                className="rounded-lg border border-emerald-900/50 bg-emerald-950/20 px-3 py-2"
              >
                {s}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Punti deboli individuati */}
      {improvement.weaknesses.length > 0 && (
        <section className="panel space-y-3">
          <h3 className="text-base">Analisi dei Punti Deboli ({improvement.weaknesses.length})</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {improvement.weaknesses.map((w, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-slate-800 bg-slate-950/60 p-3.5 space-y-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-sm text-slate-100">
                    {w.title}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span className="badge text-[11px] uppercase">{w.area}</span>
                    <span
                      className={`text-[11px] font-medium rounded-full border px-2 py-0.5 ${
                        SEVERITY_BADGE[w.severity] || SEVERITY_BADGE.media
                      }`}
                    >
                      Gravità {w.severity}
                    </span>
                  </div>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">{w.finding}</p>
                <p className="text-xs text-sky-200/90 leading-relaxed">
                  <strong>Intervento:</strong> {w.recommendation}
                </p>
                {w.affected_matchups && w.affected_matchups.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {w.affected_matchups.map((m, i) => (
                      <span
                        key={i}
                        className="text-[11px] rounded bg-slate-800 px-2 py-0.5 text-slate-300"
                      >
                        vs {m}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Cambi Consigliati (OUT -> IN) */}
      <section className="panel space-y-3">
        <div>
          <h3 className="text-base">
            Cambi Consigliati ({improvement.suggested_swaps.length})
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Clicca sul nome di qualsiasi carta per ispezionare testo Oracle, legalità e statistiche.
          </p>
        </div>

        {improvement.suggested_swaps.length === 0 ? (
          <p className="text-sm text-slate-400">
            Nessun cambio diretto necessario: la lista è già ben bilanciata.
          </p>
        ) : (
          <div className="space-y-3">
            {improvement.suggested_swaps.map((swap, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-slate-800 bg-slate-950/70 p-4 space-y-2.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="badge uppercase text-[11px]">
                      {swap.board === "main" ? "Mainboard" : "Sideboard"}
                    </span>
                    <span
                      className={`text-[11px] rounded-full border px-2 py-0.5 ${
                        PRIORITY_BADGE[swap.priority] || PRIORITY_BADGE.alta
                      }`}
                    >
                      Priorità {swap.priority}
                    </span>
                    <span className="text-xs text-slate-400">· {swap.role}</span>
                  </div>
                  {swap.matchups_improved && swap.matchups_improved.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {swap.matchups_improved.map((m, i) => (
                        <span
                          key={i}
                          className="text-[11px] rounded bg-emerald-950/60 border border-emerald-800/60 px-2 py-0.5 text-emerald-200"
                        >
                          Migliora vs {m}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-3 pt-1">
                  <button
                    type="button"
                    onClick={() => onInspectCard(swap.card_out)}
                    className="rounded-md border border-rose-800/80 bg-rose-950/40 px-3 py-1.5 text-sm font-semibold text-rose-200 hover:border-rose-500 transition"
                  >
                    −{swap.quantity}x {swap.card_out}
                  </button>
                  <ArrowRight size={16} className="text-slate-400" />
                  <button
                    type="button"
                    onClick={() => onInspectCard(swap.card_in)}
                    className="rounded-md border border-emerald-800/80 bg-emerald-950/40 px-3 py-1.5 text-sm font-semibold text-emerald-200 hover:border-emerald-500 transition"
                  >
                    +{swap.quantity}x {swap.card_in}
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs pt-1">
                  <div className="rounded bg-slate-900/70 p-2.5 text-slate-300">
                    <strong className="text-rose-300 block mb-0.5">
                      Perché tagliare {swap.card_out}:
                    </strong>
                    {swap.reason_out}
                  </div>
                  <div className="rounded bg-slate-900/70 p-2.5 text-slate-300">
                    <strong className="text-emerald-300 block mb-0.5">
                      Perché inserire {swap.card_in}:
                    </strong>
                    {swap.reason_in}
                  </div>
                </div>

                {swap.opportunity_cost && (
                  <p className="text-xs text-slate-400">
                    <strong>Trade-off / Costo opportunità:</strong>{" "}
                    {swap.opportunity_cost}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Carte Papabili Alternative */}
      {improvement.candidate_cards.length > 0 && (
        <section className="panel space-y-3">
          <div>
            <h3 className="flex items-center gap-2 text-base">
              <Layers size={17} className="text-sky-400" />
              Altre Carte Papabili da Considerare ({improvement.candidate_cards.length})
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Opzioni legali nel formato per adattare gli slot flessibili al tuo metagame locale.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {improvement.candidate_cards.map((cand, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-slate-800 bg-slate-950/60 p-3.5 space-y-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onInspectCard(cand.card_name)}
                    className="font-semibold text-sm text-sky-300 hover:underline text-left"
                  >
                    {cand.suggested_copies}x {cand.card_name}
                  </button>
                  <div className="flex items-center gap-1.5">
                    <span className="badge text-[11px] uppercase">
                      {cand.board === "main" ? "Main" : "Side"}
                    </span>
                    <span className="text-xs text-slate-400">{cand.role}</span>
                  </div>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {cand.why_consider}
                </p>
                <p className="text-xs text-slate-400 leading-relaxed">
                  <strong className="text-slate-200">Quando preferirla:</strong>{" "}
                  {cand.when_to_prefer}
                </p>
                {cand.replaces_candidates && cand.replaces_candidates.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
                    <span className="text-slate-400">Al posto di:</span>
                    {cand.replaces_candidates.map((rep, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => onInspectCard(rep)}
                        className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-slate-200 hover:border-sky-500"
                      >
                        {rep}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {improvement.sideboard_tuning_notes && (
        <section className="panel space-y-2">
          <h3 className="text-base">Note di Ottimizzazione Sideboard</h3>
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">
            {improvement.sideboard_tuning_notes}
          </p>
        </section>
      )}
    </div>
  );
};
