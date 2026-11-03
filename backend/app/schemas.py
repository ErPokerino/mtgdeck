from datetime import datetime
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class FormatOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    min_mainboard: int = 60
    max_sideboard: int = 15
    max_copies: int = 4
    legal_sets_count: int = 0
    legal_cards_count: int = 0
    banned_cards_count: int = 0


class SetOut(BaseModel):
    code: str
    name: str
    set_type: str
    released_at: Optional[str] = None
    card_count: int = 0
    icon_svg_uri: Optional[str] = None
    is_standard_legal: bool = False
    is_pioneer_legal: bool = False
    is_modern_legal: bool = False

    model_config = {"from_attributes": True}


class BannedCardOut(BaseModel):
    oracle_id: str
    name: str
    mana_cost: Optional[str] = None
    type_line: str
    set_code: str
    image_uris: Dict[str, Any] = Field(default_factory=dict)


class FormatDetailOut(FormatOut):
    legal_sets: List[SetOut] = Field(default_factory=list)
    banned_cards: List[BannedCardOut] = Field(default_factory=list)


class CardMetaInfo(BaseModel):
    overall_presence_pct: float = 0.0
    main_presence_pct: float = 0.0
    main_avg_copies: float = 0.0
    side_presence_pct: float = 0.0
    side_avg_copies: float = 0.0
    top_archetypes: List[Dict[str, Any]] = Field(default_factory=list)


class CardOut(BaseModel):
    oracle_id: str
    scryfall_id: str
    name: str
    layout: str = "normal"
    mana_cost: Optional[str] = None
    cmc: float = 0.0
    colors: List[str] = Field(default_factory=list)
    color_identity: List[str] = Field(default_factory=list)
    type_line: str = ""
    oracle_text: Optional[str] = ""
    power: Optional[str] = None
    toughness: Optional[str] = None
    loyalty: Optional[str] = None
    rarity: str = "common"
    set_code: str = ""
    set_name: Optional[str] = None
    collector_number: Optional[str] = None
    released_at: Optional[str] = None
    image_uris: Dict[str, Any] = Field(default_factory=dict)
    card_faces: List[Dict[str, Any]] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    produced_mana: List[str] = Field(default_factory=list)
    prices: Dict[str, Any] = Field(default_factory=dict)
    max_copies: Optional[int] = 4
    is_basic_land: bool = False
    legality_standard: str = "not_legal"
    legality_pioneer: str = "not_legal"
    legality_modern: str = "not_legal"
    meta_info: Optional[CardMetaInfo] = None
    # Filled only by the card detail endpoint.
    rulings: Optional[List[Dict[str, Any]]] = None
    functional_tags: Optional[List[str]] = None

    model_config = {"from_attributes": True}


class CardSearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    cards: List[CardOut]


class DeckCardEntryIn(BaseModel):
    oracle_id: Optional[str] = None
    card_name: Optional[str] = None
    board: Literal["main", "side", "companion"] = "main"
    quantity: int = Field(default=1, ge=1, le=250)


class DeckCardOut(BaseModel):
    id: Optional[int] = None
    oracle_id: str
    card_name: str
    board: str
    quantity: int
    card: CardOut


class ValidationIssue(BaseModel):
    severity: str  # "error" | "warning"
    code: str
    message: str
    card_name: Optional[str] = None


class DeckValidationReport(BaseModel):
    is_valid: bool
    format_id: str
    mainboard_count: int
    sideboard_count: int
    companion_count: int = 0
    issues: List[ValidationIssue] = Field(default_factory=list)


class DeckAnalytics(BaseModel):
    mana_curve: Dict[str, Dict[str, int]] = Field(
        default_factory=dict
    )  # {"0": {"creatures": 0, "spells": 2}, ... "6+": ...}
    avg_cmc_nonland: float = 0.0
    color_pip_distribution: Dict[str, int] = Field(
        default_factory=dict
    )  # {"W": 12, "U": 24, ...}
    mana_source_distribution: Dict[str, int] = Field(
        default_factory=dict
    )  # {"W": 14, "U": 18, ...}
    type_Counts: Dict[str, int] = Field(
        default_factory=dict
    )  # {"Creature": 16, "Instant": 12, "Land": 24, ...}
    land_count: int = 0
    nonland_count: int = 0


class DeckCreateIn(BaseModel):
    name: str
    format_id: Literal["standard", "pioneer", "modern"] = "standard"
    archetype: str = "midrange"
    colors: List[str] = Field(default_factory=list)
    color_label: Optional[str] = None
    description: Optional[str] = None
    source: str = "manual"
    cards: List[DeckCardEntryIn] = Field(default_factory=list)


class DeckUpdateIn(BaseModel):
    name: Optional[str] = None
    format_id: Optional[Literal["standard", "pioneer", "modern"]] = None
    archetype: Optional[str] = None
    colors: Optional[List[str]] = None
    color_label: Optional[str] = None
    description: Optional[str] = None
    cards: Optional[List[DeckCardEntryIn]] = None


class DeckSummaryOut(BaseModel):
    archived: bool = False
    guide_count: int = 0
    revision_count: int = 0
    id: int
    name: str
    format_id: str
    archetype: str
    colors: List[str] = Field(default_factory=list)
    color_label: Optional[str] = None
    source: str
    mainboard_count: int = 0
    sideboard_count: int = 0
    is_valid: bool = False
    updated_at: datetime


class DeckDetailOut(BaseModel):
    id: int
    name: str
    format_id: str
    archetype: str
    colors: List[str] = Field(default_factory=list)
    color_label: Optional[str] = None
    description: Optional[str] = None
    source: str
    guide_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    cards: List[DeckCardOut] = Field(default_factory=list)
    validation: DeckValidationReport
    analytics: DeckAnalytics


class DeckImportIn(BaseModel):
    text: str
    format_id: Literal["standard", "pioneer", "modern"] = "standard"
    name: Optional[str] = None
    archetype: str = "midrange"
    save_to_db: bool = True


class DeckExportOut(BaseModel):
    arena_format: str
    mtgo_format: str


class SyncStatusOut(BaseModel):
    scryfall_status: str  # "idle" | "running" | "completed" | "failed"
    scryfall_progress_pct: float = 0.0
    scryfall_message: str = ""
    scryfall_last_sync: Optional[datetime] = None
    total_cards_in_db: int = 0
    total_sets_in_db: int = 0
    meta_status: str = "idle"
    meta_message: str = ""
    meta_last_sync_by_format: Dict[str, Optional[datetime]] = Field(
        default_factory=dict
    )


class SettingsOut(BaseModel):
    ai_provider: str
    has_gemini_api_key: bool
    masked_gemini_api_key: str
    selected_complex_model_id: str
    simple_model_id: str
    available_models: List[Dict[str, Any]]
    tiers_info: Dict[str, Any]
    skills_config: Dict[str, Any]
    gcp_project: str = ""
    gcp_location: str = "us-central1"


class SettingsUpdateIn(BaseModel):
    gemini_api_key: Optional[str] = None
    selected_complex_model_id: Optional[str] = None
    ai_provider: Optional[str] = None
    gcp_project: Optional[str] = None
    gcp_location: Optional[str] = None
