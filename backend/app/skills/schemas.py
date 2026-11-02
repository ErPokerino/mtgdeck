from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


# ============================================================================
# SKILL 1: GENERAZIONE AI DEL MAZZO (deck_generation)
# ============================================================================
class AIDeckCardSlot(BaseModel):
    card_name: str = Field(
        description="Nome inglese esatto della carta come su Scryfall"
    )
    quantity: int = Field(
        ge=1,
        le=250,
        description="Numero di copie (1-4, o superiore solo per Terre Base)",
    )
    role: str = Field(
        description="Ruolo nel mazzo es. Core Engine, Primary Threat, Premium Removal, Counter/Permission, Card Advantage, Manabase, Sideboard Bullet"
    )
    reason: str = Field(
        description="Motivazione tecnica da Pro Player in italiano della scelta e del numero esatto di copie (es. perché 4x fisso vs 2x flex slot, impatto sul meta e magic numbers)"
    )


class AIDeckGenerationOutput(BaseModel):
    deck_name: str = Field(description="Nome competitivo da torneo del mazzo")
    archetype: str = Field(
        description="aggro | midrange | control | combo | tempo | ramp"
    )
    color_combination_name: str = Field(
        description="Nome MTG della combinazione colori es. Dimir (UB), Boros (RW), Jund (BRG)"
    )
    strategy_overview: str = Field(
        description="Tesi competitiva del mazzo: perché registrare queste 75 in un torneo oggi, piano A vs piano B, vantaggi sui Tier 1 del formato e magic numbers"
    )
    mana_curve_notes: str = Field(
        description="Analisi matematica della curva di mana, conteggio fonti colorate (Karsten math), bilanciamento terre stappate/tappate e utility lands"
    )
    sideboard_mapping_notes: str = Field(
        default="",
        description="Logica di costruzione dei 15 slot di Sideboard e mappatura con i flex slot del Mainboard (elefanti/over-siding evitati contro i Tier 1)",
    )
    key_synergies: List[str] = Field(
        description="Elenco delle 4-6 sinergie chiave, micro-interazioni di regole e linee di sequenziamento tra le carte scelte"
    )
    excluded_cards_or_traps: List[str] = Field(
        default_factory=list,
        description="Sezione 'Why We Didn't Register X': 3-5 carte popolari o apparentemente sinergiche che abbiamo deliberatamente ESCLUSO perché subottimali o trappole nel meta attuale",
    )
    mainboard: List[AIDeckCardSlot] = Field(
        description="Lista carte Mainboard (la somma delle quantity DEVE essere esattamente 60)"
    )
    sideboard: List[AIDeckCardSlot] = Field(
        description="Lista carte Sideboard (la somma delle quantity DEVE essere esattamente 15)"
    )


class AIDeckGenerationRequest(BaseModel):
    format_id: Literal["standard", "pioneer", "modern"] = "standard"
    prompt: str = ""
    archetype: Optional[str] = None  # aggro | midrange | control | combo | tempo | ramp
    colors: List[str] = Field(default_factory=list)  # es. ["U", "B"]
    color_preset_name: Optional[str] = None  # es. "Dimir (UB)", "Jund (BRG)"
    build_around_cards: List[str] = Field(default_factory=list)
    model_id: Optional[str] = None
    save_deck: bool = True


# ============================================================================
# SKILL 2: GUIDA AL MAZZO AI (deck_guide) — PRO TOUR / RC PRIMER
# ============================================================================
class CardRoleExplanation(BaseModel):
    card_name: str
    quantity: int = Field(ge=1, le=250)
    role_category: str = Field(
        description="Core Engine | Primary Threat | Interaction/Removal | Flex Slot | Manabase | Sideboard Tech"
    )
    explanation: str = Field(
        description="Analisi approfondita: perché esattamente questo numero di copie, come sequenziarla, interazioni di regole e quando tagliarla post-side"
    )


class SynergyExplanation(BaseModel):
    cards_involved: List[str]
    description: str = Field(
        description="Spiegazione tecnica della sinergia, timing nello stack, linee di turno e vantaggio generato"
    )


class ExcludedCardNote(BaseModel):
    card_name: str = Field(
        description="Nome inglese della carta popolare o candidata esclusa ('Maybes / Don'ts')"
    )
    why_excluded: str = Field(
        description="Spiegazione tecnica da Pro Player del perché NON giochiamo questa carta (es. mana-inefficiente, vulnerabile alle rimozioni del formato, win-more)"
    )


