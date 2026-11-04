import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useRef,
} from "react";
import {
  AlertTriangle,
  ArrowLeftRight,
  BarChart2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FilePlus2,
  FileUp,
  Filter,
  FolderOpen,
  Info,
  LayoutGrid,
  List,
  Minus,
  Plus,
  RotateCcw,
  Save,
  Search,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../../api/client";
import type {
  Card,
  DeckAnalytics,
  DeckCardItem,
  DeckDetail,
  DeckSummary,
  DeckValidationReport,
  FormatDetail,
  FormatId,
  ListAnalysis,
} from "../../types";
import { CardInfoModal } from "../common/CardInfoModal";
import { ColorBadges, ManaCost, SetSymbol } from "../common/ManaCost";
import { ResizableSplitPane } from "../common/ResizableSplitPane";
import { ImportExportModal } from "./ImportExportModal";
import { UndoToast } from "../common/UndoToast";
import { InteractionSummary, ManaRequirements } from "./CompetitiveStats";

interface DeckBuilderViewProps {
  formatId: FormatId;
  formatDetail: FormatDetail | null;
  preselectedSetCode?: string | null;
  onClearPreselectedSet?: () => void;
  activeDeck: DeckDetail | null;
  onDeckChange: (deck: DeckDetail | null) => void;
  onNavigateToAI?: () => void;
}

const ARCHETYPES = [
  { id: "aggro", label: "Aggro" },
  { id: "midrange", label: "Midrange" },
  { id: "control", label: "Control" },
  { id: "combo", label: "Combo" },
  { id: "tempo", label: "Tempo" },
  { id: "ramp", label: "Ramp / Big Mana" },
];

const CARD_TYPES = [
  "",
  "Creature",
  "Instant",
  "Sorcery",
  "Planeswalker",
  "Artifact",
  "Enchantment",
  "Land",
  "Battle",
];

// Deck rows: devices with a mouse swap info for controls on hover or keyboard focus;
// touch screens have no hover, so they always show the controls.
// Classes are spelled out in full: Tailwind only generates classes it finds as literal text.
const ROW_INFO =
  "hidden [@media(hover:hover)]:flex [@media(hover:hover)]:group-hover:hidden [@media(hover:hover)]:group-focus-within:hidden items-center gap-1.5";
const ROW_CONTROLS =
  "flex [@media(hover:hover)]:hidden [@media(hover:hover)]:group-hover:flex [@media(hover:hover)]:group-focus-within:flex items-center gap-0.5";
const ROW_BUTTON =
  "p-1.5 min-w-6 min-h-6 flex items-center justify-center rounded bg-[#0B0E17] cursor-pointer";

const manaValueOf = (cost: string) =>
  (cost.match(/\{[^}]+\}/g) || []).reduce((sum, raw) => {
    const first = raw.slice(1, -1).split("/")[0];
    if (/^\d+$/.test(first)) return sum + Number(first);
    return ["X", "Y", "Z"].includes(first) ? sum : sum + 1;
  }, 0);

// Split cards and Rooms carry the sum of both halves; each half is cast on its own.
const castableManaValue = (card: Card) => {
  if (card.layout === "split") {
    const costs = (card.card_faces || [])
      .map((f) => f.mana_cost || "")
      .filter(Boolean);
    if (costs.length) return Math.min(...costs.map(manaValueOf));
  }
  return card.cmc || 0;
};

// Scryfall Tagger functions ingested by the backend (descendants included).
const FUNCTION_FILTERS = [
  { id: "", label: "Tutte le funzioni" },
  { id: "removal", label: "Rimozione" },
  { id: "removal-creature", label: "Rimozione creature" },
  { id: "removal-exile", label: "Esilio" },
  { id: "burn", label: "Danno diretto" },
  { id: "sweeper", label: "Rimozione di massa" },
  { id: "counterspell", label: "Counter" },
  { id: "discard", label: "Scarto" },
  { id: "draw", label: "Pescata" },
  { id: "card-advantage", label: "Vantaggio carte" },
  { id: "hate-graveyard", label: "Hate al cimitero" },
  { id: "removal-artifact", label: "Rimozione artefatti" },
  { id: "removal-enchantment", label: "Rimozione incantesimi" },
  { id: "ramp", label: "Ramp" },
  { id: "tutor", label: "Tutor" },
  { id: "lifegain", label: "Guadagno vita" },
  { id: "recursion", label: "Ricorsione" },
  { id: "protection", label: "Protezione" },
];

const RARITIES = [
  { id: "", label: "Tutte le rarità" },
  { id: "common", label: "Common" },
  { id: "uncommon", label: "Uncommon" },
  { id: "rare", label: "Rare" },
  { id: "mythic", label: "Mythic Rare" },
];

