import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import { LibraryView } from "./components/library/LibraryView";
import { Onboarding } from "./components/layout/Onboarding";
import { AIStudioView } from "./components/ai/AIStudioView";
import { DeckBuilderView } from "./components/deckbuilder/DeckBuilderView";
import { FormatExplorerView } from "./components/formats/FormatExplorerView";
import { SettingsModal } from "./components/layout/SettingsModal";
import { type ActiveTab, TopBar } from "./components/layout/TopBar";
import { MetaExplorerView } from "./components/meta/MetaExplorerView";
import { PlaytestView } from "./components/playtest/PlaytestView";
import type {
  AppSettings,
  DeckDetail,
  FormatDetail,
  FormatId,
  FormatInfo,
  MetaArchetypeInfo,
  SyncStatus,
} from "./types";

interface NavEntry {
  tab: ActiveTab;
  format: FormatId;
  setCode: string | null;
}

const VALID_TABS: ActiveTab[] = [
  "deckbuilder",
  "format_info",
  "meta",
  "ai_studio",
  "playtest",
  "library",
];
const VALID_FORMATS: FormatId[] = ["standard", "pioneer", "modern"];

function parseNavFromUrl(): NavEntry {
  const params = new URLSearchParams(window.location.search);
  const rawTab = params.get("tab") as ActiveTab;
  const rawFmt = params.get("format") as FormatId;
  const setCode = params.get("set") || null;
  return {
    tab: VALID_TABS.includes(rawTab) ? rawTab : "deckbuilder",
    format: VALID_FORMATS.includes(rawFmt) ? rawFmt : "standard",
    setCode,
  };
}

function buildUrlSearch(entry: NavEntry): string {
  const params = new URLSearchParams();
  params.set("format", entry.format);
  params.set("tab", entry.tab);
  if (entry.setCode) {
    params.set("set", entry.setCode);
  }
  return `?${params.toString()}`;
}