class MulliganHandExample(BaseModel):
    hand_cards: List[str] = Field(
        description="Lista esatta di 7 carte della mano iniziale di esempio (usando carte reali del mazzo)"
    )
    context: str = Field(
        description="Contesto es. 'Game 1 al buio On the Play', 'Game 2 On the Draw vs Red Deck Wins', 'Game 2 On the Play vs Control'"
    )
    verdict: str = Field(description="KEEP | MULLIGAN | KEEP CONDIZIONALE")
    analysis: str = Field(
        description="Spiegazione dettagliata del perché questa mano è un Keep o una Trap Hand da mandare in Mulligan, e cosa mettere in fondo se a 6"
    )


class SideboardSwapItem(BaseModel):
    card_name: str
    quantity: int = Field(ge=1, le=250)
    reason: str


class MatchupSideboardPlan(BaseModel):
    opponent_archetype: str
    tier: int
    expected_winrate_pct: float = Field(ge=0, le=100)  #
    matchup_difficulty: str = Field(
        description="Favorevole | Equilibrato | Sfavorevole"
    )
    gameplan_pre_side: str = Field(
        description="Piano di gioco dettagliato in Game 1: chi è il beatdown, minacce prioritarie da neutralizzare e finestre di svolta"
    )
    gameplan_post_side: str = Field(
        description="Come si trasforma il matchup in Game 2/3, quali hate-cards avversarie aspettarsi e come giocarci attorno"
    )
    on_the_play_notes: str = Field(
        description="Differenze tattiche e di sidata quando siamo On the Play (OTP: pressione proattiva, curve-out)"
    )
    on_the_draw_notes: str = Field(
        description="Differenze tattiche e di sidata quando siamo On the Draw (OTD: rimozioni a basso costo, tagliare carte lente)"
    )
    mulligan_target: str = Field(
        default="",
        description="Cosa cercare specificamente nella mano iniziale in questo matchup (carte chiave da avere a turno 1-3)",
    )
    pro_tips: List[str] = Field(
        default_factory=list,
        description="2-4 consigli tattici specifici per questo matchup (es. cosa nominare con carte di hate, su cosa conservare i counter/rimozioni)",
    )
    cards_in: List[SideboardSwapItem]
    cards_out: List[SideboardSwapItem]
    on_the_play_in: List[SideboardSwapItem] = Field(default_factory=list)
    on_the_play_out: List[SideboardSwapItem] = Field(default_factory=list)
    on_the_draw_in: List[SideboardSwapItem] = Field(default_factory=list)
    on_the_draw_out: List[SideboardSwapItem] = Field(default_factory=list)
    estimate_rationale: str = ""


class AIDeckGuideOutput(BaseModel):
    executive_summary: str = Field(
        description="Introduzione da guida Pro Tour: filosofia dell'archetipo, perché giocare questa versione (Thesis) ed evoluzione della lista"
    )
    pro_score: int = Field(
        ge=1,
        le=10,
        description="Punteggio da 1 a 10 (10 = Tier-0 teorico, 8-9 = Tier-1 da vittoria Pro Tour/RC, 6-7 = Tier-2/Metagame Call)",
    )
    pro_score_rationale: str = Field(
        description="Motivazione tecnica rigorosa dello score basata su consistenza geometrica, efficienza di mana, piano post-board e posizionamento"
    )
    meta_positioning: str = Field(
        description="Posizionamento nel metagame attuale: quali archetipi prediamo, quali soffriamo e perché"
    )
    format_context_and_magic_numbers: str = Field(
        default="",
        description="Analisi dei 'Magic Numbers' del formato (es. soglie di costituzione 3/4 contro le rimozioni più giocate, costi di mana critici per Spell Snare/Fatal Push/Torch the Tower, velocità del clock)",
    )
    manabase_and_probability_analysis: str = Field(
        default="",
        description="Analisi matematica della manabase: numero di terre, conteggio fonti per colore rispetto ai requisiti di turno 1-3, gestione di terre tappate/surveil/fastland/shockland e flood mitigation",
    )
    card_roles: List[CardRoleExplanation] = Field(
        description="Card-by-Card Breakdown dettagliato delle scelte di Mainboard e Sideboard"
    )
    synergies: List[SynergyExplanation]
    early_game_plan: str = Field(
        description="Turni 1-3: sequenziamento terre, setup, gestione del tempo e prime decisioni critiche"
    )
    mid_game_plan: str = Field(
        description="Turni 4-6: svolta di ruolo (Who's the Beatdown), massimizzazione del vantaggio carte/tempo e gestione delle minacce"
    )
    late_game_plan: str = Field(
        description="Turni 7+: chiusura della partita, gestione del topdeck, attivazione manland/utility lands e prevenzione delle rimozioni di massa"
    )
    mulligan_heuristics: str = Field(
        description="Regole auree di Mulligan per questo mazzo, soglie minime di terre/interazione e gestione di Londra Mulligan a 6 e 5 carte"
    )
    mulligan_examples: List[MulliganHandExample] = Field(
        default_factory=list,
        description="4 esempi concreti di mani iniziali da 7 carte (inclusa almeno una 'Trap Hand' ingannevole da mandare in Mulligan) con verdetto e spiegazione",
    )
    excluded_cards_and_donts: List[ExcludedCardNote] = Field(
        default_factory=list,
        description="Sezione 'Maybes / Don'ts — Why didn't we register X card?': 4-6 carte popolari escluse o errori di deckbuilding da evitare in questo archetipo",
    )
    tips_and_tricks: List[str] = Field(
        default_factory=list,
        description="6-10 micro-interazioni avanzate, trick di pila (stack), stop in upkeep/draw step, interazioni tra carte e scorciatoie da Pro Player",
    )
    strengths: List[str]
    weaknesses: List[str]
    sideboard_guide: List[MatchupSideboardPlan]


