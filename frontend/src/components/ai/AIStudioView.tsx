import React, { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Cpu,
  Loader2,
  Plus,
  Settings,
  Sparkles,
  Swords,
  X,
} from "lucide-react";
import { api } from "../../api/client";
import type {
  AppSettings,
  Card,
  DeckDetail,
  DeckSummary,
  FormatId,
  MetaArchetypeInfo,
} from "../../types";
import { ColorBadges } from "../common/ManaCost";
import { GuideReader } from "../library/GuideReader";
import { CardInfoModal } from "../common/CardInfoModal";

interface Props {
  formatId: FormatId;
  activeDeck: DeckDetail | null;
  settings: AppSettings | null;
  openGuide?: boolean;
  onGuideIntentHandled?: () => void;
  onChangeModel: (id: string) => void;
  preselectedOpponentArchetype?: MetaArchetypeInfo | null;
  onClearPreselectedOpponent?: () => void;
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
  onOpenDeckInBuilder,
  onOpenDeckInPlaytest,
  onOpenSettings,
}: Props) {
  const [tab, setTab] = useState<"generator" | "guide" | "matchup">(
      "generator",
    ),
    [decks, setDecks] = useState<DeckSummary[]>([]),
    [archetypes, setArchetypes] = useState<MetaArchetypeInfo[]>([]);
  const [color, setColor] = useState("Dimir"),
    [customColors, setCustomColors] = useState<string[]>([]),
    [archetype, setArchetype] = useState("midrange"),
    [prompt, setPrompt] = useState(""),
    [buildAround, setBuildAround] = useState<string[]>([]);
  const [query, setQuery] = useState(""),
    [suggestions, setSuggestions] = useState<Card[]>([]),
    [inspected, setInspected] = useState<Card | null>(null);
  const [generation, setGeneration] = useState<any>(null),
    [genLoading, setGenLoading] = useState(false),
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
  const [deckA, setDeckA] = useState<number | "custom">(
      activeDeck?.id || "custom",
    ),
    [textA, setTextA] = useState(""),
    [modeB, setModeB] = useState<"meta" | "saved" | "custom">("meta"),
    [deckB, setDeckB] = useState<number | "">(""),
    [archB, setArchB] = useState<number | "">(""),
    [textB, setTextB] = useState("");
  const [matchup, setMatchup] = useState<any>(null),
    [matchLoading, setMatchLoading] = useState(false),
    [matchError, setMatchError] = useState(""),
    [loadError, setLoadError] = useState("");
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
    }
  }, [activeDeck?.id]);
  useEffect(() => {
    if (openGuide) {
      setTab("guide");
      if (activeDeck) setGuideDeck(activeDeck.id);
      onGuideIntentHandled?.();
    }
  }, [openGuide, activeDeck?.id]);
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
  const runGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setGenLoading(true);
    setGenError("");
    try {
      const colors =
        color === "Personalizzato"
          ? customColors
          : combinations.find(([n]) => n === color)?.[1] || [];
      const result = await api.generateDeckAI({
        format_id: formatId,
        prompt,
        archetype,
        colors,
        color_preset_name: color,
        build_around_cards: buildAround,
        model_id: modelId,
        save_deck: true,
      });
      setGeneration(result);
      await loadDecks();
    } catch (e: any) {
      setGenError(e.message);
    } finally {
      setGenLoading(false);
    }
  };
  const runGuide = async (e: React.FormEvent) => {
    e.preventDefault();
    const request = ++guideRequest.current;
    setGuideLoading(true);
    setGuideError("");
    setGuideAttempted(true);
    setGuide(null);
    setGuideId(undefined);
    try {
      const r = await api.generateDeckGuideAI({
        format_id: formatId,
        deck_id: guideDeck === "custom" ? undefined : guideDeck,
        decklist_text: guideDeck === "custom" ? customGuide : undefined,
        deck_name:
          decks.find((d) => d.id === guideDeck)?.name || "Lista personalizzata",
        model_id: modelId,
      });
      if (request === guideRequest.current) {
        setGuide(r.guide);
        setGuideId(r.meta?.guide_id);
      }
    } catch (e: any) {
      if (request === guideRequest.current) setGuideError(e.message);
    } finally {
      if (request === guideRequest.current) setGuideLoading(false);
    }
  };
  const runMatch = async (e: React.FormEvent) => {
    e.preventDefault();
    setMatchLoading(true);
    setMatchError("");
    try {
      const r = await api.analyzeSpotMatchupAI({
        format_id: formatId,
        deck_a_id: deckA === "custom" ? undefined : deckA,
        deck_a_name: decks.find((d) => d.id === deckA)?.name || "Mazzo A",
        deck_a_text: deckA === "custom" ? textA : undefined,
        deck_b_archetype_id: modeB === "meta" && archB ? archB : undefined,
        deck_b_id: modeB === "saved" && deckB ? deckB : undefined,
        deck_b_text: modeB === "custom" ? textB : undefined,
        deck_b_name:
          archetypes.find((a) => a.id === archB)?.name ||
          decks.find((d) => d.id === deckB)?.name ||
          "Mazzo B",
        model_id: modelId,
      });
      setMatchup(r);
    } catch (e: any) {
      setMatchError(e.message);
    } finally {
      setMatchLoading(false);
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
  const runButton = (loading: boolean, label: string, disabled = false) => (
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
        ["cards_out", "OUT · dal mainboard", "text-rose-300"],
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
      {tab === "generator" && (
        <div className="space-y-5">
          <form className="panel space-y-5" onSubmit={runGenerate}>
            <div>
              <h2 className="text-xl font-bold">Progetta le tue 75</h2>
              <p className="text-sm text-slate-400 mt-2">
                Lista da 60 main + 15 side. La legalità viene controllata sul
                catalogo locale; una proposta non valida viene rifiutata prima
                del salvataggio.
              </p>
            </div>
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
                  onChange={(e) => setArchetype(e.target.value)}
                >
                  {[
                    "aggro",
                    "midrange",
                    "control",
                    "combo",
                    "tempo",
                    "ramp",
                  ].map((a) => (
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
            {runButton(genLoading, "Genera e salva mazzo")}
            <p className="text-xs text-slate-500">
              L’analisi può richiedere alcuni minuti. Puoi consultare altre
              sezioni mentre il lavoro prosegue in questa sessione.
            </p>
          </form>
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
                  <p className="text-xs text-slate-400 mt-2">
                    {generation.meta?.model_id} ·{" "}
                    {generation.meta?.validation_attempts} verifiche
                  </p>
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
              {textSection(
                "Tesi competitiva",
                generation.ai_result.strategy_overview,
              )}
              {textSection("Manabase", generation.ai_result.mana_curve_notes)}
              {textSection(
                "Progetto della sideboard",
                generation.ai_result.sideboard_mapping_notes,
              )}
              {textSection(
                "Sinergie",
                generation.ai_result.key_synergies?.join("\n\n"),
              )}
              {textSection(
                "Alternative escluse",
                generation.ai_result.excluded_cards_or_traps?.join("\n\n"),
              )}
              <div className="grid lg:grid-cols-2 gap-4">
                {(["mainboard", "sideboard"] as const).map((board) => (
                  <section className="panel" key={board}>
                    <h3 className="capitalize">
                      {board} (
                      {generation.ai_result[board].reduce(
                        (n: number, c: any) => n + c.quantity,
                        0,
                      )}
                      )
                    </h3>
                    {generation.ai_result[board].map((slot: any, i: number) => (
                      <details
                        className="py-3 border-b border-slate-800 text-sm"
                        key={i}
                      >
                        <summary className="cursor-pointer">
                          {slot.quantity}× {slot.card_name}{" "}
                          <span className="text-slate-500">· {slot.role}</span>
                        </summary>
                        <p className="text-slate-300 mt-2">{slot.reason}</p>
                        <button
                          className="text-sky-200 mt-3"
                          onClick={() => inspect(slot.card_name)}
                        >
                          Esamina carta
                        </button>
                      </details>
                    ))}
                  </section>
                ))}
              </div>
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
              disabled={guideLoading}
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
              La guida viene verificata e corretta prima del salvataggio. Ogni
              versione approvata si trova in Mazzi e guide, con lista esatta e
              fonti. Il winrate ponderato usa le quote del metagame disponibile.
            </p>
            {runButton(
              guideLoading,
              guide ? "Genera nuova versione" : "Genera e salva guida",
              guideDeck === "custom" && !customGuide.trim(),
            )}
          </form>
          {guideLoading && (
            <div role="status" className="panel flex items-start gap-3">
              <Loader2 className="animate-spin shrink-0" size={20} />
              <div>
                <p className="font-semibold">Preparazione della nuova guida</p>
                <p className="text-sm text-slate-300 mt-2">
                  Generazione, controllo delle sidate, revisione Oracle e
                  correzioni automatiche possono richiedere alcuni minuti. Qui
                  apparirà solo la versione che supera i controlli.
                </p>
              </div>
            </div>
          )}
          {guideError && (
            <div className="notice-error" role="alert">
              <p className="font-semibold">
                {guideAttempted
                  ? "Generazione non completata"
                  : "Caricamento non riuscito"}
              </p>
              <p className="mt-2">{guideError}</p>
              {guideAttempted && (
                <p className="mt-2 text-sm">
                  Nessuna nuova versione salvata. Le guide precedenti restano in
                  Mazzi e guide.
                </p>
              )}
            </div>
          )}
          {guide && (
            <GuideReader guide={guide} guideId={guideId} onInspect={inspect} />
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
            )}
          </form>
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
