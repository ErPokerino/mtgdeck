import React, { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Cpu,
  Loader2,
  Plus,
  Settings,
  Sparkles,
  Swords,
  Wrench,
  X,
} from "lucide-react";
import { api } from "../../api/client";
import type {
  AppSettings,
  Card,
  DeckDetail,
  DeckGenerationResult,
  DeckImprovementResult,
  DeckSummary,
  FormatId,
  MetaArchetypeInfo,
} from "../../types";
import { ColorBadges } from "../common/ManaCost";
import { GuideJobStatus } from "./GuideJobStatus";
import { GuideReader } from "../library/GuideReader";
import { CardInfoModal } from "../common/CardInfoModal";
import { GenerationReport } from "./GenerationReport";
import { ImprovementReport } from "./ImprovementReport";
import { CostEstimate } from "./CostEstimate";
import { AIJobStatus } from "./AIJobStatus";
import { isActiveJob, useAIJob } from "../../hooks/useAIJob";

interface Props {
  formatId: FormatId;
  activeDeck: DeckDetail | null;
  settings: AppSettings | null;
  openGuide?: boolean;
  onGuideIntentHandled?: () => void;
  onChangeModel: (id: string) => void;
  preselectedOpponentArchetype?: MetaArchetypeInfo | null;
  onClearPreselectedOpponent?: () => void;
  preselectedBaseArchetype?: MetaArchetypeInfo | null;
  onClearPreselectedBase?: () => void;
  onOpenDeckInBuilder: (deck: DeckDetail) => void;
  onOpenDeckInPlaytest: (deck: DeckDetail) => void;
  onOpenSettings: () => void;
}
const combinations: [string, string[]][] = [
  ["Libero", []],
  ["Mono White", ["W"]],
  ["Mono Blue", ["U"]],
  ["Mono Black", ["B"]],
  ["Mono Red", ["R"]],
  ["Mono Green", ["G"]],
  ["Azorius", ["W", "U"]],
  ["Dimir", ["U", "B"]],
  ["Rakdos", ["B", "R"]],
  ["Gruul", ["R", "G"]],
  ["Selesnya", ["W", "G"]],
  ["Orzhov", ["W", "B"]],
  ["Izzet", ["U", "R"]],
  ["Golgari", ["B", "G"]],
  ["Boros", ["W", "R"]],
  ["Simic", ["U", "G"]],
  ["Esper", ["W", "U", "B"]],
  ["Grixis", ["U", "B", "R"]],
  ["Jund", ["B", "R", "G"]],
  ["Naya", ["W", "R", "G"]],
  ["Bant", ["W", "U", "G"]],
  ["Abzan", ["W", "B", "G"]],
  ["Jeskai", ["W", "U", "R"]],
  ["Sultai", ["U", "B", "G"]],
  ["Mardu", ["W", "B", "R"]],
  ["Temur", ["U", "R", "G"]],
  ["Domain", ["W", "U", "B", "R", "G"]],
];
const archetypeOptions = [
  "aggro",
  "midrange",
  "control",
  "combo",
  "tempo",
  "ramp",
];
const date = (v: string) => new Date(v).toLocaleString("it-IT");
export function AIStudioView({
  formatId,
  activeDeck,
  settings,
  openGuide,
  onGuideIntentHandled,
  onChangeModel,
  preselectedOpponentArchetype,
  onClearPreselectedOpponent,
  preselectedBaseArchetype,
  onClearPreselectedBase,
  onOpenDeckInBuilder,
  onOpenDeckInPlaytest,
  onOpenSettings,
}: Props) {
  const [tab, setTab] = useState<
      "generator" | "improve" | "guide" | "matchup"
    >("generator"),
    [decks, setDecks] = useState<DeckSummary[]>([]),
    [archetypes, setArchetypes] = useState<MetaArchetypeInfo[]>([]);
  const [color, setColor] = useState("Dimir"),
    [customColors, setCustomColors] = useState<string[]>([]),
    [archetype, setArchetype] = useState("midrange"),
    [baseArch, setBaseArch] = useState<number | "">(""),
    [prompt, setPrompt] = useState(""),
    [buildAround, setBuildAround] = useState<string[]>([]);
  const [query, setQuery] = useState(""),
    [suggestions, setSuggestions] = useState<Card[]>([]),
    [inspected, setInspected] = useState<Card | null>(null);
  const [generation, setGeneration] = useState<DeckGenerationResult | null>(
      null,
    ),
    [genError, setGenError] = useState("");
  const [guideDeck, setGuideDeck] = useState<number | "custom">(
      activeDeck?.id || "custom",
    ),
    [customGuide, setCustomGuide] = useState(""),
    [guide, setGuide] = useState<any>(null),
    [guideId, setGuideId] = useState<number | undefined>();
  const [guideLoading, setGuideLoading] = useState(false),
    [guideError, setGuideError] = useState(""),
    [guideAttempted, setGuideAttempted] = useState(false);
  const guideRequest = useRef(0);
  const jobListRequest = useRef(0);
  const [guideJob, setGuideJob] = useState<any>(null);
  const [legacyDrafts, setLegacyDrafts] = useState<any[]>([]);
  const guideBusy =
    guideLoading ||
    ["queued", "running", "publishing"].includes(guideJob?.status);
  useEffect(() => {
    let stopped = false;
    const request = ++jobListRequest.current;
    api
      .listGuideJobs(formatId)
      .then((data) => {
        if (stopped || request !== jobListRequest.current) return;
        setLegacyDrafts(data.legacy_drafts || []);
        const latestForDeck = data.jobs.find(
          (j: any) => j.deck_id === (guideDeck === "custom" ? null : guideDeck),
        );
        const job =
          data.jobs.find((j: any) =>
            ["queued", "running", "publishing"].includes(j.status),
          ) || (latestForDeck?.status !== "completed" ? latestForDeck : null);
        if (job) {
          if (["queued", "running", "publishing"].includes(job.status))
            setGuideDeck(job.deck_id || "custom");
          setGuideJob((old: any) => (old && old.id > job.id ? old : job));
          ++guideRequest.current;
          setGuide(null);
          setGuideId(undefined);
        } else
          setGuideJob((old: any) =>
            old && ["queued", "running", "publishing"].includes(old.status)
              ? old
              : null,
          );
      })
      .catch((e) => {
        if (!stopped)
          setGuideError(`Stato analisi non disponibile: ${e.message}`);
      });
    return () => {
      stopped = true;
    };
  }, [formatId, guideDeck]);
  useEffect(() => {
    if (
      !guideJob ||
      !["queued", "running", "publishing"].includes(guideJob.status)
    )
      return;
    let stopped = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const job = await api.getGuideJob(guideJob.id);
        if (stopped) return;
        setGuideJob(job);
        setGuideError("");
        if (
          job.status === "completed" &&
          job.deck_id === (guideDeck === "custom" ? null : guideDeck)
        ) {
          setGuide(job.result.guide);
          setGuideId(job.result.meta.guide_id);
        }
      } catch (e: any) {
        if (!stopped)
          setGuideError(
            `Connessione interrotta. L’analisi prosegue nel server; riprovo automaticamente. ${e.message}`,
          );
      } finally {
        polling = false;
      }
    };
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [guideJob?.id, guideJob?.status, guideDeck]);
  const [deckA, setDeckA] = useState<number | "custom">(
      activeDeck?.id || "custom",
    ),
    [textA, setTextA] = useState(""),
    [modeB, setModeB] = useState<"meta" | "saved" | "custom">("meta"),
    [deckB, setDeckB] = useState<number | "">(""),
    [archB, setArchB] = useState<number | "">(""),
    [textB, setTextB] = useState("");
  const [matchup, setMatchup] = useState<any>(null),
    [matchError, setMatchError] = useState(""),
    [loadError, setLoadError] = useState("");
  const [improveDeck, setImproveDeck] = useState<number | "custom">(
      activeDeck?.id || "custom",
    ),
    [customImprove, setCustomImprove] = useState(""),
    [improvePrompt, setImprovePrompt] = useState(""),
    [improvement, setImprovement] = useState<DeckImprovementResult | null>(null),
    [improveError, setImproveError] = useState("");
  const available =
    settings?.available_models.filter((m) => m.tier === "complex") || [];
  const ready = !!(
    settings?.has_gemini_api_key || settings?.ai_provider === "vertex-ai"
  );
  const modelId = settings?.selected_complex_model_id;
  const loadDecks = () =>
    api
      .listDecks(formatId)
      .then(setDecks)
      .catch((e) => setLoadError(e.message));
  useEffect(() => {
    let stopped = false;
    loadDecks();
    api
      .getFormatMeta(formatId)
      .then((m) => {
        if (!stopped) {
          setArchetypes(m.archetypes || []);
          setArchB((v) => v || m.archetypes?.[0]?.id || "");
          setBaseArch((v) =>
            m.archetypes?.some((a) => a.id === v) ? v : "",
          );
        }
      })
      .catch((e) => setLoadError(e.message));
    return () => {
      stopped = true;
    };
  }, [formatId, activeDeck?.id]);
  useEffect(() => {
    if (activeDeck) {
      setGuideDeck(activeDeck.id);
      setDeckA(activeDeck.id);
      setImproveDeck(activeDeck.id);
    }
  }, [activeDeck?.id]);
  useEffect(() => {
    if (openGuide) {
      setTab("guide");
      if (activeDeck) setGuideDeck(activeDeck.id);
      onGuideIntentHandled?.();
    }
  }, [openGuide, activeDeck?.id]);
  const chooseBase = (id: number | "") => {
    setBaseArch(id);
    const arch = archetypes.find((a) => a.id === id);
    if (!arch) return;
    const preset = combinations.find(
      ([, cols]) =>
        cols.length === arch.colors.length &&
        cols.every((c) => arch.colors.includes(c)),
    );
    setCustomColors(arch.colors);
    setColor(preset?.[0] || "Personalizzato");
    if (archetypeOptions.includes(arch.category)) setArchetype(arch.category);
  };
  useEffect(() => {
    if (preselectedBaseArchetype && archetypes.length) {
      setTab("generator");
      chooseBase(preselectedBaseArchetype.id);
      onClearPreselectedBase?.();
    }
  }, [preselectedBaseArchetype, archetypes]);
  useEffect(() => {
    if (preselectedOpponentArchetype) {
      setTab("matchup");
      setModeB("meta");
      setArchB(preselectedOpponentArchetype.id);
      onClearPreselectedOpponent?.();
    }
  }, [preselectedOpponentArchetype]);
  useEffect(() => {
    const request = ++guideRequest.current;
    setGuide(null);
    setGuideId(undefined);
    setGuideError("");
    setGuideLoading(false);
    setGuideAttempted(false);
    if (guideDeck !== "custom") {
      Promise.all([api.getDeck(guideDeck), api.listGuides(formatId)])
        .then(([d, versions]) => {
          if (request === guideRequest.current && d.guide_json) {
            setGuide(d.guide_json);
            setGuideId(versions.find((g) => g.deck_id === guideDeck)?.id);
          }
        })
        .catch((e) => {
          if (request === guideRequest.current) setGuideError(e.message);
        });
    }
    return () => {
      if (request === guideRequest.current) ++guideRequest.current;
    };
  }, [guideDeck, formatId, activeDeck?.guide_json]);
  useEffect(() => {
    let cancelled = false;
    if (query.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    const timer = setTimeout(
      () =>
        api
          .searchCards({ format_id: formatId, q: query, page_size: 8 })
          .then((r) => {
            if (!cancelled) setSuggestions(r.cards);
          })
          .catch(() => {}),
      250,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, formatId]);
  const inspect = async (name: string) => {
    const card =
      generation?.deck?.cards.find((c: any) => c.card_name === name)?.card ||
      activeDeck?.cards.find((c) => c.card_name === name)?.card;
    if (card) {
      setInspected(card);
      return;
    }
    try {
      const r = await api.searchCards({
        format_id: formatId,
        q: name,
        page_size: 10,
      });
      const c = r.cards.find(
        (c) => c.name === name || c.name.split(" // ")[0] === name,
      );
      if (c) setInspected(c);
    } catch {}
  };
  const [genJob, setGenJob] = useAIJob(formatId, "deck_generation", (job) => {
    if (job.status === "completed") {
      setGeneration(job.result);
      loadDecks();
    } else if (job.status === "failed") setGenError(job.error || "");
  });
  const [matchJob, setMatchJob] = useAIJob(formatId, "matchup_spot", (job) => {
    if (job.status === "completed") setMatchup(job.result);
    else if (job.status === "failed") setMatchError(job.error || "");
  });
  const [improveJob, setImproveJob] = useAIJob(
    formatId,
    "deck_improvement",
    (job) => {
      if (job.status === "completed") {
        setImprovement(job.result);
        loadDecks();
      } else if (job.status === "failed") setImproveError(job.error || "");
    },
  );
  const genLoading = isActiveJob(genJob);
  const matchLoading = isActiveJob(matchJob);
  const improveLoading = isActiveJob(improveJob);
  const cancelJob = async (id: number, setJob: (j: any) => void) => {
    try {
      setJob(await api.cancelAIJob(id));
    } catch {}
  };
  const runGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setGenError("");
    try {
      const colors =
        color === "Personalizzato"
          ? customColors
          : combinations.find(([n]) => n === color)?.[1] || [];
      const job = await api.startDeckGenerationJob({
        format_id: formatId,
        prompt,
        archetype,
        colors,
        color_preset_name: color,
        build_around_cards: buildAround,
        base_archetype_id: baseArch === "" ? undefined : baseArch,
        model_id: modelId,
        save_deck: true,
      });
      setGenJob(job);
    } catch (e: any) {
      setGenError(e.message);
    }
  };
  const startGuide = async (legacyRunId?: number) => {
    ++jobListRequest.current;
    ++guideRequest.current;
    setGuideLoading(true);
    setGuideError("");
    setGuideAttempted(true);
    setGuide(null);
    setGuideId(undefined);
    try {
      setGuideJob(
        await api.startGuideJob(
          {
            format_id: formatId,
            deck_id: guideDeck === "custom" ? undefined : guideDeck,
            decklist_text: guideDeck === "custom" ? customGuide : undefined,
            deck_name:
              decks.find((d) => d.id === guideDeck)?.name ||
              "Lista personalizzata",
            model_id: modelId,
          },
          legacyRunId,
        ),
      );
    } catch (e: any) {
      setGuideError(e.message);
    } finally {
      setGuideLoading(false);
    }
  };
  const runGuide = (e: React.FormEvent) => {
    e.preventDefault();
    if (!guideBusy) void startGuide();
  };
  const resumeGuide = async () => {
    ++jobListRequest.current;
    if (!guideJob) return;
    setGuideLoading(true);
    setGuideError("");
    setGuide(null);
    setGuideId(undefined);
    try {
      setGuideJob(await api.resumeGuideJob(guideJob.id));
    } catch (e: any) {
      setGuideError(e.message);
    } finally {
      setGuideLoading(false);
    }
  };
  const runMatch = async (e: React.FormEvent) => {
    e.preventDefault();
    setMatchError("");
    try {
      const job = await api.startMatchupJob({
        format_id: formatId,
        deck_a_id: deckA === "custom" ? undefined : deckA,
        deck_a_name: decks.find((d) => d.id === deckA)?.name || "Mazzo A",
        deck_a_text: deckA === "custom" ? textA : undefined,
        deck_b_archetype_id: modeB === "meta" && archB ? archB : undefined,
        deck_b_id: modeB === "saved" && deckB ? deckB : undefined,
        deck_b_text: modeB === "custom" ? textB : undefined,
        deck_b_name:
          modeB === "meta"
            ? archetypes.find((a) => a.id === archB)?.name || "Mazzo B"
            : modeB === "saved"
              ? decks.find((d) => d.id === deckB)?.name || "Mazzo B"
              : "Lista incollata",
        model_id: modelId,
      });
      setMatchJob(job);
    } catch (e: any) {
      setMatchError(e.message);
    }
  };
  const runImprove = async (e: React.FormEvent) => {
    e.preventDefault();
    setImproveError("");
    setImprovement(null);
    try {
      const job = await api.startDeckImprovementJob({
        format_id: formatId,
        deck_id: improveDeck === "custom" ? undefined : improveDeck,
        decklist_text: improveDeck === "custom" ? customImprove : undefined,
        deck_name:
          decks.find((d) => d.id === improveDeck)?.name ||
          "Lista personalizzata",
        user_prompt: improvePrompt.trim() || undefined,
        model_id: modelId,
      });
      setImproveJob(job);
    } catch (e: any) {
      setImproveError(e.message);
    }
  };
  const deckSelect = (
    value: number | "custom",
    setValue: (v: number | "custom") => void,
    label: string,
  ) => (
    <label className="block text-sm text-slate-300">
      {label}
      <select
        className="field block w-full mt-2"
        value={value}
        onChange={(e) =>
          setValue(
            e.target.value === "custom" ? "custom" : Number(e.target.value),
          )
        }
      >
        <option value="custom">Incolla una lista</option>
        {decks.map((d) => (
          <option value={d.id} key={d.id}>
            {d.name} · {d.mainboard_count}/{d.sideboard_count}
          </option>
        ))}
      </select>
    </label>
  );
  const runButton = (
    loading: boolean,
    label: string,
    disabled = false,
    skill?: "deck_generation" | "deck_guide" | "matchup_spot" | "deck_improvement",
  ) => (
    <div className="space-y-2">
      <button
        className="btn-primary"
        disabled={!ready || loading || disabled}
        type="submit"
      >
        {loading ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <Sparkles size={16} />
        )}{" "}
        {loading ? "Analisi in corso…" : label}
      </button>
      {skill && !loading && <CostEstimate skill={skill} modelId={modelId} />}
    </div>
  );
  const textSection = (title: string, text: string) =>
    text && (
      <section className="panel">
        <h3>{title}</h3>
        <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line mt-3">
          {text}
        </p>
      </section>
    );
  const swapList = (plan: any) => (
    <div className="grid md:grid-cols-2 gap-4 mt-4">
      {[
        ["cards_in", "IN · dalla sideboard", "text-emerald-300"],
        ["cards_out", "OUT · dal main", "text-rose-300"],
      ].map(([f, label, color]) => (
        <div className="panel" key={f}>
          <h4 className={`font-bold text-sm ${color}`}>
            {label} (
            {plan?.[f]?.reduce((sum: number, c: any) => sum + c.quantity, 0) ||
              0}
            )
          </h4>
          {plan?.[f]?.map((c: any, i: number) => (
            <div key={i} className="mt-3 text-sm">
              <button
                className="text-sky-200"
                onClick={() => inspect(c.card_name)}
              >
                {c.quantity}× {c.card_name}
              </button>
              <p className="text-slate-400 mt-1">{c.reason}</p>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
  return (
    <div className="max-w-[1500px] mx-auto p-4 md:p-7 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="eyebrow">Preparazione competitiva · {formatId}</p>
          <h1 className="text-3xl font-bold mt-2">AI Studio</h1>
        </div>
        <label className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
          <Cpu size={16} />
          Modello strategico
          <select
            aria-label="Modello strategico"
            className="field"
            value={modelId || ""}
            onChange={(e) => onChangeModel(e.target.value)}
          >
            {available.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="panel text-sm text-slate-400 leading-relaxed">
        I mazzi generati vengono salvati automaticamente in{" "}
        <strong className="text-slate-100">Mazzi e guide → Mazzi attivi</strong>
        . Ogni guida conserva una versione in{" "}
        <strong className="text-slate-100">Guide salvate</strong>, anche per una
        lista incollata. Flash Lite gestisce solo le riparazioni; i selettori
        strategici condividono la stessa scelta.
      </p>
      {!ready && (
        <div className="panel flex flex-wrap justify-between gap-3 text-sm">
          <p>Configura il provider AI prima di avviare un’analisi.</p>
          <button className="btn-secondary" onClick={onOpenSettings}>
            <Settings size={16} />
            Apri impostazioni
          </button>
        </div>
      )}
      {loadError && (
        <p className="notice-error" role="alert">
          Dati di contesto non disponibili: {loadError}
        </p>
      )}
      <nav className="flex flex-wrap gap-2" aria-label="Attività AI">
        {(
          [
            ["generator", "Crea mazzo", Sparkles],
            ["improve", "Migliora mazzo", Wrench],
            ["guide", "Guida e sideboard", BookOpen],
            ["matchup", "Confronta matchup", Swords],
          ] as const
        ).map(([id, label, Icon]) => (
          <button
            key={id}
            className={tab === id ? "btn-primary" : "btn-secondary"}
            aria-pressed={tab === id}
            onClick={() => setTab(id)}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </nav>
      {tab === "improve" && (
        <div className="space-y-5">
          <form className="panel space-y-5" onSubmit={runImprove}>
            <div className="grid md:grid-cols-2 gap-4">
              {deckSelect(
                improveDeck,
                setImproveDeck,
                "Mazzo da analizzare e migliorare",
              )}
              <label className="block text-sm text-slate-300">
                Obiettivo o focus specifico (opzionale)
                <input
                  type="text"
                  className="field block w-full mt-2"
                  placeholder="Es. Migliorare il matchup contro Aggro, sistemare la manabase, aggiornare la sideboard…"
                  value={improvePrompt}
                  onChange={(e) => setImprovePrompt(e.target.value)}
                />
              </label>
            </div>
            {improveDeck === "custom" && (
              <label className="block text-sm text-slate-300">
                Lista del mazzo (formato MTG Arena / MTGO)
                <textarea
                  className="field block w-full mt-2 min-h-[150px] font-mono text-xs"
                  placeholder={"4 Fatal Push\n4 Thoughtseize\n...\n\nSideboard\n2 Duress"}
                  value={customImprove}
                  onChange={(e) => setCustomImprove(e.target.value)}
                />
              </label>
            )}
            <p className="text-xs text-slate-400">
              L'AI analizza punti deboli strutturali (fonti Karsten, curva, densità d'interazione, posizionamento nel metagame),
              propone cambi bilanciati <strong>OUT → IN</strong> validati sul catalogo del formato e suggerisce ulteriori carte papabili.
            </p>
            {improveError && (
              <p className="notice-error" role="alert">
                {improveError}
              </p>
            )}
            {runButton(
              improveLoading,
              "Analizza punti deboli e migliora mazzo",
              improveDeck === "custom" && !customImprove.trim(),
              "deck_improvement",
            )}
          </form>
          {improveJob && improveLoading && (
            <AIJobStatus
              job={improveJob}
              onCancel={() => cancelJob(improveJob.id, setImproveJob)}
            />
          )}
          {improvement && (
            <ImprovementReport
              result={improvement}
              onInspectCard={inspect}
              onOpenDeckInBuilder={async (deckId) => {
                try {
                  const full = await api.getDeck(deckId);
                  loadDecks();
                  onOpenDeckInBuilder(full);
                } catch {}
              }}
            />
          )}
        </div>
      )}
      {tab === "generator" && (
        <div className="space-y-5">
          <form className="panel space-y-5" onSubmit={runGenerate}>
            <div>
              <h2 className="text-xl font-bold">Progetta le tue 75</h2>
              <p className="text-sm text-slate-400 mt-2">
                Lista da 60 main + 15 side, costruita contro il meta del
                meta. L'app calcola fonti, curva e probabilità, poi un revisore
                cerca i punti deboli prima del salvataggio.
              </p>
            </div>
            <label className="block text-sm">
              Punto di partenza
              <select
                className="field w-full block mt-2"
                value={baseArch}
                onChange={(e) =>
                  chooseBase(
                    e.target.value === "" ? "" : Number(e.target.value),
                  )
                }
              >
                <option value="">Brew: parti dalla tua tesi</option>
                {archetypes.length > 0 && (
                  <optgroup label="Lista di consenso di un archetipo del meta">
                    {archetypes.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} · {a.meta_share_pct}%
                        {a.decklists_count ? ` · ${a.decklists_count} liste` : ""}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              <span className="block text-xs text-slate-400 mt-2">
                {baseArch === ""
                  ? "Archetipi e carte fuori meta sono ammessi: le liste più vicine servono solo come riferimento di densità, e ogni scelta viene ottimizzata contro il meta."
                  : "Si parte dalle carte che le liste dell'archetipo hanno in comune; ogni differenza dal consenso verrà motivata contro il meta."}
              </span>
            </label>
            <div className="grid md:grid-cols-2 gap-4">
              <label className="text-sm">
                Colori
                <select
                  className="field w-full block mt-2"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                >
                  {combinations.map(([name]) => (
                    <option key={name}>{name}</option>
                  ))}
                  {color === "Personalizzato" && (
                    <option>Personalizzato</option>
                  )}
                </select>
              </label>
              <label className="text-sm">
                Archetipo
                <select
                  className="field w-full block mt-2"
                  value={archetype}
                  disabled={baseArch !== ""}
                  onChange={(e) => setArchetype(e.target.value)}
                >
                  {archetypeOptions.map((a) => (
                    <option key={a}>{a}</option>
                  ))}
                </select>
              </label>
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm text-slate-200">
                Seleziona i colori desiderati
              </legend>
              <div className="flex flex-wrap gap-2">
                {["W", "U", "B", "R", "G"].map((c) => {
                  const current =
                    color === "Personalizzato"
                      ? customColors
                      : combinations.find(([n]) => n === color)?.[1] || [];
                  const selected = current.includes(c);
                  return (
                    <button
                      key={c}
                      type="button"
                      aria-label={`Colore ${c}`}
                      aria-pressed={selected}
                      className={selected ? "btn-primary" : "btn-secondary"}
                      onClick={() => {
                        const next = selected
                          ? current.filter((x) => x !== c)
                          : [...current, c];
                        const preset = combinations.find(
                          ([, cols]) =>
                            cols.length === next.length &&
                            cols.every((x) => next.includes(x)),
                        );
                        setCustomColors(next);
                        setColor(preset?.[0] || "Personalizzato");
                      }}
                    >
                      <ColorBadges colors={[c]} size="md" />
                      {c}
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-slate-400">
                Combinazione: {color}{" "}
                {color !== "Libero" && (
                  <ColorBadges
                    colors={
                      color === "Personalizzato"
                        ? customColors
                        : combinations.find(([n]) => n === color)?.[1] || []
                    }
                  />
                )}
              </p>
            </fieldset>
            <div>
              <label className="text-sm block mb-2" htmlFor="buildaround">
                Carte attorno a cui costruire
              </label>
              <div className="flex flex-wrap gap-2 mb-3">
                {buildAround.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      setBuildAround((b) => b.filter((n) => n !== name))
                    }
                  >
                    {name}
                    <X size={14} />
                  </button>
                ))}
              </div>
              <input
                id="buildaround"
                className="field w-full"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Cerca una carta legale, es. Fable of the Mirror-Breaker"
              />
              {suggestions.length > 0 && (
                <div className="border border-slate-700 rounded-lg mt-2 max-h-56 overflow-y-auto">
                  {suggestions.map((c) => (
                    <button
                      type="button"
                      className="block w-full text-left px-4 py-3 text-sm hover:bg-slate-800"
                      key={c.oracle_id}
                      onClick={() => {
                        setBuildAround((v) =>
                          v.includes(c.name) ? v : [...v, c.name],
                        );
                        setQuery("");
                        setSuggestions([]);
                      }}
                    >
                      <Plus className="inline w-4 mr-2" />
                      {c.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <label className="block text-sm">
              Obiettivo e vincoli
              <textarea
                className="field w-full mt-2 min-h-28"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Es. Prepara una lista per un torneo con molto aggro. Motiva i flex slot e i compromessi contro control."
              />
            </label>
            {runButton(genLoading, "Genera e salva mazzo", false, "deck_generation")}
            <p className="text-xs text-slate-400">
              L’analisi richiede alcuni minuti e continua sul server: puoi
              consultare altre sezioni o ricaricare la pagina. Il mazzo viene
              salvato in Mazzi e guide.
            </p>
          </form>
          {genJob && isActiveJob(genJob) && (
            <AIJobStatus
              job={genJob}
              onCancel={() => cancelJob(genJob.id, setGenJob)}
            />
          )}
          {genError && (
            <p className="notice-error" role="alert">
              {genError}
            </p>
          )}
          {generation && (
            <div className="space-y-4">
              <div className="panel flex flex-wrap justify-between items-center gap-3">
                <div>
                  <p className="eyebrow">
                    Salvato nell’archivio · #{generation.deck?.id}
                  </p>
                  <h2 className="text-2xl font-bold mt-2">
                    {generation.ai_result.deck_name}
                  </h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="btn-primary"
                    onClick={() => onOpenDeckInBuilder(generation.deck)}
                  >
                    Apri builder
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => onOpenDeckInPlaytest(generation.deck)}
                  >
                    Playtest
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => {
                      setGuideDeck(generation.deck.id);
                      setTab("guide");
                    }}
                  >
                    Crea guida
                  </button>
                </div>
              </div>
              <GenerationReport generation={generation} onInspect={inspect} />
            </div>
          )}
        </div>
      )}
      {tab === "guide" && (
        <div className="space-y-5">
          <form onSubmit={runGuide} className="panel space-y-4">
            <h2 className="text-xl font-bold">
              Guida al mazzo e piano di sideboard
            </h2>
            <fieldset
              disabled={guideBusy}
              className="space-y-4 disabled:opacity-60"
            >
              {deckSelect(guideDeck, setGuideDeck, "Lista da analizzare")}
              {guideDeck === "custom" && (
                <textarea
                  aria-label="Lista personalizzata per guida"
                  className="field w-full min-h-44 font-mono"
                  value={customGuide}
                  onChange={(e) => setCustomGuide(e.target.value)}
                  placeholder={"Deck\n4 Card Name\n…\n\nSideboard\n2 Card Name"}
                />
              )}
            </fieldset>
            <p className="text-sm text-slate-400">
              La guida si salva solo a revisione conclusa, con lista legale e
              ogni correzione verificata. Di solito bastano pochi minuti; se il
              tempo non basta la bozza viene conservata e puoi riprenderne la
              revisione. Ogni versione approvata si trova in Mazzi e guide.
            </p>
            {runButton(
              guideBusy,
              guide ? "Genera nuova versione" : "Genera e salva guida",
              guideDeck === "custom" && !customGuide.trim(),
              "deck_guide",
            )}
          </form>
          {guideJob && (
            <GuideJobStatus
              job={guideJob}
              onCancel={() =>
                api
                  .cancelGuideJob(guideJob.id)
                  .then(setGuideJob)
                  .catch((e) => setGuideError(e.message))
              }
              onResume={() => void resumeGuide()}
            />
          )}
          {!guideBusy &&
            !guideJob &&
            guideDeck !== "custom" &&
            legacyDrafts.find((d) => d.deck_id === guideDeck) && (
              <div className="panel space-y-3">
                <p className="font-semibold">
                  È disponibile la bozza del tentativo precedente
                </p>
                <p className="text-sm text-slate-300">
                  Puoi recuperare il lavoro e riprendere solo la revisione,
                  senza aspettare una nuova scrittura completa.
                </p>
                <button
                  className="btn-primary"
                  onClick={() =>
                    void startGuide(
                      legacyDrafts.find((d) => d.deck_id === guideDeck).run_id,
                    )
                  }
                >
                  Recupera e verifica la bozza
                </button>
              </div>
            )}
          {guideError && (
            <div className="notice-error" role="alert">
              <p className="font-semibold">
                {guideBusy
                  ? "Aggiornamento dello stato sospeso"
                  : guideAttempted
                    ? "Generazione non completata"
                    : "Caricamento non riuscito"}
              </p>
              <p className="mt-2">{guideError}</p>
              {guideAttempted && !guideBusy && (
                <p className="mt-2 text-sm">
                  Nessuna nuova versione salvata. Le guide precedenti restano in
                  Mazzi e guide.
                </p>
              )}
            </div>
          )}
          {guide && (
            <GuideReader
              guide={guide}
              guideId={guideId}
              onInspect={inspect}
              onReviewStarted={(job) => {
                ++jobListRequest.current;
                ++guideRequest.current;
                setGuide(null);
                setGuideId(undefined);
                setGuideJob(job);
              }}
            />
          )}
        </div>
      )}
      {tab === "matchup" && (
        <div className="space-y-5">
          <form onSubmit={runMatch} className="panel space-y-5">
            <div>
              <h2 className="text-xl font-bold">Confronto testa a testa</h2>
              <p className="text-sm text-slate-400 mt-2">
                Le percentuali sono stime teoriche AI; non sono risultati di
                partite. Entrambe le liste devono essere riconosciute e legali
                nel formato.
              </p>
            </div>
            <div className="grid md:grid-cols-2 gap-6">
              <div className="space-y-3">
                {deckSelect(deckA, setDeckA, "Mazzo A · il tuo mazzo")}
                {deckA === "custom" && (
                  <textarea
                    aria-label="Lista mazzo A"
                    className="field w-full min-h-44 font-mono"
                    value={textA}
                    onChange={(e) => setTextA(e.target.value)}
                    placeholder="Incolla la lista completa"
                  />
                )}
              </div>
              <div className="space-y-3">
                <label className="block text-sm">
                  Mazzo B · avversario
                  <select
                    aria-label="Origine mazzo avversario"
                    className="field block w-full mt-2"
                    value={modeB}
                    onChange={(e) => setModeB(e.target.value as typeof modeB)}
                  >
                    <option value="meta">Archetipo del metagame</option>
                    <option value="saved">Mazzo salvato</option>
                    <option value="custom">Incolla una lista</option>
                  </select>
                </label>
                {modeB === "meta" && archB && (
                  <div className="flex items-center gap-2 text-sm text-slate-300">
                    <ColorBadges
                      colors={
                        archetypes.find((a) => a.id === archB)?.colors || []
                      }
                      size="md"
                    />{" "}
                    {archetypes.find((a) => a.id === archB)?.name}
                  </div>
                )}
                {modeB === "meta" ? (
                  <select
                    aria-label="Archetipo avversario"
                    className="field w-full"
                    value={archB}
                    onChange={(e) => setArchB(Number(e.target.value))}
                  >
                    <option value="">Seleziona archetipo…</option>
                    {archetypes.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} · {a.meta_share_pct}%
                      </option>
                    ))}
                  </select>
                ) : modeB === "saved" ? (
                  <select
                    aria-label="Mazzo avversario salvato"
                    className="field w-full"
                    value={deckB}
                    onChange={(e) => setDeckB(Number(e.target.value))}
                  >
                    <option value="">Seleziona mazzo…</option>
                    {decks.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <textarea
                    aria-label="Lista mazzo B"
                    className="field w-full min-h-44 font-mono"
                    value={textB}
                    onChange={(e) => setTextB(e.target.value)}
                    placeholder="Incolla la lista completa"
                  />
                )}
              </div>
            </div>
            {runButton(
              matchLoading,
              "Analizza matchup",
              (deckA === "custom" && !textA.trim()) ||
                (modeB === "custom" && !textB.trim()) ||
                (modeB === "meta" && !archB) ||
                (modeB === "saved" && !deckB),
              "matchup_spot",
            )}
          </form>
          {matchJob && isActiveJob(matchJob) && (
            <AIJobStatus
              job={matchJob}
              onCancel={() => cancelJob(matchJob.id, setMatchJob)}
            />
          )}
          {matchError && (
            <p className="notice-error" role="alert">
              {matchError}
            </p>
          )}
          {matchup && (
            <div className="space-y-4">
              <h2 className="text-2xl font-bold">
                {matchup.analysis.matchup_title}
              </h2>
              <div className="grid md:grid-cols-3 gap-4">
                {[
                  ["Game 1", "expected_winrate_deck_a_pre_side_pct"],
                  ["Game post-side", "expected_winrate_deck_a_post_side_pct"],
                  ["Match Bo3", "overall_expected_winrate_deck_a_pct"],
                ].map(([label, key]) => (
                  <div className="panel" key={key}>
                    <p className="eyebrow">{label} · stima teorica A</p>
                    <p className="text-3xl font-bold text-emerald-300 mt-3">
                      {matchup.analysis[key]}%
                    </p>
                  </div>
                ))}
              </div>
              {textSection(
                "Chi è il beatdown?",
                matchup.analysis.whos_the_beatdown,
              )}
              <div className="grid md:grid-cols-2 gap-4">
                {textSection(
                  "Strategia mazzo A",
                  matchup.analysis.deck_a_strategy,
                )}
                {textSection(
                  "Strategia mazzo B",
                  matchup.analysis.deck_b_strategy,
                )}
              </div>
              {textSection(
                "Turni critici e interazioni",
                matchup.analysis.critical_turns_and_interactions?.join("\n\n"),
              )}
              <section className="panel">
                <h3>Carte decisive</h3>
                {matchup.analysis.key_cards?.map((c: any, i: number) => (
                  <div className="mt-4 text-sm" key={i}>
                    <button
                      className="text-sky-200"
                      onClick={() => inspect(c.card_name)}
                    >
                      {c.card_name} · {c.owner} · {c.impact_level}
                    </button>
                    <p className="text-slate-400 mt-2">
                      {c.how_to_play_or_counter}
                    </p>
                  </div>
                ))}
              </section>
              {(["a", "b"] as const).map((player) => (
                <section className="panel" key={player}>
                  <h3>Sideboard · Mazzo {player.toUpperCase()}</h3>
                  <p className="text-sm text-slate-400 mt-3">
                    {
                      matchup.analysis[`sideboard_plan_for_deck_${player}`]
                        ?.post_side_adjustments
                    }
                  </p>
                  {swapList(
                    matchup.analysis[`sideboard_plan_for_deck_${player}`],
                  )}
                </section>
              ))}
            </div>
          )}
        </div>
      )}
      <CardInfoModal
        card={inspected}
        formatId={formatId}
        onClose={() => setInspected(null)}
      />
    </div>
  );
}
