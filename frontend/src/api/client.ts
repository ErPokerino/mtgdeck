import type {
  AIJob,
  AppSettings,
  ArchetypeDetail,
  Card,
  CardSearchResponse,
  DeckDetail,
  DeckGenerationResult,
  DeckSummary,
  FormatDetail,
  FormatId,
  FormatInfo,
  FormatMetaResponse,
  ListAnalysis,
  SyncStatus,
} from "../types";

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
    ...options,
  });
  if (!res.ok) {
    // The body can be read only once: read text, then try to interpret it as JSON.
    const raw = await res.text().catch(() => "");
    let errText = raw || `HTTP ${res.status}`;
    try {
      const data = JSON.parse(raw);
      errText =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail
                .map((e: any) => `${e.loc?.join(".")}: ${e.msg}`)
                .join("; ")
            : JSON.stringify(data);
    } catch {
      /* not JSON: keep the raw text */
    }
    throw new Error(errText);
  }
  return res.json();
}

export const api = {
  getFormats: () => apiFetch<FormatInfo[]>("/api/formats"),
  getFormatDetail: (formatId: FormatId) =>
    apiFetch<FormatDetail>(`/api/formats/${formatId}`),

  searchCards: (
    params: Record<string, string | number | boolean | undefined>,
    signal?: AbortSignal,
  ) => {
    const sp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") {
        sp.set(k, String(v));
      }
    });
    return apiFetch<CardSearchResponse>(`/api/cards/search?${sp.toString()}`, {
      signal,
    });
  },

  getCardDetail: (oracleId: string, formatId: FormatId) =>
    apiFetch<Card>(`/api/cards/${oracleId}?format_id=${formatId}`),

  listDecks: (formatId?: FormatId, archived = false) =>
    apiFetch<DeckSummary[]>(
      `/api/decks?archived=${archived}${formatId ? `&format_id=${formatId}` : ""}`,
    ),

  listGuides: (formatId?: FormatId) =>
    apiFetch<any[]>(`/api/guides${formatId ? `?format_id=${formatId}` : ""}`),
  getGuide: (id: number) => apiFetch<any>(`/api/guides/${id}`),
  deleteGuide: (id: number) =>
    apiFetch<any>(`/api/guides/${id}`, { method: "DELETE" }),
  archiveDeck: (id: number, archived: boolean) =>
    apiFetch<any>(`/api/decks/${id}/archive?archived=${archived}`, {
      method: "PUT",
    }),
  duplicateDeck: (id: number) =>
    apiFetch<DeckDetail>(`/api/decks/${id}/duplicate`, { method: "POST" }),
  getRevisions: (id: number) => apiFetch<any[]>(`/api/decks/${id}/revisions`),
  restoreRevision: (id: number, rev: number) =>
    apiFetch<DeckDetail>(`/api/decks/${id}/restore/${rev}`, { method: "POST" }),
  getTokens: (oracleId: string) =>
    apiFetch<Card[]>(`/api/cards/${oracleId}/tokens`),
  getDeck: (deckId: number) => apiFetch<DeckDetail>(`/api/decks/${deckId}`),

  createDeck: (payload: any) =>
    apiFetch<DeckDetail>("/api/decks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateDeck: (deckId: number, payload: any) =>
    apiFetch<DeckDetail>(`/api/decks/${deckId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  deleteDeck: (deckId: number) =>
    apiFetch<{ status: string; deck_id: number }>(`/api/decks/${deckId}`, {
      method: "DELETE",
    }),

  analyzeDeck: (payload: any, signal?: AbortSignal) =>
    apiFetch<{
      colors: string[];
      color_label: string;
      validation: DeckDetail["validation"];
      analytics: DeckDetail["analytics"];
      competitive: ListAnalysis | null;
      export: { arena_format: string; mtgo_format: string };
    }>("/api/decks/analyze", {
      method: "POST",
      body: JSON.stringify(payload),
      signal,
    }),

  importDeck: (payload: {
    text: string;
    format_id: FormatId;
    name?: string;
    archetype?: string;
    save_to_db?: boolean;
  }) =>
    apiFetch<{ deck?: DeckDetail; unresolved_cards: string[]; cards?: any[] }>(
      "/api/decks/import",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  getFormatMeta: (formatId: FormatId) =>
    apiFetch<FormatMetaResponse>(`/api/meta/${formatId}`),

  triggerMetaSync: (formatId?: FormatId) =>
    apiFetch<any>(`/api/meta/sync${formatId ? `?format_id=${formatId}` : ""}`, {
      method: "POST",
    }),

  loadArchetypeSampleDeck: (
    formatId: FormatId,
    archetypeId: number,
    decklistId?: number,
  ) =>
    apiFetch<DeckDetail>(
      `/api/meta/${formatId}/load-archetype-deck/${archetypeId}${
        decklistId != null ? `?decklist_id=${decklistId}` : ""
      }`,
      {
        method: "POST",
      },
    ),

  getArchetypeDetail: (formatId: FormatId, archetypeId: number) =>
    apiFetch<ArchetypeDetail>(
      `/api/meta/${formatId}/archetypes/${archetypeId}`,
    ),

  generateDeckAI: (payload: {
    format_id: FormatId;
    prompt: string;
    archetype?: string;
    colors: string[];
    color_preset_name?: string;
    build_around_cards: string[];
    base_archetype_id?: number;
    model_id?: string;
    save_deck?: boolean;
  }) =>
    apiFetch<DeckGenerationResult>(
      "/api/ai/generate-deck",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  generateDeckGuideAI: (payload: {
    deck_id?: number;
    format_id: FormatId;
    deck_name: string;
    decklist_text?: string;
    model_id?: string;
  }) =>
    apiFetch<{ guide: any; meta: any }>("/api/ai/deck-guide", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  startGuideJob: (payload: any, legacyRunId?: number) =>
    apiFetch<any>(
      `/api/ai/guide-jobs${legacyRunId ? `?legacy_run_id=${legacyRunId}` : ""}`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  listGuideJobs: (formatId: FormatId) =>
    apiFetch<any>(`/api/ai/guide-jobs?format_id=${formatId}`),
  getGuideJob: (id: number) => apiFetch<any>(`/api/ai/guide-jobs/${id}`),
  cancelGuideJob: (id: number) =>
    apiFetch<any>(`/api/ai/guide-jobs/${id}/cancel`, { method: "POST" }),
  resumeGuideJob: (id: number) =>
    apiFetch<any>(`/api/ai/guide-jobs/${id}/resume`, { method: "POST" }),

  analyzeSpotMatchupAI: (payload: {
    format_id: FormatId;
    deck_a_id?: number;
    deck_a_name: string;
    deck_a_text?: string;
    deck_b_id?: number;
    deck_b_archetype_id?: number;
    deck_b_name: string;
    deck_b_text?: string;
    model_id?: string;
  }) =>
    apiFetch<{ analysis: any; meta: any }>("/api/ai/matchup-spot", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  startDeckGenerationJob: (payload: Record<string, unknown>) =>
    apiFetch<AIJob>("/api/ai/jobs/deck-generation", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startMatchupJob: (payload: Record<string, unknown>) =>
    apiFetch<AIJob>("/api/ai/jobs/matchup-spot", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listAIJobs: (formatId: FormatId, kind: AIJob["kind"]) =>
    apiFetch<{ jobs: AIJob[] }>(
      `/api/ai/jobs?format_id=${formatId}&kind=${kind}`,
    ),
  getAIJob: (id: number) => apiFetch<AIJob>(`/api/ai/jobs/${id}`),
  cancelAIJob: (id: number) =>
    apiFetch<AIJob>(`/api/ai/jobs/${id}/cancel`, { method: "POST" }),

  getQualityReport: (formatId: FormatId) =>
    apiFetch<any>(`/api/quality/report?format_id=${formatId}`),
  getRating: (kind: "guide" | "deck", id: number) =>
    apiFetch<any>(`/api/quality/ratings?target_kind=${kind}&target_id=${id}`),
  addRating: (payload: {
    target_kind: "guide" | "deck";
    target_id: number;
    depth: number;
    correctness: number;
    usefulness: number;
    note?: string;
  }) =>
    apiFetch<any>("/api/quality/ratings", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listRecords: (deckId: number) =>
    apiFetch<any>(`/api/quality/decks/${deckId}/records`),
  addRecord: (deckId: number, payload: Record<string, unknown>) =>
    apiFetch<any>(`/api/quality/decks/${deckId}/records`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteRecord: (recordId: number) =>
    apiFetch<any>(`/api/quality/records/${recordId}`, { method: "DELETE" }),

  getSyncStatus: () => apiFetch<SyncStatus>("/api/sync/status"),

  triggerScryfallSync: (forceDownload = false) =>
    apiFetch<{ status: string; message: string }>(
      `/api/sync/scryfall?force_download=${forceDownload}`,
      { method: "POST" },
    ),

  getSettings: () => apiFetch<AppSettings>("/api/settings"),

  updateSettings: (
    payload: Partial<{
      gemini_api_key: string;
      selected_complex_model_id: string;
      ai_provider: string;
      gcp_project: string;
      gcp_location: string;
    }>,
  ) =>
    apiFetch<AppSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};