class AIDeckGuideRequest(BaseModel):
    deck_id: Optional[int] = None
    format_id: Literal["standard", "pioneer", "modern"] = "standard"
    deck_name: str = "Mazzo in Analisi"
    decklist_text: Optional[str] = None
    model_id: Optional[str] = None


# ============================================================================
# SKILL 3: ANALISI MATCHUP SPOT AI (matchup_spot)
# ============================================================================
class KeyCardImpact(BaseModel):
    card_name: str
    owner: str = Field(description="Deck A | Deck B")
    impact_level: str = Field(description="Game-Winning | High | Medium")
    how_to_play_or_counter: str


class SpotMatchupSideboardPlan(BaseModel):
    cards_in: List[SideboardSwapItem]
    cards_out: List[SideboardSwapItem]
    post_side_adjustments: str


class AIMatchupSpotOutput(BaseModel):
    matchup_title: str
    expected_winrate_deck_a_pre_side_pct: float = Field(
        ge=0, le=100, description="Winrate atteso Mazzo A in Game 1 (0-100)"
    )
    expected_winrate_deck_a_post_side_pct: float = Field(
        ge=0, le=100, description="Winrate atteso Mazzo A post-sideboard (0-100)"
    )
    overall_expected_winrate_deck_a_pct: float = Field(
        ge=0,
        le=100,
        description="Winrate complessivo stimato Bo3 per il Mazzo A (0-100)",
    )
    whos_the_beatdown: str = Field(
        description="Analisi dettagliata di chi è il Beatdown e chi il Control, e come cambia post-side e tra On the Play vs On the Draw"
    )
    deck_a_strategy: str = Field(
        description="Piano di gioco chirurgico per il pilota del Mazzo A (sequenziamento, mulligan target, cosa neutralizzare)"
    )
    deck_b_strategy: str = Field(
        description="Piano di gioco chirurgico per il pilota del Mazzo B (come punire il Mazzo A e quali finestre sfruttare)"
    )
    critical_turns_and_interactions: List[str] = Field(
        description="Turni critici, battaglie di pila, bluff e micro-interazioni decisive tra i due mazzi"
    )
    key_cards: List[KeyCardImpact]
    sideboard_plan_for_deck_a: SpotMatchupSideboardPlan
    sideboard_plan_for_deck_b: SpotMatchupSideboardPlan


class AIMatchupSpotRequest(BaseModel):
    format_id: Literal["standard", "pioneer", "modern"] = "standard"
    deck_a_id: Optional[int] = None
    deck_a_name: str = "Mazzo A (Pilota)"
    deck_a_text: Optional[str] = None
    deck_b_id: Optional[int] = None
    deck_b_archetype_id: Optional[int] = None
    deck_b_name: str = "Mazzo B (Avversario)"
    deck_b_text: Optional[str] = None
    model_id: Optional[str] = None