export const DeckBuilderView: React.FC<DeckBuilderViewProps> = ({
  formatId,
  formatDetail,
  preselectedSetCode,
  onClearPreselectedSet,
  activeDeck,
  onDeckChange,
  onNavigateToAI,
}) => {
  // --- Search Filter States (Requirement 3) ---
  const [nameQuery, setNameQuery] = useState("");
  const [oracleQuery, setOracleQuery] = useState("");
  const [selectedSet, setSelectedSet] = useState("");
  const [selectedColors, setSelectedColors] = useState<string[]>([]);
  const [colorMode, setColorMode] = useState<"include" | "exact" | "at_most">(
    "include",
  );
  const [cmcExact, setCmcExact] = useState<number | null>(null);
  const [cmcMin, setCmcMin] = useState("");
  const [cmcMax, setCmcMax] = useState("");
  const [powerMin, setPowerMin] = useState("");
  const [powerMax, setPowerMax] = useState("");
  const [toughnessMin, setToughnessMin] = useState("");
  const [toughnessMax, setToughnessMax] = useState("");
  const [selectedRarity, setSelectedRarity] = useState("");
  const [selectedFunction, setSelectedFunction] = useState("");
  const nameInput = useRef<HTMLInputElement>(null);
  // "/" focuses the card search, as in most catalogues; ignored while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing =
        el &&
        (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) ||
          el.isContentEditable);
      if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        nameInput.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const [selectedType, setSelectedType] = useState("");
  const [subtypeQuery, setSubtypeQuery] = useState("");
  const [sortBy, setSortBy] = useState("meta_desc");
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [page, setPage] = useState(1);

  // --- Search Results State ---
  const [searchResults, setSearchResults] = useState<Card[]>([]);
  const [totalCards, setTotalCards] = useState(0);
  const [searching, setSearching] = useState(true);
  const [searchedOnce, setSearchedOnce] = useState(false);
  const [inspectedCard, setInspectedCard] = useState<Card | null>(null);

  const [draft] = useState<any>(() => {
    try {
      return JSON.parse(
        localStorage.getItem(`aetherdeck.draft.${formatId}`) || "null",
      );
    } catch {
      return null;
    }
  });
  const draftRestored = useRef(false);
  const fingerprint = (
    name: string,
    archetype: string,
    items: DeckCardItem[],
  ) =>
    JSON.stringify([
      name,
      archetype,
      items.map((i) => [i.oracle_id, i.board, i.quantity]).sort(),
    ]);
  const [savedFingerprint, setSavedFingerprint] = useState(
    activeDeck
      ? fingerprint(activeDeck.name, activeDeck.archetype, activeDeck.cards)
      : draft?.savedFingerprint ||
          fingerprint(`Nuovo Mazzo ${formatId.toUpperCase()}`, "midrange", []),
  );
  // --- Working Deck State (Requirement 4) ---
  const [deckId, setDeckId] = useState<number | null>(
    draft?.deckId ?? activeDeck?.id ?? null,
  );
  const [deckName, setDeckName] = useState(
    draft?.deckName ||
      activeDeck?.name ||
      `Nuovo Mazzo ${formatId.toUpperCase()}`,
  );
  const [deckArchetype, setDeckArchetype] = useState(
    draft?.deckArchetype || activeDeck?.archetype || "midrange",
  );
  const [deckItems, setDeckItems] = useState<DeckCardItem[]>(
    draft?.deckItems || activeDeck?.cards || [],
  );
  const [colorLabel, setColorLabel] = useState(
    activeDeck?.color_label || "Colorless",
  );
  const [deckColors, setDeckColors] = useState<string[]>(
    activeDeck?.colors || [],
  );
  const [validation, setValidation] = useState<DeckValidationReport>(
    activeDeck?.validation || {
      is_valid: false,
      format_id: formatId,
      mainboard_count: 0,
      sideboard_count: 0,
      companion_count: 0,
      issues: [],
    },
  );
  const [competitive, setCompetitive] = useState<ListAnalysis | null>(null);
  const [undo, setUndo] = useState<{
    message: string;
    items: DeckCardItem[];
  } | null>(null);
  const dismissUndo = useCallback(() => setUndo(null), []);
  const [analytics, setAnalytics] = useState<DeckAnalytics>(
    activeDeck?.analytics || {
      mana_curve: {},
      avg_cmc_nonland: 0,
      color_pip_distribution: {},
      mana_source_distribution: {},
      type_Counts: {},
      land_count: 0,
      nonland_count: 0,
    },
  );
  const [exportTexts, setExportTexts] = useState({
    arena_format: "",
    mtgo_format: "",
  });

  // Deck View Layout Controls
  const [groupBy, setGroupBy] = useState<"type" | "cmc">("type");
  const [viewStyle, setViewStyle] = useState<"visual" | "list">("visual");
  const [savedDecks, setSavedDecks] = useState<DeckSummary[]>([]);
  const [savingDeck, setSavingDeck] = useState(false);
  const [saveToast, setSaveToast] = useState<string | null>(null);
  const [isImportExportOpen, setIsImportExportOpen] = useState(false);
  const [hoveredCardImg, setHoveredCardImg] = useState<string | null>(null);

  // Apply preselected set from Format Explorer if passed
  useEffect(() => {
    if (preselectedSetCode) {
      setSelectedSet(preselectedSetCode);
      setPage(1);
      onClearPreselectedSet?.();
    }
  }, [preselectedSetCode, onClearPreselectedSet]);

  // Sync when format changes
  useEffect(() => {
    setSelectedSet("");
    setPage(1);
    api
      .listDecks(formatId)
      .then(setSavedDecks)
      .catch(() => {});
  }, [formatId]);

  // Sync if parent passes a new activeDeck
  useEffect(() => {
    if (activeDeck) {
      if (
        !draftRestored.current &&
        draft?.deckId === activeDeck.id &&
        draft?.savedFingerprint !==
          fingerprint(draft.deckName, draft.deckArchetype, draft.deckItems)
      ) {
        draftRestored.current = true;
        return;
      }
      draftRestored.current = true;
      setSavedFingerprint(
        fingerprint(activeDeck.name, activeDeck.archetype, activeDeck.cards),
      );
      setDeckId(activeDeck.id);
      setDeckName(activeDeck.name);
      setDeckArchetype(activeDeck.archetype);
      setDeckItems(activeDeck.cards);
      setDeckColors(activeDeck.colors);
      setColorLabel(activeDeck.color_label || "Colorless");
      setValidation(activeDeck.validation);
      setAnalytics(activeDeck.analytics);
    }
  }, [activeDeck]);

  const dirty =
    fingerprint(deckName, deckArchetype, deckItems) !== savedFingerprint;
  useEffect(() => {
    try {
      localStorage.setItem(
        `aetherdeck.draft.${formatId}`,
        JSON.stringify({
          deckId,
          deckName,
          deckArchetype,
          deckItems,
          savedFingerprint,
        }),
      );
    } catch {}
  }, [formatId, deckId, deckName, deckArchetype, deckItems, savedFingerprint]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // Execute Card Search. Only the latest request may update results: older ones are aborted.
  const searchAbort = useRef<AbortController | null>(null);
  const executeSearch = useCallback(async () => {
    searchAbort.current?.abort();
    const controller = new AbortController();
    searchAbort.current = controller;
    setSearching(true);
    try {
      const combinedType = [selectedType, subtypeQuery.trim()]
        .filter(Boolean)
        .join(" ");
      const res = await api.searchCards(
        {
          format_id: formatId,
          q: nameQuery.trim() || undefined,
          oracle_q: oracleQuery.trim() || undefined,
          set_code: selectedSet || undefined,
          colors:
            selectedColors.length > 0 ? selectedColors.join(",") : undefined,
          color_mode: colorMode,
          cmc_exact: cmcExact !== null ? cmcExact : undefined,
          cmc_min: cmcMin !== "" ? Number(cmcMin) : undefined,
          cmc_max: cmcMax !== "" ? Number(cmcMax) : undefined,
          power_min: powerMin !== "" ? Number(powerMin) : undefined,
          power_max: powerMax !== "" ? Number(powerMax) : undefined,
          toughness_min: toughnessMin !== "" ? Number(toughnessMin) : undefined,
          toughness_max: toughnessMax !== "" ? Number(toughnessMax) : undefined,
          rarity: selectedRarity || undefined,
          card_type: combinedType || undefined,
          tag: selectedFunction || undefined,
          sort_by: sortBy,
          page,
          page_size: 36,
        },
        controller.signal,
      );
      setSearchResults(res.cards);
      setTotalCards(res.total);
      setSearchedOnce(true);
    } catch (err) {
      if (controller.signal.aborted) return;
      console.error("Search error:", err);
    } finally {
      if (searchAbort.current === controller) setSearching(false);
    }
  }, [
    formatId,
    nameQuery,
    oracleQuery,
    selectedSet,
    selectedColors,
    colorMode,
    cmcExact,
    cmcMin,
    cmcMax,
    powerMin,
    powerMax,
    toughnessMin,
    toughnessMax,
    selectedRarity,
    selectedType,
    subtypeQuery,
    selectedFunction,
    sortBy,
    page,
  ]);

  useEffect(() => {
    const timer = setTimeout(() => {
      executeSearch();
    }, 160);
    return () => clearTimeout(timer);
  }, [executeSearch]);

  // Real-time Stateless Validation & Analytics, debounced; a stale response never overwrites a newer one.
  useEffect(() => {
    const controller = new AbortController();
    const payload = {
      name: deckName,
      format_id: formatId,
      archetype: deckArchetype,
      cards: deckItems.map((item) => ({
        oracle_id: item.oracle_id,
        card_name: item.card_name,
        board: item.board,
        quantity: item.quantity,
      })),
    };
    const timer = setTimeout(() => {
      api
        .analyzeDeck(payload, controller.signal)
        .then((res) => {
          setDeckColors(res.colors);
          setColorLabel(res.color_label);
          setValidation(res.validation);
          setAnalytics(res.analytics);
          setCompetitive(res.competitive);
          setExportTexts(res.export);
        })
        .catch((err) => {
          if (!controller.signal.aborted) console.error("Analyze error:", err);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [deckItems, formatId, deckName, deckArchetype]);

  // Reset all search filters
  const handleResetFilters = () => {
    setNameQuery("");
    setOracleQuery("");
    setSelectedSet("");
    setSelectedColors([]);
    setColorMode("include");
    setCmcExact(null);
    setCmcMin("");
    setCmcMax("");
    setPowerMin("");
    setPowerMax("");
    setToughnessMin("");
    setToughnessMax("");
    setSelectedRarity("");
    setSelectedType("");
    setSubtypeQuery("");
    setSelectedFunction("");
    setPage(1);
  };
  const activeFilters: { label: string; clear: () => void }[] = [
    nameQuery && { label: `Nome: ${nameQuery}`, clear: () => setNameQuery("") },
    oracleQuery && { label: `Testo: ${oracleQuery}`, clear: () => setOracleQuery("") },
    selectedColors.length > 0 && {
      label: `Colori: ${selectedColors.join("")}`,
      clear: () => setSelectedColors([]),
    },
    selectedType && { label: `Tipo: ${selectedType}`, clear: () => setSelectedType("") },
    subtypeQuery && { label: `Sottotipo: ${subtypeQuery}`, clear: () => setSubtypeQuery("") },
    selectedFunction && {
      label: `Funzione: ${FUNCTION_FILTERS.find((f) => f.id === selectedFunction)?.label}`,
      clear: () => setSelectedFunction(""),
    },
    selectedSet && { label: `Set: ${selectedSet.toUpperCase()}`, clear: () => setSelectedSet("") },
    selectedRarity && { label: `Rarità: ${selectedRarity}`, clear: () => setSelectedRarity("") },
    cmcExact !== null && { label: `Costo: ${cmcExact}`, clear: () => setCmcExact(null) },
    (cmcMin !== "" || cmcMax !== "") && {
      label: `Costo ${cmcMin || "0"}–${cmcMax || "∞"}`,
      clear: () => {
        setCmcMin("");
        setCmcMax("");
      },
    },
    (powerMin !== "" || powerMax !== "") && {
      label: `Forza ${powerMin || "0"}–${powerMax || "∞"}`,
      clear: () => {
        setPowerMin("");
        setPowerMax("");
      },
    },
    (toughnessMin !== "" || toughnessMax !== "") && {
      label: `Costituzione ${toughnessMin || "0"}–${toughnessMax || "∞"}`,
      clear: () => {
        setToughnessMin("");
        setToughnessMax("");
      },
    },
  ].filter(Boolean) as { label: string; clear: () => void }[];

  const toggleColor = (col: string) => {
    setPage(1);
    setSelectedColors((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col],
    );
  };

  // --- Deck Manipulation Actions (+ / - / Remove / Move Main <-> Side) ---
  const handleAddCard = (card: Card, board: "main" | "side", delta: number) => {
    setDeckItems((prev) => {
      const idx = prev.findIndex(
        (i) => i.oracle_id === card.oracle_id && i.board === board,
      );
      const totalAcrossBoards = prev
        .filter((i) => i.oracle_id === card.oracle_id)
        .reduce((acc, i) => acc + i.quantity, 0);

      // Rispetta il limite max_copies se delta > 0
      const maxAllowed = card.max_copies;
      let effectiveDelta = delta;
      if (
        effectiveDelta > 0 &&
        maxAllowed !== null &&
        maxAllowed !== undefined
      ) {
        const remaining = Math.max(0, maxAllowed - totalAcrossBoards);
        effectiveDelta = Math.min(effectiveDelta, remaining);
        if (effectiveDelta <= 0) return prev;
      }

      if (idx >= 0) {
        const nextQty = prev[idx].quantity + effectiveDelta;
        if (nextQty <= 0) {
          return prev.filter((_, i) => i !== idx);
        }
        const copy = [...prev];
        copy[idx] = { ...copy[idx], quantity: nextQty };
        return copy;
      } else if (effectiveDelta > 0) {
        return [
          ...prev,
          {
            oracle_id: card.oracle_id,
            card_name: card.name,
            board,
            quantity: effectiveDelta,
            card,
          },
        ];
      }
      return prev;
    });
  };

  const handleRemoveCard = (
    oracleId: string,
    board: "main" | "side" | "companion",
  ) => {
    const removed = deckItems.find(
      (i) => i.oracle_id === oracleId && i.board === board,
    );
    setDeckItems((prev) =>
      prev.filter((i) => !(i.oracle_id === oracleId && i.board === board)),
    );
    if (removed)
      setUndo({
        message: `Rimosse ${removed.quantity} ${removed.card_name} (${board === "main" ? "main" : board === "side" ? "side" : "companion"})`,
        items: deckItems,
      });
  };

  const handleMoveBoard = (item: DeckCardItem) => {
    const targetBoard: "main" | "side" =
      item.board === "main" ? "side" : "main";
    setDeckItems((prev) => {
      const withoutSource = prev.filter(
        (i) => !(i.oracle_id === item.oracle_id && i.board === item.board),
      );
      const existingTargetIdx = withoutSource.findIndex(
        (i) => i.oracle_id === item.oracle_id && i.board === targetBoard,
      );
      if (existingTargetIdx >= 0) {
        const copy = [...withoutSource];
        copy[existingTargetIdx] = {
          ...copy[existingTargetIdx],
          quantity: copy[existingTargetIdx].quantity + item.quantity,
        };
        return copy;
      }
      return [...withoutSource, { ...item, board: targetBoard }];
    });
  };

  const handleSaveDeck = async () => {
    setSavingDeck(true);
    try {
      const payload = {
        name: deckName,
        format_id: formatId,
        archetype: deckArchetype,
        colors: deckColors,
        color_label: colorLabel,
        cards: deckItems.map((i) => ({
          oracle_id: i.oracle_id,
          card_name: i.card_name,
          board: i.board,
          quantity: i.quantity,
        })),
      };
      let saved: DeckDetail;
      if (deckId) {
        saved = await api.updateDeck(deckId, payload);
      } else {
        saved = await api.createDeck(payload);
        setDeckId(saved.id);
      }
      setSavedFingerprint(
        fingerprint(saved.name, saved.archetype, saved.cards),
      );
      onDeckChange(saved);
      const list = await api.listDecks(formatId);
      setSavedDecks(list);
      setSaveToast("Salvato nel server → Mazzi e guide. Versione conservata.");
      setTimeout(() => setSaveToast(null), 2500);
    } catch (err: any) {
      setSaveToast(`Errore di salvataggio: ${err.message}`);
    } finally {
      setSavingDeck(false);
    }
  };

  const handleSelectSavedDeck = async (id: number) => {
    if (
      dirty &&
      !window.confirm(
        "Aprire un altro mazzo? Le modifiche non salvate della bozza corrente saranno sostituite.",
      )
    )
      return;
    const detail = await api.getDeck(id);
    setDeckId(detail.id);
    setDeckName(detail.name);
    setDeckArchetype(detail.archetype);
    setDeckItems(detail.cards);
    onDeckChange(detail);
  };

  const handleNewDeck = () => {
    if (
      dirty &&
      !window.confirm(
        "Creare una nuova bozza? Salva prima le modifiche per conservarle nel server.",
      )
    )
      return;
    setSavedFingerprint(
      fingerprint(`Nuovo Mazzo ${formatId.toUpperCase()}`, "midrange", []),
    );
    try {
      localStorage.removeItem(`aetherdeck.active.${formatId}`);
    } catch {}
    setDeckId(null);
    setDeckName(`Nuovo Mazzo ${formatId.toUpperCase()}`);
    setDeckArchetype("midrange");
    setDeckItems([]);
    onDeckChange(null);
  };

  const handleImportDeckText = async (text: string, importedName: string) => {
    if (
      dirty &&
      !window.confirm(
        "Importare la lista? Le modifiche non salvate della bozza corrente saranno sostituite.",
      )
    )
      throw new Error("Importazione annullata: la bozza corrente è invariata.");
    const res = await api.importDeck({
      text,
      format_id: formatId,
      name: importedName,
      archetype: deckArchetype,
      save_to_db: true,
    });
    if (res.deck) {
      setDeckId(res.deck.id);
      setDeckName(res.deck.name);
      setDeckItems(res.deck.cards);
      setSavedFingerprint(
        fingerprint(res.deck.name, res.deck.archetype, res.deck.cards),
      );
      onDeckChange(res.deck);
      const list = await api.listDecks(formatId);
      setSavedDecks(list);
      setSaveToast(
        res.unresolved_cards.length > 0
          ? `Importato! (${res.unresolved_cards.length} non trovate)`
          : "Mazzo importato e salvato!",
      );
      setTimeout(() => setSaveToast(null), 3500);
    }
  };

  // Grouping Mainboard & Sideboard for Visual Deck View (Requirement 4: per Tipo o per Curva)
  const groupedMainboard = useMemo(() => {
    const main = deckItems.filter((i) => i.board === "main");
    if (groupBy === "type") {
      const groups: Record<string, DeckCardItem[]> = {
        Creature: [],
        Planeswalker: [],
        "Instant & Sorcery": [],
        "Artifact & Enchantment": [],
        Land: [],
      };
      main.forEach((item) => {
        const frontType = (item.card.type_line || "").split("//")[0];
        if (frontType.includes("Land")) {
          groups["Land"].push(item);
        } else if (frontType.includes("Creature")) {
          groups["Creature"].push(item);
        } else if (frontType.includes("Planeswalker")) {
          groups["Planeswalker"].push(item);
        } else if (
          frontType.includes("Instant") ||
          frontType.includes("Sorcery")
        ) {
          groups["Instant & Sorcery"].push(item);
        } else {
          groups["Artifact & Enchantment"].push(item);
        }
      });
      return Object.entries(groups).filter(([, arr]) => arr.length > 0);
    } else {
      const groups: Record<string, DeckCardItem[]> = {
        "CMC 0-1": [],
        "CMC 2": [],
        "CMC 3": [],
        "CMC 4": [],
        "CMC 5+": [],
        Terre: [],
      };
      main.forEach((item) => {
        const frontType = (item.card.type_line || "").split("//")[0];
        if (frontType.includes("Land")) {
          groups["Terre"].push(item);
        } else {
          const cmc = Math.floor(castableManaValue(item.card));
          if (cmc <= 1) groups["CMC 0-1"].push(item);
          else if (cmc === 2) groups["CMC 2"].push(item);
          else if (cmc === 3) groups["CMC 3"].push(item);
          else if (cmc === 4) groups["CMC 4"].push(item);
          else groups["CMC 5+"].push(item);
        }
      });
      return Object.entries(groups).filter(([, arr]) => arr.length > 0);
    }
  }, [deckItems, groupBy]);

  const sideboardItems = useMemo(
    () =>
      deckItems.filter((i) => i.board === "side" || i.board === "companion"),
    [deckItems],
  );

  // Quick lookup of how many copies of each card are already in the deck
  const deckCountByOracle = useMemo(() => {
    const map: Record<string, { main: number; side: number }> = {};
    deckItems.forEach((i) => {
      if (!map[i.oracle_id]) map[i.oracle_id] = { main: 0, side: 0 };
      if (i.board === "main") map[i.oracle_id].main += i.quantity;
      else map[i.oracle_id].side += i.quantity;
    });
    return map;
  }, [deckItems]);

  const totalPages = Math.max(1, Math.ceil(totalCards / 36));

  return (
    <div className="h-[calc(100dvh-var(--header-h,3.75rem))] overflow-hidden max-lg:pb-16">
      {/* Mobile: counter and Save always reachable, whichever tab is open. */}
      <div
        role="region"
        aria-label="Stato del mazzo"
        className="lg:hidden fixed bottom-0 inset-x-0 z-40 flex items-center justify-between gap-3 border-t border-[#1E2638] bg-[#0E131D]/95 px-4 py-2 backdrop-blur"
      >
        <span className="text-sm font-mono-tech text-slate-200">
          Main {validation.mainboard_count}/60 · Side {validation.sideboard_count}/15
          {dirty && (
            <span className="block text-xs text-amber-300">Modifiche non salvate</span>
          )}
        </span>
        <button
          type="button"
          onClick={handleSaveDeck}
          disabled={savingDeck}
          className={`${dirty ? "btn-primary" : "btn-secondary"} min-h-11`}
        >
          <Save className="w-4 h-4" />
          {savingDeck ? "Salvataggio..." : "Salva"}
        </button>
      </div>
      <ResizableSplitPane
        storageKey="deckbuilder_main"
        defaultLeftPct={52}
        minLeftPct={25}
        maxLeftPct={75}
        className="h-full"
        mobileTabs={{
          first: "Cerca carte",
          second: `Mazzo · ${validation.mainboard_count}/60 · ${validation.sideboard_count}/15`,
        }}
        left={
          <div className="w-full h-full flex flex-col bg-[#0A0D14]">
            {/* Search & Filters Header */}
            <div className="p-3.5 bg-[#0E131D] border-b border-[#1E2638] space-y-2.5">
              {/* Row 1: Name Search + Oracle Rules Search + Advanced Toggle */}
              <div className="grid grid-cols-1 sm:grid-cols-12 gap-2">
                <div className="sm:col-span-5 relative">
                  <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    ref={nameInput}
                    type="text"
                    aria-label="Cerca per nome (scorciatoia /)"
                    value={nameQuery}
                    onChange={(e) => {
                      setNameQuery(e.target.value);
                      setPage(1);
                    }}
                    placeholder="Nome carta (es. Sheoldred, Counterspell)..."
                    className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-[#080A10] border border-[#222B40] text-xs text-white focus:outline-none focus:border-[#C8AA6E]"
                  />
                </div>

                <div className="sm:col-span-5 relative">
                  <Search className="w-3.5 h-3.5 text-sky-400/80 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={oracleQuery}
                    onChange={(e) => {
                      setOracleQuery(e.target.value);
                      setPage(1);
                    }}
                    placeholder="Testo regole Oracle (es. draw a card, ward)..."
                    className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-[#080A10] border border-[#222B40] text-xs text-white focus:outline-none focus:border-sky-400"
                  />
                </div>

                <div className="sm:col-span-2 flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
                    className={`flex-1 py-1.5 px-2 rounded-lg border text-xs font-medium flex items-center justify-center gap-1 cursor-pointer ${
                      showAdvancedFilters
                        ? "bg-[#1A2336] border-[#C8AA6E] text-[#F3E5C8]"
                        : "bg-[#121724] border-[#222B40] text-slate-300 hover:text-white"
                    }`}
                    title="Filtri avanzati (Forza, Costituzione, Rarità, Sottotipo)"
                  >
                    <Filter className="w-3.5 h-3.5" />
                    <span>Filtri</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleResetFilters}
                    className="p-1.5 rounded-lg bg-[#121724] hover:bg-[#1B2234] border border-[#222B40] text-slate-400 hover:text-white cursor-pointer"
                    title="Resetta tutti i filtri"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Row 2: WUBRG Color Filter + CMC Quick Pills + Type + Set Selector */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                {/* WUBRG + C Color Pills */}
                <div className="flex items-center gap-1 bg-[#080A10] p-1 rounded-lg border border-[#1E2638]">
                  {(["W", "U", "B", "R", "G", "C"] as const).map((col) => {
                    const active = selectedColors.includes(col);
                    return (
                      <button
                        key={col}
                        type="button"
                        onClick={() => toggleColor(col)}
                        className={`w-6 h-6 rounded flex items-center justify-center transition-all cursor-pointer ${
                          active
                            ? "bg-[#C8AA6E]/25 ring-1 ring-[#C8AA6E] scale-105"
                            : "opacity-55 hover:opacity-100 hover:bg-[#141A29]"
                        }`}
                        title={`Filtra colore ${col}`}
                      >
                        <i
                          className={`ms ms-${col.toLowerCase()} ms-cost ms-shadow text-xs`}
                        />
                      </button>
                    );
                  })}
                  <select
                    value={colorMode}
                    onChange={(e) => {
                      setColorMode(e.target.value as any);
                      setPage(1);
                    }}
                    className="bg-transparent text-[11px] font-mono-tech text-slate-300 pl-1 pr-0.5 focus:outline-none cursor-pointer"
                    title="Modalità filtro colore"
                  >
                    <option value="include" className="bg-[#0D111A]">
                      Include
                    </option>
                    <option value="exact" className="bg-[#0D111A]">
                      Esatti
                    </option>
                    <option value="at_most" className="bg-[#0D111A]">
                      Al più
                    </option>
                  </select>
                </div>

                {/* Mana Value (CMC) Quick Selector */}
                <div className="flex items-center gap-0.5 bg-[#080A10] p-1 rounded-lg border border-[#1E2638]">
                  <span className="text-[11px] font-mono-tech text-slate-400 px-1.5">
                    CMC:
                  </span>
                  {[0, 1, 2, 3, 4, 5, 6].map((val) => {
                    const active = cmcExact === val;
                    return (
                      <button
                        key={val}
                        type="button"
                        onClick={() => {
                          setPage(1);
                          setCmcExact(active ? null : val);
                        }}
                        className={`w-5 h-5 rounded text-[11px] font-mono-tech font-bold transition-colors cursor-pointer ${
                          active
                            ? "bg-[#C8AA6E] text-[#090B10]"
                            : "text-slate-400 hover:text-white hover:bg-[#151C2C]"
                        }`}
                      >
                        {val}
                      </button>
                    );
                  })}
                </div>

                {/* Type Dropdown */}
                <select
                  aria-label="Tipo di carta"
                  value={selectedType}
                  onChange={(e) => {
                    setSelectedType(e.target.value);
                    setPage(1);
                  }}
                  className="px-2.5 py-1.5 rounded-lg bg-[#080A10] border border-[#1E2638] text-xs text-slate-200 focus:outline-none focus:border-[#C8AA6E] cursor-pointer"
                >
                  <option value="">Tutti i Tipi</option>
                  {CARD_TYPES.filter(Boolean).map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>

                {/* Functional role (Scryfall Tagger) */}
                <select
                  aria-label="Funzione della carta"
                  value={selectedFunction}
                  onChange={(e) => {
                    setSelectedFunction(e.target.value);
                    setPage(1);
                  }}
                  className="px-2.5 py-1.5 rounded-lg bg-[#080A10] border border-[#1E2638] text-xs text-slate-200 focus:outline-none focus:border-[#C8AA6E] cursor-pointer"
                >
                  {FUNCTION_FILTERS.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.label}
                    </option>
                  ))}
                </select>

                {/* Admitted Sets Dropdown */}
                <select
                  aria-label="Set"
                  value={selectedSet}
                  onChange={(e) => {
                    setSelectedSet(e.target.value);
                    setPage(1);
                  }}
                  className="max-w-[165px] px-2.5 py-1.5 rounded-lg bg-[#080A10] border border-[#1E2638] text-xs text-slate-200 focus:outline-none focus:border-[#C8AA6E] truncate cursor-pointer"
                >
                  <option value="">
                    Tutti i Set ({formatId.toUpperCase()})
                  </option>
                  {(formatDetail?.legal_sets || []).map((s) => (
                    <option key={s.code} value={s.code}>
                      [{s.code.toUpperCase()}] {s.name}
                    </option>
                  ))}
                </select>

                {/* Primary Sort Dropdown (Always visible, defaults to Meta %) */}
                <select
                  aria-label="Ordinamento dei risultati"
                  value={sortBy}
                  onChange={(e) => {
                    setSortBy(e.target.value);
                    setPage(1);
                  }}
                  className="px-2.5 py-1.5 rounded-lg bg-[#080A10] border border-[#C8AA6E]/40 text-xs font-semibold text-[#F3E5C8] focus:outline-none focus:border-[#C8AA6E] cursor-pointer"
                  title="Ordina risultati di ricerca"
                >
                  <option value="meta_desc">★ Più Giocate nel Meta (%)</option>
                  <option value="cmc_asc">CMC Crescente</option>
                  <option value="cmc_desc">CMC Decrescente</option>
                  <option value="rarity_desc">Rarità (Mythic → Common)</option>
                  <option value="released_desc">Più Recenti</option>
                  <option value="name_asc">Nome (A-Z)</option>
                </select>
              </div>

              {activeFilters.length > 0 && (
                <ul className="flex flex-wrap gap-1.5" aria-label="Filtri attivi">
                  {activeFilters.map((f) => (
                    <li key={f.label}>
                      <button
                        type="button"
                        onClick={() => {
                          f.clear();
                          setPage(1);
                        }}
                        className="inline-flex items-center gap-1 rounded-full border border-[#C8AA6E]/40 bg-[#141A28] px-2 py-0.5 text-xs text-[#F3E5C8] min-h-6"
                        aria-label={`Rimuovi filtro ${f.label}`}
                      >
                        {f.label} <X className="w-3 h-3" aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {/* Row 3 (Collapsible): Advanced Filters (Power, Toughness, Rarity, Subtype, CMC Min/Max, Sort) */}
              {showAdvancedFilters && (
                <div className="pt-2 border-t border-[#1E2638] grid grid-cols-2 sm:grid-cols-6 gap-2 text-xs">
                  <div>
                    <label className="block text-[11px] font-mono-tech text-slate-400 mb-0.5">
                      Rarità
                    </label>
                    <select
                      value={selectedRarity}
                      onChange={(e) => {
                        setSelectedRarity(e.target.value);
                        setPage(1);
                      }}
                      className="w-full px-2 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white"
                    >
                      {RARITIES.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono-tech text-slate-400 mb-0.5">
                      Sottotipo (es. Goblin)
                    </label>
                    <input
                      type="text"
                      value={subtypeQuery}
                      onChange={(e) => {
                        setSubtypeQuery(e.target.value);
                        setPage(1);
                      }}
                      placeholder="Elf, Wizard, Aura..."
                      className="w-full px-2 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono-tech text-slate-400 mb-0.5">
                      CMC (Min - Max)
                    </label>
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        min={0}
                        max={20}
                        value={cmcMin}
                        onChange={(e) => {
                          setCmcMin(e.target.value);
                          setCmcExact(null);
                          setPage(1);
                        }}
                        placeholder="Min"
                        className="w-1/2 px-1.5 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white font-mono-tech"
                      />
                      <input
                        type="number"
                        min={0}
                        max={20}
                        value={cmcMax}
                        onChange={(e) => {
                          setCmcMax(e.target.value);
                          setCmcExact(null);
                          setPage(1);
                        }}
                        placeholder="Max"
                        className="w-1/2 px-1.5 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white font-mono-tech"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono-tech text-slate-400 mb-0.5">
                      Forza (Min - Max)
                    </label>
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        value={powerMin}
                        onChange={(e) => {
                          setPowerMin(e.target.value);
                          setPage(1);
                        }}
                        placeholder="Min"
                        className="w-1/2 px-1.5 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white font-mono-tech"
                      />
                      <input
                        type="number"
                        value={powerMax}
                        onChange={(e) => {
                          setPowerMax(e.target.value);
                          setPage(1);
                        }}
                        placeholder="Max"
                        className="w-1/2 px-1.5 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white font-mono-tech"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono-tech text-slate-400 mb-0.5">
                      Costituz. (Min - Max)
                    </label>
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        value={toughnessMin}
                        onChange={(e) => {
                          setToughnessMin(e.target.value);
                          setPage(1);
                        }}
                        placeholder="Min"
                        className="w-1/2 px-1.5 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white font-mono-tech"
                      />
                      <input
                        type="number"
                        value={toughnessMax}
                        onChange={(e) => {
                          setToughnessMax(e.target.value);
                          setPage(1);
                        }}
                        placeholder="Max"
                        className="w-1/2 px-1.5 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white font-mono-tech"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono-tech text-slate-400 mb-0.5">
                      Ordina per
                    </label>
                    <select
                      value={sortBy}
                      onChange={(e) => {
                        setSortBy(e.target.value);
                        setPage(1);
                      }}
                      className="w-full px-2 py-1 rounded bg-[#080A10] border border-[#222B40] text-xs text-white"
                    >
                      <option value="meta_desc">
                        ★ Più Giocate nel Meta (%)
                      </option>
                      <option value="cmc_asc">CMC Crescente</option>
                      <option value="cmc_desc">CMC Decrescente</option>
                      <option value="rarity_desc">
                        Rarità (Mythic → Common)
                      </option>
                      <option value="name_asc">Nome (A-Z)</option>
                      <option value="released_desc">Più Recenti</option>
                    </select>
                  </div>
                </div>
              )}
            </div>

            {/* Search Results Subheader */}
            <div className="px-4 py-2 bg-[#0B0E16] border-b border-[#181F2E] flex items-center justify-between text-xs">
              <span className="text-slate-400">
                Carte legali in{" "}
                <strong className="capitalize text-slate-200">
                  {formatId}
                </strong>
                :{" "}
                <strong className="font-mono-tech text-[#C8AA6E]">
                  {totalCards.toLocaleString("it-IT")}
                </strong>
              </span>

              <div className="flex items-center gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="p-1 rounded bg-[#141A28] hover:bg-[#1D2538] disabled:opacity-30 cursor-pointer"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <span className="font-mono-tech text-[11px] text-slate-300">
                  Pag. {page} / {totalPages}
                </span>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="p-1 rounded bg-[#141A28] hover:bg-[#1D2538] disabled:opacity-30 cursor-pointer"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Card Grid */}
            <div className="flex-1 overflow-y-auto p-3.5" aria-busy={searching}>
              {(searching || !searchedOnce) && searchResults.length === 0 ? (
                <div
                  className="h-64 flex items-center justify-center text-xs text-slate-400"
                  role="status"
                >
                  Ricerca carte nel catalogo…
                </div>
              ) : searchResults.length === 0 ? (
                <div className="h-64 flex flex-col items-center justify-center text-center gap-2">
                  <p className="text-sm text-slate-300 font-medium">
                    Nessuna carta trovata con i filtri selezionati.
                  </p>
                  <button
                    onClick={handleResetFilters}
                    className="px-3 py-1.5 rounded-lg bg-[#171F30] text-xs text-[#C8AA6E] border border-[#C8AA6E]/30 cursor-pointer"
                  >
                    Azzera filtri di ricerca
                  </button>
                </div>
              ) : (
                <div
                  className={`grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3 transition-opacity ${searching ? "opacity-60" : ""}`}
                >
                  {searchResults.map((card) => {
                    const imgUrl =
                      card.image_uris?.normal ||
                      card.image_uris?.small ||
                      card.card_faces?.[0]?.image_uris?.normal ||
                      "";
                    const counts = deckCountByOracle[card.oracle_id] || {
                      main: 0,
                      side: 0,
                    };
                    const totalInDeck = counts.main + counts.side;

                    return (
                      <div
                        key={card.oracle_id}
                        className="group relative rounded-xl bg-[#101521] border border-[#1F273B] hover:border-[#C8AA6E] transition-all overflow-hidden flex flex-col shadow-md"
                      >
                        {/* Card Image */}
                        <div
                          onClick={() => setInspectedCard(card)}
                          className="relative aspect-[63/88] w-full bg-[#07090E] overflow-hidden cursor-pointer"
                        >
                          {imgUrl ? (
                            <img
                              src={imgUrl}
                              alt={card.name}
                              loading="lazy"
                              className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-200"
                            />
                          ) : (
                            <div className="p-3 text-xs text-slate-400 flex flex-col justify-between h-full">
                              <div className="font-bold text-white">
                                {card.name}
                              </div>
                              <div className="text-[11px]">
                                {card.oracle_text}
                              </div>
                            </div>
                          )}

                          {/* Badge if already in deck */}
                          {totalInDeck > 0 && (
                            <div className="absolute top-2 left-2 px-2 py-0.5 rounded-md bg-[#C8AA6E] text-[#090B10] font-mono-tech font-extrabold text-xs shadow-lg">
                              {counts.main}M{" "}
                              {counts.side > 0 ? `/ ${counts.side}S` : ""}
                            </div>
                          )}

                          {/* Meta Presence Pill if present */}
                          {card.meta_info &&
                            card.meta_info.overall_presence_pct > 0 && (
                              <div className="absolute top-2 right-2 px-1.5 py-0.5 rounded bg-sky-950/90 border border-sky-500/50 text-sky-300 font-mono-tech text-[11px] font-bold">
                                Meta{" "}
                                {card.meta_info.overall_presence_pct.toFixed(0)}
                                %
                              </div>
                            )}

                          {/* Quick actions: always visible on touch screens, on hover or keyboard focus elsewhere */}
                          <div
                            className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/95 via-black/80 to-transparent opacity-100 [@media(hover:hover)]:opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity flex items-center justify-between gap-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <button
                              onClick={() => handleAddCard(card, "main", 1)}
                              className="flex-1 min-h-7 py-1.5 rounded bg-[#C8AA6E] hover:bg-[#DFC286] text-[#090B10] font-bold text-[11px] flex items-center justify-center gap-0.5 cursor-pointer shadow"
                              title="Aggiungi 1 copia al Mainboard"
                              aria-label={`Aggiungi ${card.name} al mainboard`}
                            >
                              <Plus className="w-3 h-3 stroke-[2.5]" /> Main
                            </button>
                            <button
                              onClick={() => handleAddCard(card, "side", 1)}
                              className="flex-1 min-h-7 py-1.5 rounded bg-[#182236] hover:bg-[#22304C] text-sky-300 border border-sky-500/40 font-semibold text-[11px] flex items-center justify-center gap-0.5 cursor-pointer shadow"
                              title="Aggiungi 1 copia alla Sideboard"
                              aria-label={`Aggiungi ${card.name} alla sideboard`}
                            >
                              <Plus className="w-3 h-3" /> Side
                            </button>
                            <button
                              onClick={() => setInspectedCard(card)}
                              className="p-1.5 min-h-7 rounded bg-[#141A29] hover:bg-[#1E273D] text-slate-200 border border-slate-600/40 cursor-pointer"
                              title="Info Carta & Statistiche Meta"
                              aria-label={`Dettagli di ${card.name}`}
                            >
                              <Info className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>

                        {/* Compact Footer under Card */}
                        <div className="px-2.5 py-1.5 bg-[#0D111B] flex items-center justify-between gap-1 text-[11px]">
                          <span
                            onClick={() => setInspectedCard(card)}
                            className="font-medium text-slate-200 truncate cursor-pointer hover:text-[#C8AA6E]"
                            title={card.name}
                          >
                            {card.name}
                          </span>
                          <div className="flex items-center gap-1 shrink-0">
                            <ManaCost cost={card.mana_cost} size="xs" />
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        }
        right={
          <div className="w-full h-full flex flex-col bg-[#080A0F]">
            {/* Deck Top Controls Bar */}
            <div className="p-3.5 bg-[#0E131D] border-b border-[#1E2638] space-y-2.5">
              <div className="px-4 py-2 text-xs border-b border-slate-800 flex flex-wrap gap-2 justify-between">
                <span className={dirty ? "text-amber-200" : "text-emerald-300"}>
                  {dirty
                    ? "● Modifiche non salvate nel server"
                    : deckId
                      ? `✓ Mazzo #${deckId} salvato`
                      : "Bozza locale · premi Salva per aggiungerla all’archivio"}
                </span>
                <span className="text-slate-400">
                  {dirty ? "Bozza recuperabile in questo browser. " : ""}Mazzi,
                  versioni e guide sono in “Mazzi e guide”.
                </span>
              </div>
              {/* Deck Name, Archetype, Color Badge & Saved Decks */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 flex-1 min-w-[220px]">
                  <input
                    type="text"
                    value={deckName}
                    onChange={(e) => setDeckName(e.target.value)}
                    className="flex-1 px-3 py-1.5 rounded-lg bg-[#080A10] border border-[#232D42] text-sm font-bold text-[#F3E5C8] focus:outline-none focus:border-[#C8AA6E]"
                    placeholder="Nome del mazzo..."
                  />
                  <select
                    value={deckArchetype}
                    onChange={(e) => setDeckArchetype(e.target.value)}
                    className="px-2.5 py-1.5 rounded-lg bg-[#080A10] border border-[#232D42] text-xs font-medium text-slate-200 focus:outline-none cursor-pointer"
                  >
                    {ARCHETYPES.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Color Combination Badge */}
                <div className="flex items-center gap-2 px-2.5 py-1 rounded-lg bg-[#111726] border border-[#222D44]">
                  <ColorBadges colors={deckColors} size="sm" />
                  <span className="text-xs font-semibold text-[#F3E5C8]">
                    {colorLabel}
                  </span>
                </div>
              </div>

              {/* Action Toolbar: Load Saved, Save, Import/Export, AI Build, Clear */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-1.5">
                  {savedDecks.length > 0 && (
                    <div className="flex items-center gap-1 bg-[#080A10] px-2 py-1 rounded-lg border border-[#1E2638]">
                      <FolderOpen className="w-3.5 h-3.5 text-[#C8AA6E]" />
                      <select
                        value={deckId || ""}
                        onChange={(e) => {
                          const val = Number(e.target.value);
                          if (val) handleSelectSavedDeck(val);
                        }}
                        className="bg-transparent text-xs text-slate-200 focus:outline-none max-w-[155px] truncate cursor-pointer"
                      >
                        <option value="" className="bg-[#0D111A]">
                          Mazzi salvati ({savedDecks.length})...
                        </option>
                        {savedDecks.map((d) => (
                          <option
                            key={d.id}
                            value={d.id}
                            className="bg-[#0D111A]"
                          >
                            {d.name} ({d.mainboard_count}/{d.sideboard_count})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={handleSaveDeck}
                    disabled={savingDeck}
                    className="px-3 py-1.5 rounded-lg bg-[#C8AA6E] hover:bg-[#DFC286] text-[#090B10] font-bold text-xs flex items-center gap-1.5 cursor-pointer shadow-sm"
                  >
                    <Save className="w-3.5 h-3.5" />
                    <span>{savingDeck ? "Salvataggio..." : "Salva"}</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setIsImportExportOpen(true)}
                    className="px-2.5 py-1.5 rounded-lg bg-[#141B2B] hover:bg-[#1D273E] border border-[#26324D] text-xs font-medium text-slate-200 flex items-center gap-1.5 cursor-pointer"
                  >
                    <FileUp className="w-3.5 h-3.5 text-[#C8AA6E]" />
                    <span>Import / Export</span>
                  </button>

                  {onNavigateToAI && (
                    <button
                      type="button"
                      onClick={onNavigateToAI}
                      className="px-2.5 py-1.5 rounded-lg bg-purple-950/60 hover:bg-purple-900/70 border border-purple-500/40 text-xs font-semibold text-purple-200 flex items-center gap-1 cursor-pointer"
                    >
                      <Sparkles className="w-3.5 h-3.5 text-purple-300" />
                      <span>AI Guide / Build</span>
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={handleNewDeck}
                    className="p-1.5 rounded-lg bg-[#131824] hover:bg-[#1D273E] border border-[#222B40] text-slate-300 hover:text-[#F3E5C8] cursor-pointer"
                    title="Nuovo mazzo vuoto"
                    aria-label="Nuovo mazzo vuoto"
                  >
                    <FilePlus2 className="w-3.5 h-3.5" />
                  </button>
                </div>

                {/* Grouping & View Mode Switcher */}
                <div className="flex items-center gap-1 bg-[#080A10] p-1 rounded-lg border border-[#1E2638] text-xs">
                  <button
                    type="button"
                    onClick={() => setGroupBy("type")}
                    aria-pressed={groupBy === "type"}
                    className={`px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer ${
                      groupBy === "type"
                        ? "bg-[#1C2539] text-[#F3E5C8]"
                        : "text-slate-400"
                    }`}
                  >
                    Per Tipo
                  </button>
                  <button
                    type="button"
                    onClick={() => setGroupBy("cmc")}
                    aria-pressed={groupBy === "cmc"}
                    className={`px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer ${
                      groupBy === "cmc"
                        ? "bg-[#1C2539] text-[#F3E5C8]"
                        : "text-slate-400"
                    }`}
                  >
                    Per Curva
                  </button>
                  <div className="w-px h-3.5 bg-[#1E2638] mx-0.5" />
                  <button
                    type="button"
                    onClick={() => setViewStyle("visual")}
                    aria-pressed={viewStyle === "visual"}
                    aria-label="Vista grafica a pile"
                    className={`p-1 rounded cursor-pointer ${
                      viewStyle === "visual"
                        ? "bg-[#1C2539] text-[#C8AA6E]"
                        : "text-slate-400"
                    }`}
                    title="Vista grafica carte"
                  >
                    <LayoutGrid className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewStyle("list")}
                    aria-pressed={viewStyle === "list"}
                    aria-label="Vista elenco compatto"
                    className={`p-1 rounded cursor-pointer ${
                      viewStyle === "list"
                        ? "bg-[#1C2539] text-[#C8AA6E]"
                        : "text-slate-400"
                    }`}
                    title="Vista tabella compatta"
                  >
                    <List className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {saveToast && (
                <div className="text-xs text-emerald-400 font-medium flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" /> {saveToast}
                </div>
              )}

              {/* Live Validation Status Bar (60/15, 4x limit, Banlist) */}
              <div
                className={`px-3 py-2 rounded-lg border flex flex-col gap-1.5 ${
                  deckItems.length === 0
                    ? "bg-slate-900/40 border-slate-700/60"
                    : validation.is_valid
                      ? "bg-emerald-950/30 border-emerald-700/40"
                      : "bg-amber-950/25 border-amber-700/40"
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    {deckItems.length === 0 ? null : validation.is_valid ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    ) : (
                      <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                    )}
                    <span className="font-bold text-slate-100">
                      {deckItems.length === 0
                        ? "Bozza vuota: aggiungi carte per iniziare"
                        : validation.is_valid
                          ? `Mazzo legale in ${formatId.toUpperCase()}`
                          : `Validazione ${formatId.toUpperCase()}`}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 font-mono-tech text-xs">
                    <span
                      className={
                        deckItems.length === 0
                          ? "text-slate-300"
                          : validation.mainboard_count === 60
                            ? "text-emerald-400 font-bold"
                            : validation.mainboard_count < 60
                              ? "text-amber-300 font-bold"
                              : "text-sky-300 font-bold"
                      }
                    >
                      Main: {validation.mainboard_count}/60
                    </span>
                    <span
                      className={
                        validation.sideboard_count <= 15
                          ? "text-sky-300 font-bold"
                          : "text-rose-400 font-bold"
                      }
                    >
                      Side: {validation.sideboard_count}/15
                    </span>
                    <span className="text-slate-400">
                      Avg CMC:{" "}
                      <strong className="text-[#F3E5C8]">
                        {analytics.avg_cmc_nonland}
                      </strong>
                    </span>
                  </div>
                </div>

                {deckItems.length > 0 && validation.issues.length > 0 && (
                  <div className="space-y-0.5 pt-1 border-t border-white/10 max-h-20 overflow-y-auto">
                    {validation.issues.map((iss, idx) => (
                      <div
                        key={idx}
                        className={`text-[11px] flex items-center gap-1.5 ${
                          iss.severity === "error"
                            ? "text-rose-300 font-medium"
                            : "text-amber-300/90"
                        }`}
                      >
                        <span>•</span>
                        <span>{iss.message}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Mainboard & Sideboard Cards Area */}
            <div className="flex-1 overflow-y-auto p-3.5 space-y-5 relative">
              {deckItems.length === 0 ? (
                <div className="h-56 rounded-xl border border-dashed border-[#232D42] flex flex-col items-center justify-center p-6 text-center gap-2">
                  <p className="text-sm font-semibold text-slate-300">
                    Il tuo mazzo è vuoto
                  </p>
                  <p className="text-xs text-slate-400 max-w-md">
                    Aggiungi carte dal catalogo Scryfall a sinistra cliccando su{" "}
                    <strong>+ Main</strong> o <strong>+ Side</strong>, oppure
                    importa una lista da MTG Arena / MTGO.
                  </p>
                  <button
                    onClick={() => setIsImportExportOpen(true)}
                    className="mt-1 px-3.5 py-1.5 rounded-lg bg-[#161E31] hover:bg-[#1F2A44] border border-[#C8AA6E]/40 text-xs font-semibold text-[#F3E5C8] cursor-pointer"
                  >
                    Importa lista o carica Mazzo Esempio (
                    {formatId.toUpperCase()})
                  </button>
                </div>
              ) : (
                <>
                  {/* MAINBOARD GROUPS */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {groupedMainboard.map(([groupTitle, items]) => {
                      const groupQty = items.reduce(
                        (acc, i) => acc + i.quantity,
                        0,
                      );
                      return (
                        <div
                          key={groupTitle}
                          className="rounded-xl bg-[#0D111A] border border-[#1E2638] p-3 space-y-2"
                        >
                          <div className="flex items-center justify-between border-b border-[#1A2234] pb-1.5">
                            <span className="text-xs font-bold uppercase tracking-wider text-[#C8AA6E]">
                              {groupTitle}
                            </span>
                            <span className="font-mono-tech text-xs font-bold text-slate-300">
                              {groupQty}
                            </span>
                          </div>

                          <div className="space-y-1">
                            {items.map((item) => {
                              const thumb =
                                item.card.image_uris?.art_crop ||
                                item.card.image_uris?.small ||
                                item.card.card_faces?.[0]?.image_uris
                                  ?.art_crop ||
                                "";
                              const fullImg =
                                item.card.image_uris?.normal ||
                                item.card.card_faces?.[0]?.image_uris?.normal ||
                                "";
                              const legStatus = (item.card as any)[
                                `legality_${formatId}`
                              ];
                              const isIllegal = legStatus !== "legal";

                              return (
                                <div
                                  key={`${item.oracle_id}-main`}
                                  onMouseEnter={() =>
                                    setHoveredCardImg(fullImg)
                                  }
                                  onMouseLeave={() => setHoveredCardImg(null)}
                                  className={`group relative rounded-lg px-2 py-1.5 flex items-center justify-between gap-2 transition-colors ${
                                    isIllegal
                                      ? "bg-rose-950/40 border border-rose-600/60"
                                      : "bg-[#121826] hover:bg-[#182134] border border-[#1D263B]"
                                  }`}
                                >
                                  {viewStyle === "visual" && thumb && (
                                    <img
                                      src={thumb}
                                      alt=""
                                      className="w-7 h-5 rounded object-cover shrink-0 border border-white/10"
                                    />
                                  )}

                                  <button
                                    type="button"
                                    onClick={() => setInspectedCard(item.card)}
                                    className="flex items-center gap-2 min-w-0 flex-1 cursor-pointer text-left"
                                    title={item.card_name}
                                  >
                                    <span className="font-mono-tech font-bold text-xs text-[#F3E5C8] w-4 text-center">
                                      {item.quantity}x
                                    </span>
                                    <span
                                      className={`text-xs font-medium truncate ${
                                        isIllegal
                                          ? "text-rose-300 line-through"
                                          : "text-slate-100"
                                      }`}
                                    >
                                      {item.card_name}
                                    </span>
                                  </button>

                                  {/* Right side: meta % + mana cost, swapped for the controls on hover/focus; touch screens always show controls */}
                                  <div className="flex items-center gap-1.5 shrink-0">
                                    <div className={ROW_INFO}>
                                      {item.card.meta_info &&
                                        item.card.meta_info
                                          .overall_presence_pct > 0 && (
                                          <span
                                            className="px-1.5 py-0.2 rounded bg-sky-950/80 border border-sky-700/40 text-sky-300 font-mono-tech text-[11px] font-bold"
                                            title={`Giocata nel ${item.card.meta_info.overall_presence_pct.toFixed(1)}% dei mazzi torneo`}
                                          >
                                            {item.card.meta_info.overall_presence_pct.toFixed(
                                              0,
                                            )}
                                            %
                                          </span>
                                        )}
                                      <ManaCost
                                        cost={item.card.mana_cost}
                                        size="xs"
                                      />
                                    </div>
                                    <div className={ROW_CONTROLS}>
                                      <button
                                        onClick={() =>
                                          handleAddCard(item.card, "main", -1)
                                        }
                                        className={
                                          ROW_BUTTON +
                                          " hover:bg-slate-700 text-slate-200"
                                        }
                                        title="Rimuovi 1 copia"
                                        aria-label={`Rimuovi una copia di ${item.card_name} dal mainboard`}
                                      >
                                        <Minus className="w-3 h-3" />
                                      </button>
                                      <button
                                        onClick={() =>
                                          handleAddCard(item.card, "main", 1)
                                        }
                                        className={
                                          ROW_BUTTON +
                                          " hover:bg-[#C8AA6E] hover:text-black text-slate-200"
                                        }
                                        title="Aggiungi 1 copia"
                                        aria-label={`Aggiungi una copia di ${item.card_name} al mainboard`}
                                      >
                                        <Plus className="w-3 h-3" />
                                      </button>
                                      <button
                                        onClick={() => handleMoveBoard(item)}
                                        className={
                                          ROW_BUTTON +
                                          " hover:bg-sky-800 text-sky-300"
                                        }
                                        title="Sposta in Sideboard"
                                        aria-label={`Sposta ${item.card_name} in sideboard`}
                                      >
                                        <ArrowLeftRight className="w-3 h-3" />
                                      </button>
                                      <button
                                        onClick={() =>
                                          handleRemoveCard(
                                            item.oracle_id,
                                            "main",
                                          )
                                        }
                                        className={
                                          ROW_BUTTON +
                                          " hover:bg-rose-800 text-rose-300"
                                        }
                                        title="Elimina dal mazzo"
                                        aria-label={`Elimina ${item.card_name} dal mainboard`}
                                      >
                                        <Trash2 className="w-3 h-3" />
                                      </button>
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* SIDEBOARD SECTION */}
                  <div className="rounded-xl bg-[#0D111A] border border-sky-900/40 p-3 space-y-2">
                    <div className="flex items-center justify-between border-b border-[#1A2234] pb-1.5">
                      <span className="text-xs font-bold uppercase tracking-wider text-sky-400">
                        Sideboard (Max 15)
                      </span>
                      <span className="font-mono-tech text-xs font-bold text-sky-300">
                        {validation.sideboard_count} / 15
                      </span>
                    </div>

                    {sideboardItems.length === 0 ? (
                      <p className="text-xs text-slate-400 py-2">
                        Nessuna carta in Sideboard. Usa il pulsante{" "}
                        <strong>+ Side</strong> sulle carte.
                      </p>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
                        {sideboardItems.map((item) => (
                          <div
                            key={`${item.oracle_id}-side`}
                            className="group rounded-lg px-2 py-1.5 bg-[#111726] hover:bg-[#172034] border border-[#1E2942] flex items-center justify-between gap-2"
                          >
                            <button
                              type="button"
                              onClick={() => setInspectedCard(item.card)}
                              className="flex items-center gap-2 min-w-0 flex-1 cursor-pointer text-left"
                              title={item.card_name}
                            >
                              <span className="font-mono-tech font-bold text-xs text-sky-300 w-4 text-center">
                                {item.quantity}x
                              </span>
                              <span className="text-xs font-medium text-slate-200 truncate">
                                {item.card_name}
                              </span>
                            </button>
                            <div className="flex items-center gap-1 shrink-0">
                              <div className={ROW_INFO}>
                                <ManaCost
                                  cost={item.card.mana_cost}
                                  size="xs"
                                />
                              </div>
                              <div className={ROW_CONTROLS}>
                                <button
                                  onClick={() =>
                                    handleAddCard(item.card, "side", -1)
                                  }
                                  className={
                                    ROW_BUTTON +
                                    " hover:bg-slate-700 text-slate-200"
                                  }
                                  title="Rimuovi 1 copia"
                                  aria-label={`Rimuovi una copia di ${item.card_name} dalla sideboard`}
                                >
                                  <Minus className="w-3 h-3" />
                                </button>
                                <button
                                  onClick={() =>
                                    handleAddCard(item.card, "side", 1)
                                  }
                                  className={
                                    ROW_BUTTON +
                                    " hover:bg-sky-500 hover:text-black text-slate-200"
                                  }
                                  title="Aggiungi 1 copia"
                                  aria-label={`Aggiungi una copia di ${item.card_name} alla sideboard`}
                                >
                                  <Plus className="w-3 h-3" />
                                </button>
                                <button
                                  onClick={() => handleMoveBoard(item)}
                                  className={
                                    ROW_BUTTON +
                                    " hover:bg-amber-700 text-amber-300"
                                  }
                                  title="Sposta in Mainboard"
                                  aria-label={`Sposta ${item.card_name} nel mainboard`}
                                >
                                  <ArrowLeftRight className="w-3 h-3" />
                                </button>
                                <button
                                  onClick={() =>
                                    handleRemoveCard(item.oracle_id, item.board)
                                  }
                                  className={
                                    ROW_BUTTON +
                                    " hover:bg-rose-800 text-rose-300"
                                  }
                                  title="Elimina dalla sideboard"
                                  aria-label={`Elimina ${item.card_name} dalla sideboard`}
                                >
                                  <Trash2 className="w-3 h-3" />
                                </button>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}

              {/* Floating Card Image Preview on Deck Hover */}
              {hoveredCardImg && (
                <div className="fixed bottom-6 left-[48%] -translate-x-full z-40 pointer-events-none hidden lg:block">
                  <img
                    src={hoveredCardImg}
                    alt="Preview"
                    className="w-52 rounded-xl shadow-[0_10px_40px_rgba(0,0,0,0.9)] border border-[#C8AA6E]/60"
                  />
                </div>
              )}

              {/* =================================================================
              DECK TELEMETRY & ANALYTICS PANEL (Mana Curve + Pips vs Sources)
             ================================================================= */}
              <div className="rounded-xl bg-[#0D111A] border border-[#1E2638] p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-[#F3E5C8]">
                    <BarChart2 className="w-4 h-4 text-[#C8AA6E]" />
                    <span>
                      Telemetria Mazzo: Curva di Mana & Bilanciamento Colori
                    </span>
                  </div>
                  <span className="font-mono-tech text-[11px] text-slate-400">
                    Spell:{" "}
                    <strong className="text-white">
                      {analytics.nonland_count}
                    </strong>{" "}
                    | Terre:{" "}
                    <strong className="text-[#C8AA6E]">
                      {analytics.land_count}
                    </strong>
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
                  {/* Mana Curve Bar Chart (7 cols) */}
                  <div className="md:col-span-7 bg-[#090C12] border border-[#192030] rounded-lg p-3">
                    <div className="flex items-center justify-between text-[11px] text-slate-400 mb-2">
                      <span>Curva di Mana (Escluse Terre)</span>
                      <div className="flex items-center gap-3 text-[11px]">
                        <span className="flex items-center gap-1">
                          <span className="w-2 h-2 rounded-xs bg-[#C8AA6E]" />{" "}
                          Creature
                        </span>
                        <span className="flex items-center gap-1">
                          <span className="w-2 h-2 rounded-xs bg-sky-500" />{" "}
                          Altre Magie
                        </span>
                      </div>
                    </div>

                    <div className="h-28 flex items-end justify-between gap-2 pt-4 px-1">
                      {["0", "1", "2", "3", "4", "5", "6+"].map((bucket) => {
                        const data = analytics.mana_curve?.[bucket] || {
                          creatures: 0,
                          spells: 0,
                          total: 0,
                        };
                        // Scale to the tallest bucket so the shape of the curve is readable.
                        const maxBar = Math.max(
                          1,
                          ...Object.values(analytics.mana_curve || {}).map(
                            (b) => b.total,
                          ),
                        );
                        const creatH = Math.min(
                          100,
                          (data.creatures / maxBar) * 100,
                        );
                        const spellH = Math.min(
                          100 - creatH,
                          (data.spells / maxBar) * 100,
                        );
                        return (
                          <div
                            key={bucket}
                            className="flex-1 flex flex-col items-center gap-1 h-full"
                          >
                            <span className="font-mono-tech text-[11px] text-slate-300">
                              {data.total > 0 ? data.total : ""}
                            </span>
                            <div className="w-full flex-1 bg-[#111622] rounded-t flex flex-col justify-end overflow-hidden border border-[#1D2538]">
                              {data.spells > 0 && (
                                <div
                                  style={{ height: `${spellH}%` }}
                                  className="w-full bg-sky-500/85 transition-all"
                                  title={`Magie CMC ${bucket}: ${data.spells}`}
                                />
                              )}
                              {data.creatures > 0 && (
                                <div
                                  style={{ height: `${creatH}%` }}
                                  className="w-full bg-[#C8AA6E] transition-all"
                                  title={`Creature CMC ${bucket}: ${data.creatures}`}
                                />
                              )}
                            </div>
                            <span className="font-mono-tech text-[11px] font-bold text-slate-400">
                              {bucket}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Color Pips vs Mana Sources (5 cols) */}
                  <div className="md:col-span-5 bg-[#090C12] border border-[#192030] rounded-lg p-3 space-y-2">
                    <div className="text-xs text-slate-400 flex items-center justify-between">
                      <span>Fonti di mana rispetto ai requisiti</span>
                      <span className="font-mono-tech">Karsten · 60 carte</span>
                    </div>
                    <ManaRequirements analysis={competitive} />
                  </div>
                </div>
                <InteractionSummary analysis={competitive} />
              </div>
            </div>
          </div>
        }
      />

      {undo && (
        <UndoToast
          message={undo.message}
          onUndo={() => setDeckItems(undo.items)}
          onDismiss={dismissUndo}
        />
      )}

      {/* Card Detail & Meta Info Modal */}
      <CardInfoModal
        card={inspectedCard}
        formatId={formatId}
        onClose={() => setInspectedCard(null)}
        onAddCard={(card, board, qty) => {
          handleAddCard(card, board, qty);
          setInspectedCard(null);
        }}
      />

      {/* Import / Export Arena & MTGO Modal */}
      <ImportExportModal
        isOpen={isImportExportOpen}
        onClose={() => setIsImportExportOpen(false)}
        formatId={formatId}
        arenaText={exportTexts.arena_format}
        mtgoText={exportTexts.mtgo_format}
        onImportText={handleImportDeckText}
      />
    </div>
  );
};