export const App: React.FC = () => {
  const initialNav = parseNavFromUrl();

  const [formats, setFormats] = useState<FormatInfo[]>([]);
  const [selectedFormat, setSelectedFormat] = useState<FormatId>(
    initialNav.format,
  );
  const [formatDetail, setFormatDetail] = useState<FormatDetail | null>(null);
  const [loadingFormatDetail, setLoadingFormatDetail] = useState(false);

  const [activeTab, setActiveTab] = useState<ActiveTab>(initialNav.tab);
  const [preselectedSetCode, setPreselectedSetCode] = useState<string | null>(
    initialNav.setCode,
  );
  const [preselectedBaseArch, setPreselectedBaseArch] =
    useState<MetaArchetypeInfo | null>(null);
  const [preselectedOpponentArch, setPreselectedOpponentArch] =
    useState<MetaArchetypeInfo | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [builderEpoch, setBuilderEpoch] = useState(0);
  const [guideIntent, setGuideIntent] = useState(false);
  const [activeDeck, setActiveDeck] = useState<DeckDetail | null>(null);
  const [aiStudioFormats, setAiStudioFormats] = useState<FormatId[]>([
    initialNav.format,
  ]);
  useEffect(() => {
    setAiStudioFormats((prev) =>
      prev.includes(selectedFormat) ? prev : [...prev, selectedFormat],
    );
  }, [selectedFormat]);

  // Navigation history stack synchronized with Browser History API
  const [navStack, setNavStack] = useState<NavEntry[]>([initialNav]);
  const [navIndex, setNavIndex] = useState<number>(0);
  const isPoppingRef = useRef(false);

  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [helpToken, setHelpToken] = useState(0);

  // Full-height views size themselves against the real header, which wraps on narrow screens.
  useEffect(() => {
    const header = document.querySelector<HTMLElement>(".workspace-header");
    if (!header) return;
    const update = () =>
      document.documentElement.style.setProperty(
        "--header-h",
        `${header.offsetHeight}px`,
      );
    update();
    const observer = new ResizeObserver(update);
    observer.observe(header);
    return () => observer.disconnect();
  }, []);

  // Initialize first history entry
  useEffect(() => {
    window.history.replaceState(
      { navIdx: 0, entry: initialNav },
      "",
      buildUrlSearch(initialNav),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const navigateTo = useCallback(
    (partial: Partial<NavEntry>) => {
      const nextEntry: NavEntry = {
        tab: partial.tab ?? activeTab,
        format: partial.format ?? selectedFormat,
        setCode:
          partial.setCode !== undefined ? partial.setCode : preselectedSetCode,
      };
      if (
        nextEntry.tab === activeTab &&
        nextEntry.format === selectedFormat &&
        nextEntry.setCode === preselectedSetCode
      ) {
        return;
      }

      setActiveTab(nextEntry.tab);
      setSelectedFormat(nextEntry.format);
      setPreselectedSetCode(nextEntry.setCode);

      if (!isPoppingRef.current) {
        // Side effects stay out of state updaters: StrictMode runs updaters twice.
        const nextStack = [...navStack.slice(0, navIndex + 1), nextEntry];
        const nextIdx = nextStack.length - 1;
        setNavStack(nextStack);
        setNavIndex(nextIdx);
        window.history.pushState(
          { navIdx: nextIdx, entry: nextEntry },
          "",
          buildUrlSearch(nextEntry),
        );
      }
    },
    [activeTab, selectedFormat, preselectedSetCode, navIndex, navStack],
  );

  // Listen to browser Back / Forward (popstate)
  useEffect(() => {
    const handlePopState = (ev: PopStateEvent) => {
      isPoppingRef.current = true;
      const stateEntry: NavEntry = ev.state?.entry || parseNavFromUrl();
      const idx = typeof ev.state?.navIdx === "number" ? ev.state.navIdx : -1;
      setActiveTab(stateEntry.tab);
      setSelectedFormat(stateEntry.format);
      setPreselectedSetCode(stateEntry.setCode);
      if (idx >= 0) {
        setNavIndex(idx);
      }
      setTimeout(() => {
        isPoppingRef.current = false;
      }, 20);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const handleGoBack = useCallback(() => {
    if (navIndex > 0) {
      window.history.back();
    }
  }, [navIndex]);

  const handleGoForward = useCallback(() => {
    if (navIndex < navStack.length - 1) {
      window.history.forward();
    }
  }, [navIndex, navStack.length]);

  const loadFormatsAndDetail = useCallback(async (fmt: FormatId) => {
    setLoadingFormatDetail(true);
    try {
      const [fmts, detail] = await Promise.all([
        api.getFormats(),
        api.getFormatDetail(fmt),
      ]);
      setFormats(fmts);
      setFormatDetail(detail);
    } catch (err) {
      console.error("Error loading format details:", err);
    } finally {
      setLoadingFormatDetail(false);
    }
  }, []);

  useEffect(() => {
    loadFormatsAndDetail(selectedFormat);
  }, [selectedFormat, loadFormatsAndDetail]);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(console.error);
  }, []);

  // Poll sync status
  useEffect(() => {
    let prevStatus = syncStatus?.scryfall_status;
    const fetchSync = async () => {
      try {
        const st = await api.getSyncStatus();
        setSyncStatus(st);
        if (prevStatus === "running" && st.scryfall_status === "completed") {
          loadFormatsAndDetail(selectedFormat);
        }
        prevStatus = st.scryfall_status;
      } catch (err) {
        console.error("Sync status poll error:", err);
      }
    };
    fetchSync();
    const intervalMs = syncStatus?.scryfall_status === "running" ? 2000 : 12000;
    const id = setInterval(fetchSync, intervalMs);
    return () => clearInterval(id);
  }, [syncStatus?.scryfall_status, selectedFormat, loadFormatsAndDetail]);

  const handleTriggerSync = async (force = false) => {
    try {
      await api.triggerScryfallSync(force);
      const st = await api.getSyncStatus();
      setSyncStatus(st);
    } catch (err: any) {
      setGlobalError(err.message);
    }
  };

  const handleChangeComplexModel = async (modelId: string) => {
    try {
      const updated = await api.updateSettings({
        selected_complex_model_id: modelId,
      });
      setSettings(updated);
    } catch (err: any) {
      setGlobalError(err.message);
    }
  };

  const handleSaveSettings = async (payload: any) => {
    const updated = await api.updateSettings(payload);
    setSettings(updated);
  };

  useEffect(() => {
    let cancelled = false;
    setActiveDeck((prev) => (prev?.format_id === selectedFormat ? prev : null));
    try {
      const id = localStorage.getItem(`aetherdeck.active.${selectedFormat}`);
      if (id)
        api
          .getDeck(Number(id))
          .then((d) => {
            if (!cancelled && d.format_id === selectedFormat) setActiveDeck(d);
          })
          .catch(() => {});
    } catch {
      /* Browser storage can be disabled. */
    }
    return () => {
      cancelled = true;
    };
  }, [selectedFormat]);
  useEffect(() => {
    if (activeDeck?.format_id === selectedFormat) {
      try {
        localStorage.setItem(
          `aetherdeck.active.${selectedFormat}`,
          String(activeDeck.id),
        );
      } catch {
        /* optional preference */
      }
    }
  }, [activeDeck, selectedFormat]);

  return (
    <div className="min-h-screen flex flex-col bg-[#090B10] text-[#E6ECF5]">
      <TopBar
        formats={formats}
        selectedFormat={selectedFormat}
        onSelectFormat={(fmt) => navigateTo({ format: fmt })}
        activeTab={activeTab}
        onSelectTab={(tab) => navigateTo({ tab })}
        canGoBack={navIndex > 0}
        canGoForward={navIndex < navStack.length - 1}
        onGoBack={handleGoBack}
        onGoForward={handleGoForward}
        syncStatus={syncStatus}
        onTriggerSync={() => handleTriggerSync(false)}
        settings={settings}
        onChangeComplexModel={handleChangeComplexModel}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenHelp={() => setHelpToken((v) => v + 1)}
      />

      <main className="flex-1 min-w-0">
        {globalError && (
          <div className="notice-error m-3" role="alert">
            {globalError}
            <button
              className="ml-4 underline"
              onClick={() => setGlobalError(null)}
            >
              Chiudi
            </button>
          </div>
        )}
        {activeTab === "library" && (
          <LibraryView
            formatId={selectedFormat}
            onOpen={(d) => {
              setActiveDeck(d);
              navigateTo({ tab: "deckbuilder" });
            }}
            onPlaytest={(d) => {
              setActiveDeck(d);
              navigateTo({ tab: "playtest" });
            }}
            onGuide={(d) => {
              setActiveDeck(d);
              setGuideIntent(true);
              navigateTo({ tab: "ai_studio" });
            }}
            onRestored={(d) => {
              // The builder keeps a local draft of the open deck: drop it and remount,
              // otherwise a later "Salva" would overwrite the restored version.
              let draftDeckId: number | null = null;
              try {
                const key = `aetherdeck.draft.${d.format_id}`;
                draftDeckId = JSON.parse(
                  localStorage.getItem(key) || "null",
                )?.deckId;
                if (draftDeckId === d.id) localStorage.removeItem(key);
              } catch {
                /* Browser storage can be disabled. */
              }
              if (activeDeck?.id === d.id || draftDeckId === d.id) {
                setActiveDeck(d);
                setBuilderEpoch((e) => e + 1);
              }
            }}
            onDelete={(id) => {
              try {
                const draft = JSON.parse(
                  localStorage.getItem(`aetherdeck.draft.${selectedFormat}`) ||
                    "null",
                );
                if (draft?.deckId === id)
                  localStorage.removeItem(`aetherdeck.draft.${selectedFormat}`);
                if (
                  localStorage.getItem(
                    `aetherdeck.active.${selectedFormat}`,
                  ) === String(id)
                )
                  localStorage.removeItem(
                    `aetherdeck.active.${selectedFormat}`,
                  );
              } catch {}
              if (activeDeck?.id === id) {
                setActiveDeck(null);
                setBuilderEpoch((e) => e + 1);
              }
            }}
          />
        )}
        <div hidden={activeTab !== "deckbuilder"}>
          <DeckBuilderView
            key={`${selectedFormat}-${builderEpoch}`}
            formatId={selectedFormat}
            formatDetail={formatDetail}
            preselectedSetCode={preselectedSetCode}
            onClearPreselectedSet={() => navigateTo({ setCode: null })}
            activeDeck={
              activeDeck?.format_id === selectedFormat ? activeDeck : null
            }
            onDeckChange={setActiveDeck}
            onNavigateToAI={() => navigateTo({ tab: "ai_studio" })}
          />
        </div>

        {activeTab === "format_info" && (
          <FormatExplorerView
            formatDetail={formatDetail}
            loading={loadingFormatDetail}
            onSelectSetForBuilder={(setCode) => {
              navigateTo({ tab: "deckbuilder", setCode });
            }}
          />
        )}

        {activeTab === "meta" && (
          <MetaExplorerView
            formatId={selectedFormat}
            onLoadDeckToBuilder={(deck) => {
              setActiveDeck(deck);
              navigateTo({ tab: "deckbuilder" });
            }}
            onOpenMatchupSpotWithArchetype={(arch) => {
              setPreselectedOpponentArch(arch);
              navigateTo({ tab: "ai_studio" });
            }}
            onBuildFromArchetype={(arch) => {
              setPreselectedBaseArch(arch);
              navigateTo({ tab: "ai_studio" });
            }}
          />
        )}

        {/* One instance per visited format keeps forms and results while switching. */}
        {aiStudioFormats.map((fmt) => (
          <div
            key={fmt}
            hidden={activeTab !== "ai_studio" || fmt !== selectedFormat}
          >
            <AIStudioView
              openGuide={fmt === selectedFormat && guideIntent}
              onGuideIntentHandled={() => setGuideIntent(false)}
              onChangeModel={handleChangeComplexModel}
              formatId={fmt}
              activeDeck={activeDeck?.format_id === fmt ? activeDeck : null}
              settings={settings}
              preselectedOpponentArchetype={
                fmt === selectedFormat ? preselectedOpponentArch : null
              }
              onClearPreselectedOpponent={() =>
                setPreselectedOpponentArch(null)
              }
              preselectedBaseArchetype={
                fmt === selectedFormat ? preselectedBaseArch : null
              }
              onClearPreselectedBase={() => setPreselectedBaseArch(null)}
              onOpenDeckInBuilder={(deck) => {
                setActiveDeck(deck);
                navigateTo({ tab: "deckbuilder" });
              }}
              onOpenDeckInPlaytest={(deck) => {
                setActiveDeck(deck);
                navigateTo({ tab: "playtest" });
              }}
              onOpenSettings={() => setIsSettingsOpen(true)}
            />
          </div>
        ))}

        <div hidden={activeTab !== "playtest"}>
          <PlaytestView
            key={selectedFormat}
            formatId={selectedFormat}
            activeDeck={
              activeDeck?.format_id === selectedFormat ? activeDeck : null
            }
            onSelectDeck={setActiveDeck}
          />
        </div>
      </main>

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        settings={settings}
        syncStatus={syncStatus}
        onSaveSettings={handleSaveSettings}
        onTriggerScryfallSync={(force) => handleTriggerSync(force)}
      />
      <Onboarding
        suspended={isSettingsOpen}
        restartToken={helpToken}
        onNavigate={(tab) => navigateTo({ tab })}
        onSettings={() => setIsSettingsOpen(true)}
      />
    </div>
  );
};

export default App;
