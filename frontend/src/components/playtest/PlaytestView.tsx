import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeftRight,
  ChevronDown,
  Copy,
  Dices,
  Download,
  Eye,
  FlipHorizontal,
  Hand,
  Heart,
  Layers,
  Minus,
  Plus,
  RotateCcw,
  Search,
  Shuffle,
  Sparkles,
  Undo2,
  X,
} from "lucide-react";
import { api } from "../../api/client";
import type { Card, DeckDetail, DeckSummary, FormatId } from "../../types";
import { faceCard, canFlip } from "./cardState";
import {
  battlefield,
  newGame,
  shuffled,
  moved,
  played,
  keep,
  type Game,
  type Instance,
  type Zone,
} from "./playtestState";

const zones: Record<Zone, string> = {
  library: "Grimorio",
  hand: "Mano",
  permanents: "Permanenti",
  lands: "Terre",
  graveyard: "Cimitero",
  exile: "Esilio",
  sideboard: "Sideboard",
};
const imageOf = (card: Card) =>
  card.image_uris?.normal || card.card_faces?.[0]?.image_uris?.normal || "";
const empty: Game = {
  cards: [],
  turn: 1,
  life: 20,
  opponent: 20,
  mulligans: 0,
  opening: true,
  log: [],
};

export function PlaytestView({
  formatId,
  activeDeck,
  onSelectDeck,
}: {
  formatId: FormatId;
  activeDeck: DeckDetail | null;
  onSelectDeck: (deck: DeckDetail) => void;
}) {
  const [decks, setDecks] = useState<DeckSummary[]>([]),
    [game, setGame] = useState<Game>(empty),
    [past, setPast] = useState<Game[]>([]);
  const [selected, setSelected] = useState<string | null>(null),
    [bottom, setBottom] = useState<string[]>([]),
    [error, setError] = useState("");
  const [zoom, setZoom] = useState(88),
    [rightZone, setRightZone] = useState<Zone | "log">("graveyard"),
    [search, setSearch] = useState("");
  const [peek, setPeek] = useState(false),
    [sideDraft, setSideDraft] = useState<Instance[] | null>(null),
    [modal, setModal] = useState(false);
  const [tokens, setTokens] = useState<Card[]>([]),
    [tokenLoading, setTokenLoading] = useState(false),
    [tokenError, setTokenError] = useState("");
  const [tokenName, setTokenName] = useState(""),
    [tokenStats, setTokenStats] = useState("1/1"),
    [tokenText, setTokenText] = useState("");
  useEffect(() => {
    api
      .listDecks(formatId)
      .then(setDecks)
      .catch((e) => setError(e.message));
  }, [formatId, activeDeck?.id]);
  useEffect(() => {
    if (activeDeck) {
      setGame(newGame(activeDeck));
      setPast([]);
      setSelected(null);
      setBottom([]);
      setPeek(false);
    } else setGame(empty);
  }, [activeDeck?.id]);
  useEffect(() => {
    setTokens([]);
    setTokenError("");
  }, [selected]);
  const chosen = game.cards.find((c) => c.uid === selected);
  const counts = useMemo(
    () =>
      Object.fromEntries(
        Object.keys(zones).map((z) => [
          z,
          game.cards.filter((c) => c.zone === z).length,
        ]),
      ) as Record<Zone, number>,
    [game.cards],
  );
  const openingBlocked = game.opening && bottom.length !== game.mulligans;
  const commit = (fn: (g: Game) => Game, label: string) => {
    setPast((p) => [...p.slice(-29), game]);
    setGame((g) => {
      const ready = g.opening ? keep(g, bottom) : g;
      if (ready.opening) return g;
      const next = fn(ready);
      return {
        ...next,
        log: [`T${g.turn} · ${label}`, ...next.log].slice(0, 100),
      };
    });
    setPeek(false);
  };
  const move = (
    uid: string,
    zone: Zone,
    position: "top" | "bottom" = "bottom",
  ) => {
    if (openingBlocked || (game.opening && bottom.includes(uid))) return;
    const card = game.cards.find((c) => c.uid === uid);
    commit(
      (g) => ({ ...g, cards: moved(g.cards, uid, zone, position) }),
      `${card?.card.name} → ${zones[zone]}`,
    );
  };
  const play = (uid: string) => {
    if (openingBlocked || (game.opening && bottom.includes(uid))) return;
    const card = game.cards.find((c) => c.uid === uid);
    commit(
      (g) => ({ ...g, cards: played(g.cards, uid) }),
      `Giocata: ${card?.card.name}`,
    );
  };
  const tap = (uid: string) =>
    commit(
      (g) => ({
        ...g,
        cards: g.cards.map((c) =>
          c.uid === uid ? { ...c, tapped: !c.tapped } : c,
        ),
      }),
      "TAP / STAP",
    );
  const draw = () => {
    const top = game.cards.find((c) => c.zone === "library");
    if (top) move(top.uid, "hand");
    else setError("Grimorio vuoto: nessuna carta da pescare.");
  };
  const nextTurn = () =>
    commit((g) => {
      let drawn = false;
      return {
        ...g,
        turn: g.turn + 1,
        cards: g.cards.map((c) => {
          if (!drawn && c.zone === "library") {
            drawn = true;
            return { ...c, zone: "hand" };
          }
          return battlefield(c.zone) ? { ...c, tapped: false } : c;
        }),
      };
    }, "Nuovo turno: STAP e pesca");
  const untapAll = () =>
    commit(
      (g) => ({
        ...g,
        cards: g.cards.map((c) =>
          battlefield(c.zone) ? { ...c, tapped: false } : c,
        ),
      }),
      "STAP globale",
    );
  const undo = () => {
    if (!past.length) return;
    setGame(past[past.length - 1]);
    setPast((p) => p.slice(0, -1));
  };
  const mulligan = () => {
    if (game.opening && game.mulligans < 7) start(game.cards, game.mulligans + 1);
  };
  // Keyboard shortcuts: D draw, T next turn, U untap, M mulligan, Z undo.
  const shortcuts = useRef<Record<string, () => void>>({});
  shortcuts.current = {
    d: () => !openingBlocked && counts.library && draw(),
    t: () => !openingBlocked && nextTurn(),
    u: () => !openingBlocked && untapAll(),
    m: mulligan,
    z: undo,
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (
        e.altKey ||
        e.metaKey ||
        (e.ctrlKey && e.key.toLowerCase() !== "z") ||
        (el &&
          (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) ||
            el.isContentEditable)) ||
        document.querySelector('[aria-modal="true"]')
      )
        return;
      const action = shortcuts.current[e.key.toLowerCase()];
      if (action) {
        e.preventDefault();
        action();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const flip = (inst: Instance) => {
    const face = inst.face ? 0 : 1;
    const type = faceCard(inst.card, face).type_line;
    commit(
      (g) => ({
        ...g,
        cards: g.cards.map((c) =>
          c.uid === inst.uid
            ? {
                ...c,
                face,
                zone: battlefield(c.zone)
                  ? type.includes("Land")
                    ? "lands"
                    : "permanents"
                  : c.zone,
              }
            : c,
        ),
      }),
      `Gira: ${faceCard(inst.card, face).name}`,
    );
  };
  const createToken = (card: Card, face = 0) => {
    if (openingBlocked) return;
    const uid = crypto.randomUUID();
    commit(
      (g) => ({
        ...g,
        cards: [
          ...g.cards,
          {
            uid,
            card,
            face,
            zone: "permanents",
            isToken: true,
            tapped: false,
            counters: 0,
          },
        ],
      }),
      `Pedina creata: ${card.name}`,
    );
    setSelected(uid);
  };
  const fetchTokens = async () => {
    if (!chosen) return;
    const uid = chosen.uid;
    setTokenLoading(true);
    setTokenError("");
    try {
      const t = await api.getTokens(chosen.card.oracle_id);
      setTokens(t);
      if (!t.length)
        setTokenError(
          "Nessuna pedina collegata su Scryfall. Puoi crearne una personalizzata.",
        );
    } catch (e: any) {
      setTokenError(e.message);
    } finally {
      setTokenLoading(false);
    }
  };
  const start = (configuration?: Instance[], mulligans = 0) => {
    if (activeDeck) {
      setGame(newGame(activeDeck, mulligans, configuration));
      setPast([]);
      setBottom([]);
      setSelected(null);
      setPeek(false);
    }
  };
  const dropped = (event: React.DragEvent, zone: Zone) => {
    event.preventDefault();
    if (openingBlocked) return;
    const uid =
      event.dataTransfer.getData("text/mtg-uid") ||
      event.dataTransfer.getData("text/plain");
    if (!uid) return;
    const card = game.cards.find((c) => c.uid === uid);
    if (card?.zone === "hand" && battlefield(zone)) {
      // Playing from hand follows the same routing as clicking: lands to the
      // land lane, permanents to the board, instants and sorceries to graveyard.
      play(uid);
    } else {
      move(uid, zone);
    }
  };
  const cardTile = (inst: Instance) => {
    const face = faceCard(inst.card, inst.face),
      img = imageOf(face),
      marked = bottom.includes(inst.uid);
    return (
      <div
        key={inst.uid}
        data-testid="playtest-card"
        data-card-name={face.name}
        data-zone={inst.zone}
        className={`shrink-0 rounded-xl border p-1.5 bg-[#101a28] ${marked ? "border-amber-300 ring-2 ring-amber-400" : selected === inst.uid ? "border-sky-300" : "border-slate-700"}`}
        style={{ width: zoom + 12 }}
        draggable={!openingBlocked}
        onDragStart={(e) => {
          e.dataTransfer.setData("text/mtg-uid", inst.uid);
          e.dataTransfer.setData("text/plain", inst.uid);
          e.dataTransfer.effectAllowed = "move";
        }}
      >
        <button
          className="relative block w-full aspect-[63/88] rounded-lg overflow-hidden bg-[#172435] cursor-pointer"
          aria-label={`${battlefield(inst.zone) ? (inst.tapped ? "Stappa" : "Tappa") : game.opening && game.mulligans ? "Seleziona per il fondo" : "Gioca"} ${face.name}`}
          onClick={() => {
            if (game.opening && inst.zone === "hand" && game.mulligans) {
              setBottom((b) =>
                b.includes(inst.uid)
                  ? b.filter((i) => i !== inst.uid)
                  : b.length < game.mulligans
                    ? [...b, inst.uid]
                    : b,
              );
            } else if (battlefield(inst.zone)) {
              tap(inst.uid);
            } else {
              play(inst.uid);
            }
          }}
        >
          {img ? (
            <img
              src={img}
              alt={face.name}
              loading="lazy"
              className={`w-full h-full object-cover transition-transform ${inst.tapped ? "rotate-12 scale-90 opacity-70" : ""}`}
            />
          ) : (
            <div className="p-3 h-full flex flex-col justify-between text-sm">
              <strong>{face.name}</strong>
              <span className="text-xs">{face.oracle_text}</span>
              <b>{face.power && `${face.power}/${face.toughness}`}</b>
            </div>
          )}
          {inst.tapped && (
            <span className="absolute top-2 left-2 rounded bg-amber-300 text-black text-xs px-2 font-bold">
              TAP
            </span>
          )}
          {inst.isToken && (
            <span className="absolute top-2 right-2 rounded bg-purple-800 text-white text-xs px-1">
              Pedina
            </span>
          )}
          {!!inst.counters && (
            <span className="absolute bottom-2 right-2 rounded-full bg-amber-300 text-black text-sm px-2 font-bold">
              {inst.counters > 0 ? "+" : ""}
              {inst.counters}
            </span>
          )}
          {marked && (
            <span className="absolute inset-0 bg-amber-900/60 flex items-center justify-center text-amber-100 font-bold">
              IN FONDO
            </span>
          )}
        </button>
        <div className="flex items-center gap-1 pt-1">
          <p
            className="text-[11px] text-slate-200 truncate flex-1"
            title={face.name}
          >
            {face.name}
          </p>
          <button
            className="shrink-0 min-w-7 min-h-7 rounded-md bg-[#1b2a3d] border border-slate-600 text-slate-100 hover:bg-[#30445c]"
            aria-label={`Azioni ${face.name}`}
            onClick={() => {
              setSelected(inst.uid);
              setModal(true);
            }}
          >
            •••
          </button>
        </div>
      </div>
    );
  };
  const zone = (id: "permanents" | "hand", help: string) => {
    const lanes: { id: Zone; label: string; description: string }[] =
      id === "permanents"
        ? [
            {
              id: "permanents",
              label: "Creature e altri permanenti",
              description: "Minacce, artefatti, incantesimi e pedine",
            },
            {
              id: "lands",
              label: "Terre e fonti",
              description: "Mana disponibile e terre tappate",
            },
          ]
        : [{ id: "hand", label: "", description: "" }];
    return (
      <section
        className="rounded-xl border border-slate-700 bg-[#0c1420] p-3 md:p-4"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => dropped(e, id)}
        aria-label={zones[id]}
      >
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <h2 className="font-semibold text-sm text-slate-100">
            {id === "permanents" ? "Campo di battaglia" : zones[id]}{" "}
            <span className="text-slate-400">
              (
              {id === "permanents"
                ? counts.permanents + counts.lands
                : counts[id]}
              )
            </span>
          </h2>
          <span className="text-xs text-slate-400">{help}</span>
        </div>
        <div className="space-y-2">
          {lanes.map((lane) => (
            <div
              key={lane.id}
              data-testid={`lane-${lane.id}`}
              className={
                id === "permanents"
                  ? "rounded-lg border border-slate-700/70 bg-[#101b2a] px-3 py-2"
                  : ""
              }
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.stopPropagation();
                dropped(e, lane.id);
              }}
            >
              {lane.label && (
                <div className="flex flex-wrap items-baseline gap-2 mb-2">
                  <h3 className="text-xs font-bold text-slate-100">
                    {lane.label}{" "}
                    <span className="text-slate-400">({counts[lane.id]})</span>
                  </h3>
                  <span className="text-xs text-slate-400">
                    {lane.description}
                  </span>
                </div>
              )}
              <div
                className="flex gap-2 overflow-x-auto pb-2 min-h-16 items-start"
                aria-label={lane.label || "Carte in mano"}
              >
                {game.cards.filter((c) => c.zone === lane.id).map(cardTile)}
                {!counts[lane.id] && (
                  <p className="self-center py-2 text-xs text-slate-400">
                    {lane.id === "hand"
                      ? "Nessuna carta in mano."
                      : "Trascina qui una carta o giocala dalla mano."}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    );
  };
  const chosenFace = chosen ? faceCard(chosen.card, chosen.face) : null;
  return (
    <div className="max-w-[1900px] mx-auto p-3 md:px-5 md:py-3 space-y-3">
      <div className="flex flex-wrap justify-between items-center gap-3">
        <div>
          <h1 className="text-lg font-bold flex gap-2 items-center">
            <Dices className="text-emerald-300" />
            Playtest
          </h1>
          <p className="text-xs text-slate-400">
            {formatId.toUpperCase()} · Playtest manuale, senza modificare il
            mazzo
          </p>
        </div>
        <label className="text-sm text-slate-300">
          Mazzo{" "}
          <select
            aria-label="Mazzo playtest"
            className="field ml-2 max-w-72"
            value={activeDeck?.id || ""}
            onChange={async (e) => {
              if (!e.target.value) return;
              try {
                onSelectDeck(await api.getDeck(Number(e.target.value)));
              } catch (err: any) {
                setError(err.message);
              }
            }}
          >
            <option value="">Seleziona un mazzo…</option>
            {decks.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} · {d.mainboard_count}/{d.sideboard_count}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <div className="notice-error flex justify-between gap-3" role="alert">
          {error}
          <button onClick={() => setError("")} aria-label="Chiudi errore">
            <X size={16} />
          </button>
        </div>
      )}
      {!activeDeck ? (
        <div className="panel text-center py-16">
          <Layers className="mx-auto text-amber-200 mb-4" size={32} />
          <h2 className="text-xl font-bold">Scegli un mazzo per iniziare</h2>
          <p className="text-slate-400 mt-3">
            Usa il selettore qui sopra. Puoi creare, importare o ritrovare le
            tue liste in “Mazzi e guide”.
          </p>
        </div>
      ) : (
        <>
          {!activeDeck.validation.is_valid && (
            <p className="panel text-sm text-amber-200">
              Lista da verificare nel Deck Builder. Puoi comunque esplorarla in
              questo ambiente manuale.
            </p>
          )}
          <div className="panel p-2! flex items-center gap-2 overflow-x-auto [&>button]:shrink-0 [&>div]:shrink-0">
            {(["life", "opponent"] as const).map((l) => (
              <div
                className="flex items-center gap-2 rounded-lg bg-black/25 px-3 py-1"
                key={l}
              >
                <Heart
                  size={15}
                  className={
                    l === "life" ? "text-emerald-300" : "text-rose-300"
                  }
                />
                <span className="text-xs text-slate-400">
                  {l === "life" ? "Tu" : "Avversario"}
                </span>
                <button
                  className="p-1"
                  aria-label={`Riduci vite ${l}`}
                  onClick={() =>
                    commit((g) => ({ ...g, [l]: g[l] - 1 }), "Vite −1")
                  }
                >
                  <Minus size={14} />
                </button>
                <strong className="text-lg tabular-nums min-w-6 text-center">
                  {game[l]}
                </strong>
                <button
                  className="p-1"
                  aria-label={`Aumenta vite ${l}`}
                  onClick={() =>
                    commit((g) => ({ ...g, [l]: g[l] + 1 }), "Vite +1")
                  }
                >
                  <Plus size={14} />
                </button>
              </div>
            ))}
            <button
              className="btn-primary"
              onClick={draw}
              disabled={openingBlocked || !counts.library}
              aria-keyshortcuts="D"
              title="Scorciatoia: D"
            >
              <Layers size={15} />
              Pesca 1 ({counts.library})
            </button>
            <button
              className="btn-secondary"
              disabled={openingBlocked}
              onClick={nextTurn}
              aria-keyshortcuts="T"
              title="Scorciatoia: T"
            >
              Turno {game.turn + 1} · STAP + pesca
            </button>
            <button
              className="btn-secondary"
              disabled={openingBlocked}
              onClick={untapAll}
              aria-keyshortcuts="U"
              title="Scorciatoia: U"
            >
              STAP tutto
            </button>
            <button
              className="btn-secondary"
              onClick={() => {
                setSideDraft(game.cards.map((c) => ({ ...c })));
              }}
            >
              <ArrowLeftRight size={15} />
              Sideboard ({counts.sideboard})
            </button>
            <button className="btn-secondary" onClick={() => start()}>
              <RotateCcw size={15} />
              Nuova partita
            </button>
            <button
              className="btn-secondary"
              disabled={!past.length}
              onClick={undo}
              aria-keyshortcuts="Z Control+Z"
              title="Scorciatoia: Z"
            >
              <Undo2 size={15} />
              Annulla
            </button>
            <p className="text-xs text-slate-400" aria-hidden="true">
              Tasti: D pesca · T turno · U stappa · M mulligan · Z annulla
            </p>
            <label className="ml-auto flex shrink-0 items-center gap-2 text-xs text-slate-400">
              Carte{" "}
              <input
                aria-label="Dimensione carte"
                type="range"
                min={80}
                max={184}
                step={8}
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
              />
              {zoom}px
            </label>
          </div>
          {game.opening && (
            <div className="rounded-xl border border-amber-500/50 bg-amber-950/25 p-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <strong className="text-amber-200">
                  Mano iniziale · London mulligan {game.mulligans}
                </strong>
                <p className="text-sm text-slate-300 mt-1">
                  {game.mulligans
                    ? `Seleziona ${game.mulligans} carte in mano da mettere in fondo (${bottom.length}/${game.mulligans}), poi conferma.`
                    : "Esamina la mano: puoi tenerla oppure iniziare subito a giocare; la prima azione la conferma automaticamente."}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  className="btn-secondary"
                  disabled={game.mulligans >= 7}
                  onClick={mulligan}
                  aria-keyshortcuts="M"
                  title="Scorciatoia: M"
                >
                  Mulligan a {Math.max(0, 6 - game.mulligans)}
                </button>
                <button
                  className="btn-primary"
                  disabled={bottom.length !== game.mulligans}
                  onClick={() => {
                    setGame((g) => keep(g, bottom));
                    setBottom([]);
                    setPast([]);
                  }}
                >
                  Tieni mano ({7 - game.mulligans})
                </button>
              </div>
            </div>
          )}
          <div className="grid xl:grid-cols-[minmax(0,1fr)_340px] gap-4 items-start">
            <div className="space-y-4 min-w-0">
              {zone(
                "permanents",
                "Clicca una carta per TAP/STAP; usa ••• per le azioni",
              )}
              {zone(
                "hand",
                game.opening && game.mulligans
                  ? "Clicca le immagini per scegliere il fondo"
                  : "Clicca la carta per giocarla; usa ••• per informazioni",
              )}
            </div>
            <aside className="panel p-3! space-y-4 xl:sticky xl:top-24 min-w-0">
              <div className="grid grid-cols-2 gap-2">
                {(["graveyard", "exile", "sideboard", "library"] as Zone[]).map(
                  (z) => (
                    <button
                      key={z}
                      className={
                        rightZone === z ? "btn-primary" : "btn-secondary"
                      }
                      onClick={() => {
                        setRightZone(z);
                        setSearch("");
                      }}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => dropped(e, z)}
                    >
                      {zones[z]} ({counts[z]})
                    </button>
                  ),
                )}
              </div>
              <div className="flex gap-2">
                <button
                  className="btn-secondary flex-1"
                  onClick={() => setRightZone("log")}
                >
                  Registro (T{game.turn})
                </button>
                <button
                  className="btn-secondary"
                  disabled={openingBlocked}
                  onClick={() =>
                    commit(
                      (g) => ({
                        ...g,
                        cards: [
                          ...shuffled(
                            g.cards.filter((c) => c.zone === "library"),
                          ),
                          ...g.cards.filter((c) => c.zone !== "library"),
                        ],
                      }),
                      "Grimorio mescolato",
                    )
                  }
                  title="Mescola grimorio"
                >
                  <Shuffle size={16} />
                </button>
              </div>
              {rightZone === "log" ? (
                <div className="space-y-2 max-h-[70vh] overflow-y-auto text-xs text-slate-400">
                  {game.log.map((line, i) => (
                    <p key={i}>{line}</p>
                  ))}
                </div>
              ) : (
                <>
                  <label className="flex gap-2 items-center">
                    <Search size={15} />
                    <input
                      className="field w-full"
                      aria-label={`Cerca in ${zones[rightZone]}`}
                      placeholder={`Cerca in ${zones[rightZone].toLowerCase()}`}
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </label>
                  {rightZone === "library" && (
                    <div className="space-y-2">
                      <button
                        className="btn-secondary w-full"
                        disabled={openingBlocked || !counts.library}
                        onClick={() => setPeek((v) => !v)}
                      >
                        <Eye size={15} />
                        {peek ? "Nascondi" : "Guarda la prima · Scry / Surveil"}
                      </button>
                      {peek &&
                        (() => {
                          const top = game.cards.find(
                            (c) => c.zone === "library",
                          );
                          return top ? (
                            <div className="panel p-3! text-sm">
                              <p className="text-sky-200 mb-3">
                                {top.card.name}
                              </p>
                              <div className="flex gap-2">
                                <button
                                  className="btn-secondary"
                                  onClick={() =>
                                    move(top.uid, "library", "bottom")
                                  }
                                >
                                  In fondo
                                </button>
                                <button
                                  className="btn-secondary"
                                  onClick={() => move(top.uid, "graveyard")}
                                >
                                  Surveil: cimitero
                                </button>
                              </div>
                            </div>
                          ) : null;
                        })()}
                    </div>
                  )}
                  <div className="max-h-[65vh] overflow-y-auto space-y-2">
                    {game.cards
                      .filter(
                        (c) =>
                          c.zone === rightZone &&
                          c.card.name
                            .toLowerCase()
                            .includes(search.toLowerCase()),
                      )
                      .map((inst) => (
                        <div
                          key={inst.uid}
                          className="rounded-lg border border-slate-800 bg-[#0c1420] p-2 flex gap-3 items-center"
                        >
                          <button
                            aria-label={`Esamina ${inst.card.name}`}
                            className="shrink-0"
                            onClick={() => {
                              setSelected(inst.uid);
                              setModal(true);
                            }}
                          >
                            {imageOf(inst.card) ? (
                              <img
                                src={imageOf(inst.card)}
                                alt=""
                                className="w-12 rounded"
                                loading="lazy"
                              />
                            ) : (
                              <Layers size={24} />
                            )}
                          </button>
                          <div className="min-w-0 flex-1">
                            <button
                              className="text-sm text-left text-sky-200"
                              onClick={() => {
                                setSelected(inst.uid);
                                setModal(true);
                              }}
                            >
                              {inst.card.name}
                            </button>
                            <div className="flex flex-wrap gap-2 mt-2">
                              <button
                                className="btn-secondary px-2! py-1! text-xs!"
                                disabled={openingBlocked}
                                onClick={() => move(inst.uid, "hand")}
                              >
                                In mano
                              </button>
                              <button
                                className="btn-secondary px-2! py-1! text-xs!"
                                disabled={openingBlocked}
                                onClick={() => play(inst.uid)}
                              >
                                Gioca
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                    {!counts[rightZone] && (
                      <p className="text-sm text-slate-400 py-8 text-center">
                        Zona vuota
                      </p>
                    )}
                  </div>
                </>
              )}
            </aside>
          </div>
        </>
      )}
      {modal && chosen && chosenFace && (
        <div className="modal-backdrop" onClick={() => setModal(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Azioni carta"
            className="panel max-w-4xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between gap-3 mb-5">
              <div>
                <p className="eyebrow">
                  {zones[chosen.zone]} · {chosen.isToken ? "Pedina" : "Carta"}
                </p>
                <h2 className="text-xl font-bold mt-1">{chosenFace.name}</h2>
              </div>
              <button
                className="btn-secondary"
                onClick={() => setModal(false)}
                aria-label="Chiudi azioni carta"
              >
                <X size={16} />
                Chiudi
              </button>
            </div>
            <div className="grid md:grid-cols-[240px_minmax(0,1fr)] gap-6">
              <div>
                {imageOf(chosenFace) ? (
                  <img
                    src={imageOf(chosenFace)}
                    alt={chosenFace.name}
                    className="w-full rounded-xl max-w-60 mx-auto"
                  />
                ) : (
                  <div className="panel text-center py-12">
                    <h3>{chosenFace.name}</h3>
                    <p>
                      {chosenFace.power}/{chosenFace.toughness}
                    </p>
                  </div>
                )}
                {canFlip(chosen.card) && (
                  <button
                    className="btn-primary mt-3 w-full"
                    onClick={() => flip(chosen)}
                  >
                    <FlipHorizontal size={16} />
                    Gira carta · {chosen.face ? "fronte" : "retro"}
                  </button>
                )}
              </div>
              <div className="space-y-4">
                <p className="text-sm text-sky-200">
                  {chosenFace.type_line}{" "}
                  {chosenFace.power &&
                    `· ${chosenFace.power}/${chosenFace.toughness}`}
                </p>
                <p className="text-sm text-slate-300 whitespace-pre-line leading-relaxed">
                  {chosenFace.oracle_text}
                </p>
                {openingBlocked ? (
                  <p className="text-amber-200 text-sm">
                    Conferma “Tieni mano” prima di spostare carte o creare
                    pedine. Puoi esaminare entrambe le facce.
                  </p>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-2">
                      {battlefield(chosen.zone) ? (
                        <>
                          <button
                            className="btn-primary"
                            onClick={() => tap(chosen.uid)}
                          >
                            {chosen.tapped ? "STAP" : "TAP"}
                          </button>
                          <button
                            className="btn-secondary"
                            onClick={() =>
                              commit(
                                (g) => ({
                                  ...g,
                                  cards: g.cards.map((c) =>
                                    c.uid === chosen.uid
                                      ? { ...c, counters: c.counters + 1 }
                                      : c,
                                  ),
                                }),
                                "Segnalino +1",
                              )
                            }
                          >
                            +1 segnalino ({chosen.counters})
                          </button>
                          <button
                            className="btn-secondary"
                            onClick={() =>
                              commit(
                                (g) => ({
                                  ...g,
                                  cards: g.cards.map((c) =>
                                    c.uid === chosen.uid
                                      ? { ...c, counters: c.counters - 1 }
                                      : c,
                                  ),
                                }),
                                "Segnalino −1",
                              )
                            }
                          >
                            −1 segnalino
                          </button>
                          <button
                            className="btn-secondary"
                            onClick={() =>
                              createToken(chosen.card, chosen.face)
                            }
                          >
                            <Copy size={15} />
                            Copia pedina
                          </button>
                        </>
                      ) : (
                        <button
                          className="btn-primary"
                          onClick={() => {
                            play(chosen.uid);
                            setModal(false);
                          }}
                        >
                          Gioca faccia visibile
                        </button>
                      )}
                    </div>
                    <label className="block text-sm text-slate-400">
                      Sposta in{" "}
                      <select
                        aria-label="Sposta carta in"
                        className="field ml-2"
                        value=""
                        onChange={(e) => {
                          move(chosen.uid, e.target.value as Zone);
                          setModal(false);
                        }}
                      >
                        <option value="">Scegli zona…</option>
                        {(Object.keys(zones) as Zone[])
                          .filter((z) => z !== chosen.zone && z !== "sideboard")
                          .map((z) => (
                            <option key={z} value={z}>
                              {z === "library"
                                ? "Fondo del grimorio"
                                : zones[z]}
                            </option>
                          ))}
                      </select>
                    </label>
                    <div className="border-t border-slate-800 pt-4">
                      <h3>Pedine generate da questa carta</h3>
                      <button
                        className="btn-secondary mt-3"
                        disabled={tokenLoading || chosen.isToken}
                        onClick={fetchTokens}
                      >
                        {tokenLoading
                          ? "Ricerca pedine…"
                          : "Cerca pedine ufficiali"}
                      </button>
                      {tokenError && (
                        <p className="text-sm text-amber-200 mt-3">
                          {tokenError}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-3 mt-3">
                        {tokens.map((t) => (
                          <button
                            key={t.scryfall_id}
                            className="w-28 text-xs text-sky-200"
                            onClick={() => createToken(t)}
                          >
                            {imageOf(t) && (
                              <img
                                src={imageOf(t)}
                                alt={t.name}
                                className="rounded-lg mb-2"
                              />
                            )}
                            Crea {t.name}{" "}
                            {t.power && `${t.power}/${t.toughness}`}
                          </button>
                        ))}
                      </div>
                    </div>
                    <details className="border-t border-slate-800 pt-4">
                      <summary className="text-sky-200 text-sm cursor-pointer">
                        Crea pedina personalizzata
                      </summary>
                      <div className="space-y-3 mt-3">
                        <input
                          className="field w-full"
                          aria-label="Nome pedina"
                          placeholder="Goblin Shaman rosso"
                          value={tokenName}
                          onChange={(e) => setTokenName(e.target.value)}
                        />
                        <input
                          className="field w-full"
                          aria-label="Forza e costituzione pedina"
                          placeholder="2/2"
                          value={tokenStats}
                          onChange={(e) => setTokenStats(e.target.value)}
                        />
                        <textarea
                          className="field w-full"
                          aria-label="Abilità pedina"
                          placeholder="Abilità, colori e promemoria"
                          value={tokenText}
                          onChange={(e) => setTokenText(e.target.value)}
                        />
                        <button
                          className="btn-primary"
                          disabled={!tokenName.trim()}
                          onClick={() =>
                            createToken({
                              ...chosen.card,
                              oracle_id: crypto.randomUUID(),
                              scryfall_id: crypto.randomUUID(),
                              name: tokenName.trim(),
                              type_line: "Token",
                              oracle_text: tokenText,
                              layout: "normal",
                              card_faces: [],
                              image_uris: {},
                              power: tokenStats.split("/")[0],
                              toughness: tokenStats.split("/")[1],
                            })
                          }
                        >
                          Crea pedina
                        </button>
                      </div>
                    </details>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
      {sideDraft && (
        <div className="modal-backdrop">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Configurazione sideboard"
            className="panel max-w-5xl w-full max-h-[90vh] overflow-y-auto"
          >
            <h2 className="text-xl font-bold">
              Prepara la partita post-sideboard
            </h2>
            <p className="text-sm text-slate-400 my-3">
              Clicca una copia per spostarla. Sono richieste almeno 60 carte
              main e al massimo 15 side; le pedine vengono rimosse dalla nuova
              partita.
            </p>
            <div className="grid md:grid-cols-2 gap-5 my-5">
              {[false, true].map((side) => (
                <div key={String(side)}>
                  <h3 className="mb-3">
                    {side ? "Sideboard" : "Mainboard"} (
                    {
                      sideDraft.filter(
                        (c) => !c.isToken && (c.zone === "sideboard") === side,
                      ).length
                    }
                    )
                  </h3>
                  <div className="max-h-[45vh] overflow-y-auto space-y-1">
                    {sideDraft
                      .filter(
                        (c) => !c.isToken && (c.zone === "sideboard") === side,
                      )
                      .sort((a, b) => a.card.name.localeCompare(b.card.name))
                      .map((c) => (
                        <button
                          key={c.uid}
                          className="w-full btn-secondary justify-between! text-xs!"
                          onClick={() =>
                            setSideDraft((v) =>
                              v!.map((i) =>
                                i.uid === c.uid
                                  ? {
                                      ...i,
                                      zone: side ? "library" : "sideboard",
                                    }
                                  : i,
                              ),
                            )
                          }
                        >
                          {c.card.name}
                          <span>{side ? "← MAIN" : "SIDE →"}</span>
                        </button>
                      ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                className="btn-primary"
                disabled={
                  sideDraft.filter((c) => !c.isToken && c.zone !== "sideboard")
                    .length < 60 ||
                  sideDraft.filter((c) => c.zone === "sideboard").length > 15
                }
                onClick={() => {
                  start(sideDraft);
                  setSideDraft(null);
                }}
              >
                Avvia partita post-sideboard
              </button>
              <button
                className="btn-secondary"
                onClick={() => setSideDraft(null)}
              >
                Annulla modifiche
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
