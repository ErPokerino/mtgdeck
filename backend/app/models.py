from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Format(Base):
    __tablename__ = "formats"

    id = Column(String(32), primary_key=True)  # "standard" | "pioneer" | "modern"
    name = Column(String(64), nullable=False)
    description = Column(Text, nullable=True)
    min_mainboard = Column(Integer, default=60, nullable=False)
    max_sideboard = Column(Integer, default=15, nullable=False)
    max_copies = Column(Integer, default=4, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SetModel(Base):
    __tablename__ = "sets"

    code = Column(String(16), primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    set_type = Column(String(64), nullable=False, index=True)
    released_at = Column(String(32), nullable=True, index=True)
    card_count = Column(Integer, default=0)
    digital = Column(Boolean, default=False)
    icon_svg_uri = Column(String(512), nullable=True)
    is_standard_legal = Column(Boolean, default=False, index=True)
    is_pioneer_legal = Column(Boolean, default=False, index=True)
    is_modern_legal = Column(Boolean, default=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Card(Base):
    __tablename__ = "cards"

    oracle_id = Column(String(64), primary_key=True)
    scryfall_id = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    normalized_name = Column(String(255), nullable=False, index=True)
    layout = Column(String(64), default="normal")

    mana_cost = Column(String(128), nullable=True)
    cmc = Column(Float, default=0.0, index=True)
    colors = Column(JSON, default=list)  # es. ["U", "R"]
    color_key = Column(String(16), default="", index=True)  # es. "UR" ordinato WUBRG
    color_identity = Column(JSON, default=list)  # es. ["U", "R"]
    color_identity_key = Column(String(16), default="", index=True)

    type_line = Column(String(255), nullable=False, default="", index=True)
    oracle_text = Column(Text, nullable=True, default="")

    power = Column(String(16), nullable=True)
    power_num = Column(Float, nullable=True, index=True)
    toughness = Column(String(16), nullable=True)
    toughness_num = Column(Float, nullable=True, index=True)
    loyalty = Column(String(16), nullable=True)
    defense = Column(String(16), nullable=True)

    rarity = Column(String(32), nullable=False, default="common", index=True)
    set_code = Column(String(16), nullable=False, index=True)
    set_name = Column(String(255), nullable=True)
    collector_number = Column(String(32), nullable=True)
    released_at = Column(String(32), nullable=True, index=True)

    arena_id = Column(Integer, nullable=True)
    mtgo_id = Column(Integer, nullable=True)

    image_uris = Column(JSON, default=dict)  # {"small", "normal", "large", "art_crop"}
    card_faces = Column(JSON, default=list)  # dettagli facce per DFC/Split/Adventure
    keywords = Column(JSON, default=list)
    produced_mana = Column(JSON, default=list)
    prices = Column(JSON, default=dict)  # {"usd", "eur", "tix"}

    # Limite copie nel mazzo: None = illimitate (Terre Base, Relentless Rats, Hare Apparent, ecc.).
    # Nessun default: con l'ORM un None esplicito attiverebbe il default e diventerebbe 4.
    max_copies = Column(Integer, nullable=True)
    is_basic_land = Column(Boolean, default=False, index=True)

    # Campi denormalizzati di legalità per filtri SQL istantanei sui 3 formati principali + legacy/commander info
    legality_standard = Column(String(32), default="not_legal", index=True)
    legality_pioneer = Column(String(32), default="not_legal", index=True)
    legality_modern = Column(String(32), default="not_legal", index=True)
    legalities_json = Column(JSON, default=dict)

    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_cards_std_cmc", "legality_standard", "cmc"),
        Index("ix_cards_pio_cmc", "legality_pioneer", "cmc"),
        Index("ix_cards_mod_cmc", "legality_modern", "cmc"),
    )


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(
        String(64), nullable=False, index=True
    )  # "scryfall" | "mtgdecks" | "mtgtop8"
    format_id = Column(String(32), nullable=True, index=True)
    status = Column(String(32), nullable=False)  # "running" | "completed" | "failed"
    records_processed = Column(Integer, default=0)
    message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class MetaSnapshot(Base):
    __tablename__ = "meta_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    format_id = Column(String(32), ForeignKey("formats.id"), nullable=False, index=True)
    source = Column(String(64), nullable=False)  # "mtgdecks+mtgtop8" | "fallback"
    fetched_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    total_decks_analyzed = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    # Quality of the snapshot: what the AI and the UI can trust.
    period_label = Column(String(64), nullable=True)  # es. "Last 2 Months"
    coverage_pct = Column(Float, nullable=True)  # quota del meta coperta da archetipi con liste
    decklists_count = Column(Integer, nullable=True)  # liste complete usate per le statistiche
    quality_status = Column(String(16), nullable=True)  # "ok" | "degraded"
    quality_warnings = Column(JSON, nullable=True)

    archetypes = relationship(
        "MetaArchetype", back_populates="snapshot", cascade="all, delete-orphan"
    )
    matchups = relationship(
        "MetaMatchup", back_populates="snapshot", cascade="all, delete-orphan"
    )
    card_stats = relationship(
        "MetaCardStat", back_populates="snapshot", cascade="all, delete-orphan"
    )


class MetaArchetype(Base):
    __tablename__ = "meta_archetypes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(
        Integer,
        ForeignKey("meta_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    format_id = Column(String(32), nullable=False, index=True)
    name = Column(String(128), nullable=False, index=True)
    slug = Column(String(128), nullable=False, index=True)
    category = Column(
        String(32), default="midrange"
    )  # aggro | midrange | control | combo | tempo
    tier = Column(Integer, default=1)  # 1, 2, 3
    colors = Column(JSON, default=list)
    color_name = Column(String(64), nullable=True)  # es. "Dimir", "Boros", "Jund"
    meta_share_pct = Column(Float, default=0.0)
    winrate_pct = Column(Float, nullable=True)  # None: nessuna fonte di winrate osservato
    matches_count = Column(Integer, default=0)  # mazzi dell'archetipo nel periodo della fonte
    key_cards = Column(JSON, default=list)  # nomi 4-6 carte simbolo
    sample_decklists = Column(
        JSON, default=list
    )  # 1-3 decklist campione reali [{"name", "pilot", "event", "main", "side"}]
    source_url = Column(String(512), nullable=True)
    source_archetype_id = Column(String(32), nullable=True)
    decklist_ids = Column(JSON, nullable=True)  # TournamentDecklist.id complete usate
    decklists_count = Column(Integer, nullable=True)

    snapshot = relationship("MetaSnapshot", back_populates="archetypes")
    cards = relationship(
        "MetaArchetypeCard", back_populates="archetype", cascade="all, delete-orphan"
    )


class TournamentDecklist(Base):
    """Persistent cache of tournament lists: a deck is downloaded once and reused by later syncs."""

    __tablename__ = "tournament_decklists"
    __table_args__ = (
        UniqueConstraint("source", "source_deck_id", name="uq_tournament_deck_source"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(32), nullable=False)  # "mtgtop8"
    source_deck_id = Column(String(64), nullable=False)
    format_id = Column(String(32), nullable=False, index=True)
    source_archetype_id = Column(String(32), nullable=True, index=True)
    archetype_name = Column(String(128), nullable=True)
    deck_title = Column(String(255), nullable=True)
    pilot = Column(String(128), nullable=True)
    event_name = Column(String(255), nullable=True)
    placement = Column(String(32), nullable=True)
    played_on = Column(String(10), nullable=True, index=True)  # ISO yyyy-mm-dd
    cards = Column(JSON, default=list)  # [{"oracle_id","card_name","board","quantity"}]
    raw_text = Column(Text, nullable=True)
    is_complete = Column(Boolean, default=False, nullable=False)
    issues = Column(JSON, default=list)
    fetched_at = Column(DateTime(timezone=True), default=utcnow)


class MetaArchetypeCard(Base):
    """Observed card usage inside one archetype's collected lists."""

    __tablename__ = "meta_archetype_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(
        Integer,
        ForeignKey("meta_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    archetype_id = Column(
        Integer,
        ForeignKey("meta_archetypes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    oracle_id = Column(String(64), nullable=False, index=True)
    card_name = Column(String(255), nullable=False)
    lists_count = Column(Integer, nullable=False)
    main_inclusion_pct = Column(Float, default=0.0)
    main_avg_copies = Column(Float, default=0.0)  # media sulle liste che la giocano in main
    side_inclusion_pct = Column(Float, default=0.0)
    side_avg_copies = Column(Float, default=0.0)

    archetype = relationship("MetaArchetype", back_populates="cards")


class CardRuling(Base):
    __tablename__ = "card_rulings"

    oracle_id = Column(String(64), primary_key=True)
    rulings = Column(JSON, default=list)  # [{"published_at","source","comment"}]


class CardTag(Base):
    """Functional Scryfall Tagger tags (removal, counterspell, draw...) per Oracle identity."""

    __tablename__ = "card_tags"

    oracle_id = Column(String(64), primary_key=True)
    tag = Column(String(64), primary_key=True, index=True)


class MetaMatchup(Base):
    __tablename__ = "meta_matchups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(
        Integer,
        ForeignKey("meta_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    format_id = Column(String(32), nullable=False, index=True)
    archetype_a_name = Column(String(128), nullable=False, index=True)
    archetype_b_name = Column(String(128), nullable=False, index=True)
    winrate_a_pct = Column(Float, nullable=False)
    matches_count = Column(Integer, default=0)

    snapshot = relationship("MetaSnapshot", back_populates="matchups")


class MetaCardStat(Base):
    __tablename__ = "meta_card_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(
        Integer,
        ForeignKey("meta_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    format_id = Column(String(32), nullable=False, index=True)
    card_name = Column(String(255), nullable=False, index=True)
    oracle_id = Column(String(64), nullable=True, index=True)
    overall_presence_pct = Column(Float, default=0.0)
    main_presence_pct = Column(Float, default=0.0)
    main_avg_copies = Column(Float, default=0.0)
    side_presence_pct = Column(Float, default=0.0)
    side_avg_copies = Column(Float, default=0.0)
    top_archetypes = Column(
        JSON, default=list
    )  # [{"archetype": "...", "sample_copies": 4}] copie osservate nella lista di riferimento

    snapshot = relationship("MetaSnapshot", back_populates="card_stats")


class Deck(Base):
    __tablename__ = "decks"
    # Without AUTOINCREMENT SQLite reuses deleted ids, re-linking old runs and jobs to new decks.
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    format_id = Column(String(32), ForeignKey("formats.id"), nullable=False, index=True)
    archetype = Column(
        String(64), default="midrange"
    )  # aggro, midrange, control, combo, tempo, ramp
    colors = Column(JSON, default=list)
    color_label = Column(String(64), nullable=True)  # es. "Azorius (WU)"
    description = Column(Text, nullable=True)
    source = Column(
        String(32), default="manual"
    )  # manual | imported | ai_generated | meta_sample
    guide_json = Column(JSON, nullable=True)  # Ultima guida AI salvata per il mazzo
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    cards = relationship(
        "DeckCard", back_populates="deck", cascade="all, delete-orphan"
    )


class DeckCard(Base):
    __tablename__ = "deck_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    deck_id = Column(
        Integer, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    oracle_id = Column(
        String(64), ForeignKey("cards.oracle_id"), nullable=False, index=True
    )
    card_name = Column(String(255), nullable=False)
    board = Column(
        String(16), nullable=False, default="main"
    )  # "main" | "side" | "companion"
    quantity = Column(Integer, nullable=False, default=1)

    deck = relationship("Deck", back_populates="cards")

    __table_args__ = (
        UniqueConstraint("deck_id", "oracle_id", "board", name="uq_deck_card_board"),
    )


class AIRun(Base):
    __tablename__ = "ai_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_name = Column(String(64), nullable=False, index=True)
    prompt_version = Column(String(32), nullable=False)
    model_id = Column(String(64), nullable=False)
    provider = Column(String(32), nullable=False)
    format_id = Column(String(32), nullable=True)
    deck_id = Column(Integer, nullable=True)
    validation_attempts = Column(Integer, default=1)
    duration_ms = Column(Integer, default=0)
    input_summary = Column(JSON, default=dict)
    output_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class GuideJob(Base):
    __tablename__ = "guide_jobs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    format_id = Column(String(32), nullable=False, index=True)
    deck_id = Column(Integer, nullable=True, index=True)
    request_json = Column(JSON, nullable=False)
    status = Column(String(32), default="queued", nullable=False)
    phase = Column(String(64), default="queued", nullable=False)
    draft_json = Column(JSON, nullable=True)
    signature = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)
    result_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AIJob(Base):
    """Durable deck generation and matchup analysis: survive reloads, report phases, can be cancelled."""

    __tablename__ = "ai_jobs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(32), nullable=False, index=True)  # deck_generation | matchup_spot
    format_id = Column(String(32), nullable=False, index=True)
    request_json = Column(JSON, nullable=False)
    status = Column(String(32), default="queued", nullable=False)
    phase = Column(String(64), default="queued", nullable=False)
    error = Column(Text, nullable=True)
    result_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value_json = Column(JSON, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DeckArchive(Base):
    __tablename__ = "deck_archives"
    deck_id = Column(
        Integer, ForeignKey("decks.id", ondelete="CASCADE"), primary_key=True
    )
    archived_at = Column(DateTime(timezone=True), default=utcnow)


class DeckRevision(Base):
    __tablename__ = "deck_revisions"
    id = Column(Integer, primary_key=True)
    deck_id = Column(
        Integer, ForeignKey("decks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class GuideVersion(Base):
    __tablename__ = "guide_versions"
    id = Column(Integer, primary_key=True)
    deck_id = Column(
        Integer, ForeignKey("decks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    deck_name = Column(String(255), nullable=False)
    format_id = Column(String(32), nullable=False, index=True)
    model_id = Column(String(64), nullable=False)
    deck_snapshot = Column(JSON, nullable=False)
    guide_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class QualityRating(Base):
    """Human evaluation of a guide or generated deck (1-5 per criterion)."""

    __tablename__ = "quality_ratings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    target_kind = Column(String(16), nullable=False, index=True)  # guide | deck
    target_id = Column(Integer, nullable=False, index=True)
    depth = Column(Integer, nullable=False)
    correctness = Column(Integer, nullable=False)
    usefulness = Column(Integer, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class MatchRecord(Base):
    """A real match the user played with a deck: the empirical side of every estimate."""

    __tablename__ = "match_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    deck_id = Column(
        Integer, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    format_id = Column(String(32), nullable=False, index=True)
    opponent_archetype = Column(String(128), nullable=False)
    games_won = Column(Integer, nullable=False, default=0)
    games_lost = Column(Integer, nullable=False, default=0)
    on_the_play = Column(Boolean, nullable=True)
    played_on = Column(String(10), nullable=True)  # yyyy-mm-dd
    event = Column(String(128), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
