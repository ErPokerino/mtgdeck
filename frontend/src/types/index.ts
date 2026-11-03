export type FormatId = "standard" | "pioneer" | "modern";

export interface FormatInfo {
  id: FormatId;
  name: string;
  description?: string;
  min_mainboard: number;
  max_sideboard: number;
  max_copies: number;
  legal_sets_count: number;
  legal_cards_count: number;
  banned_cards_count: number;
}

export interface SetInfo {
  code: string;
  name: string;
  set_type: string;
  released_at?: string;
  card_count: number;
  icon_svg_uri?: string;
  is_standard_legal: boolean;
  is_pioneer_legal: boolean;
  is_modern_legal: boolean;
}

export interface BannedCardInfo {
  oracle_id: string;
  name: string;
  mana_cost?: string;
  type_line: string;
  set_code: string;
  image_uris: Record<string, any>;
}

export interface FormatDetail extends FormatInfo {
  legal_sets: SetInfo[];
  banned_cards: BannedCardInfo[];
}

/** Observed usage of a card in an archetype's collected lists (older snapshots: copies in one list). */
export interface CardArchetypeUsage {
  archetype: string;
  main_inclusion_pct?: number;
  main_avg_copies?: number;
  side_inclusion_pct?: number;
  side_avg_copies?: number;
  sample_copies?: number;
}

export interface CardRulingInfo {
  published_at?: string;
  source?: string;
  comment: string;
}

export interface ArchetypeCardUsage {
  oracle_id: string;
  card_name: string;
  type_line: string;
  mana_cost?: string;
  main_inclusion_pct: number;
  main_avg_copies: number;
  side_inclusion_pct: number;
  side_avg_copies: number;
}

export interface ArchetypeDecklistRef {
  id: number;
  title?: string;
  pilot?: string;
  event?: string;
  placement?: string;
  played_on?: string;
}

export interface ArchetypeDetail {
  id: number;
  name: string;
  decklists_count: number;
  cards: ArchetypeCardUsage[];
  decklists: ArchetypeDecklistRef[];
}

export interface CardMetaInfo {
  overall_presence_pct: number;
  main_presence_pct: number;
  main_avg_copies: number;
  side_presence_pct: number;
  side_avg_copies: number;
  top_archetypes: CardArchetypeUsage[];
}

export interface CardFace {
  name: string;
  mana_cost?: string;
  type_line?: string;
  oracle_text?: string;
  power?: string;
  toughness?: string;
  loyalty?: string;
  colors?: string[];
  image_uris?: Record<string, string>;
}

export interface Card {
  oracle_id: string;
  scryfall_id: string;
  name: string;
  layout: string;
  mana_cost?: string;
  cmc: number;
  colors: string[];
  color_identity: string[];
  type_line: string;
  oracle_text?: string;
  power?: string;
  toughness?: string;
  loyalty?: string;
  rarity: string;
  set_code: string;
  set_name?: string;
  collector_number?: string;
  released_at?: string;
  image_uris: Record<string, any>;
  card_faces: CardFace[];
  keywords: string[];
  produced_mana: string[];
  prices: Record<string, any>;
  max_copies?: number | null;
  is_basic_land: boolean;
  legality_standard: string;
  legality_pioneer: string;
  legality_modern: string;
  meta_info?: CardMetaInfo | null;
  rulings?: CardRulingInfo[] | null;
  functional_tags?: string[] | null;
}

export interface CardSearchResponse {
  total: number;
  page: number;
  page_size: number;
  cards: Card[];
}

export interface DeckCardItem {
  id?: number;
  oracle_id: string;
  card_name: string;
  board: "main" | "side" | "companion";
  quantity: number;
  card: Card;
}

export interface ValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  card_name?: string;
}

export interface DeckValidationReport {
  is_valid: boolean;
  format_id: string;
  mainboard_count: number;
  sideboard_count: number;
  companion_count: number;
  issues: ValidationIssue[];
}

export interface DeckAnalytics {
  mana_curve: Record<
    string,
    { creatures: number; spells: number; total: number }
  >;
  avg_cmc_nonland: number;
  color_pip_distribution: Record<string, number>;
  mana_source_distribution: Record<string, number>;
  type_Counts: Record<string, number>;
  land_count: number;
  nonland_count: number;
}

export interface DeckSummary {
  archived?: boolean;
  guide_count?: number;
  revision_count?: number;
  id: number;
  name: string;
  format_id: FormatId;
  archetype: string;
  colors: string[];
  color_label?: string;
  source: string;
  mainboard_count: number;
  sideboard_count: number;
  is_valid: boolean;
  updated_at: string;
}

export interface DeckDetail {
  id: number;
  name: string;
  format_id: FormatId;
  archetype: string;
  colors: string[];
  color_label?: string;
  description?: string;
  source: string;
  guide_json?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
  cards: DeckCardItem[];
  validation: DeckValidationReport;
  analytics: DeckAnalytics;
}

export interface SyncStatus {
  scryfall_status: "idle" | "running" | "completed" | "failed";
  scryfall_progress_pct: number;
  scryfall_message: string;
  scryfall_last_sync?: string | null;
  total_cards_in_db: number;
  total_sets_in_db: number;
  meta_status: string;
  meta_message: string;
  meta_last_sync_by_format: Record<string, string | null>;
}

export interface AIModelConfig {
  id: string;
  label: string;
  tier: "simple" | "complex";
  enabled: boolean;
  isDefaultSimple?: boolean;
  isDefaultComplex?: boolean;
  description?: string;
  replacementNotice?: string;
}

export interface AppSettings {
  ai_provider: "gemini-api-key" | "vertex-ai";
  has_gemini_api_key: boolean;
  masked_gemini_api_key: string;
  selected_complex_model_id: string;
  simple_model_id: string;
  available_models: AIModelConfig[];
  tiers_info: Record<string, any>;
  skills_config: Record<string, any>;
  gcp_project: string;
  gcp_location: string;
}

export interface MetaArchetypeInfo {
  id: number;
  name: string;
  slug: string;
  category: string;
  tier: number;
  colors: string[];
  color_name?: string;
  meta_share_pct: number;
  /** null when the source publishes no winrate. */
  winrate_pct: number | null;
  matches_count: number;
  decklists_count?: number | null;
  key_cards: Array<{
    oracle_id?: string;
    name: string;
    mana_cost?: string;
    image_small?: string;
    card?: Card;
  }>;
  sample_decklists: Array<{
    decklist_id?: number;
    name: string;
    pilot?: string;
    event?: string;
    played_on?: string;
    decklist_text: string;
  }>;
  source_url?: string;
}

export interface MetaTopCardInfo {
  id: number;
  card_name: string;
  oracle_id?: string;
  overall_presence_pct: number;
  main_presence_pct: number;
  main_avg_copies: number;
  side_presence_pct: number;
  side_avg_copies: number;
  top_archetypes: CardArchetypeUsage[];
  card?: Card | null;
}

export interface FormatMetaResponse {
  snapshot: {
    id: number;
    format_id: FormatId;
    source: string;
    fetched_at: string;
    total_decks_analyzed: number;
    notes?: string;
    period_label?: string | null;
    coverage_pct?: number | null;
    decklists_count?: number | null;
    quality_status?: "ok" | "degraded" | null;
    quality_warnings?: string[];
  };
  archetypes: MetaArchetypeInfo[];
  matchup_matrix: Record<
    string,
    Record<
      string,
      {
        winrate_pct: number;
        matches_count: number;
        estimate_kind?: "observed" | "heuristic";
      }
    >
  >;
  top_cards: MetaTopCardInfo[];
}
