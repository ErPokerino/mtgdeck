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


class AIDeckDelta(BaseModel):
    card_name: str = Field(description="Nome inglese esatto della carta")
    board: Literal["main", "side"]
    change: int = Field(
        description="Copie aggiunte (positivo) o tolte (negativo) rispetto alla lista di consenso, in questo board"
    )
    reason: str = Field(
        description="Quale matchup migliora, contro quali carte avversarie e quale costo opportunità accetti"
    )
    matchups: List[str] = Field(
        default_factory=list, description="Archetipi del campo interessati, con il nome esatto fornito"
    )


class AIGenerationSwap(BaseModel):
    card_name: str
    quantity: int = Field(ge=1, le=15)


class AIGenerationMatchupPlan(BaseModel):
    opponent_archetype: str = Field(description="Nome esatto dell'archetipo del campo atteso")
    plan: str = Field(
        description="Chi è il beatdown, cosa conta nel matchup, come vincono loro e come vinciamo noi, carte avversarie da rispettare"
    )
    sideboard_in: List[AIGenerationSwap] = Field(default_factory=list)
    sideboard_out: List[AIGenerationSwap] = Field(default_factory=list)


class AIDeckGenerationOutput(BaseModel):
    deck_name: str = Field(
        description="Nome del mazzo: per una lista derivata dal meta usa il nome dell'archetipo di partenza"
    )
    archetype: str = Field(
        description="aggro | midrange | control | combo | tempo | ramp"
    )
    color_combination_name: str = Field(
        description="Nome MTG della combinazione colori es. Dimir (UB), Boros (RW), Jund (BRG)"
    )
    base_archetype: str = Field(
        default="",
        description="Nome esatto dell'archetipo del meta da cui parte la lista; stringa vuota se è un brew",
    )
    strategy_overview: str = Field(
        description="Tesi competitiva: contro quali archetipi del campo è costruita la lista, piano A e piano B, turni critici, condizioni in cui la tesi fallisce"
    )
    concessions: str = Field(
        default="",
        description="Matchup e situazioni concessi consapevolmente e perché il compromesso conviene nel campo atteso",
    )
    mana_curve_notes: str = Field(
        description="Ragionamento su numero di terre, fonti per colore rispetto ai requisiti forniti, terre che entrano tappate e curva; nessuna percentuale non fornita dal contesto"
    )
    sideboard_mapping_notes: str = Field(
        default="",
        description="Logica dei 15 slot di sideboard: quali matchup coprono, quali slot del main sostituiscono, come si evita l'overboarding",
    )
    key_synergies: List[str] = Field(
        description="4-6 sinergie e interazioni di regole tra le carte scelte, basate sui testi Oracle"
    )
    excluded_cards_or_traps: List[str] = Field(
        default_factory=list,
        description="3-5 carte popolari o plausibili escluse deliberatamente, con il motivo nel campo atteso",
    )
    deltas: List[AIDeckDelta] = Field(
        default_factory=list,
        description="Per una lista derivata dal meta: OGNI differenza rispetto alla lista di consenso, carta per carta e board per board. Vuoto per un brew",
    )
    matchup_plans: List[AIGenerationMatchupPlan] = Field(
        default_factory=list,
        description="Un piano per ciascuno degli archetipi principali del campo indicati nel contesto, con IN dalla sideboard e OUT dal main bilanciati",
    )
    flex_rules: List[str] = Field(
        default_factory=list,
        description="Criteri per cambiare i flex slot: 'se X cresce nel meta, A al posto di B' o equivalenti verificabili",
    )
    mainboard: List[AIDeckCardSlot] = Field(
        description="Lista carte Mainboard (la somma delle quantity DEVE essere esattamente 60)"
    )
    sideboard: List[AIDeckCardSlot] = Field(
        description="Lista carte Sideboard (la somma delle quantity DEVE essere esattamente 15)"
    )


class AICriticIssue(BaseModel):
    severity: Literal["alta", "media", "bassa"]
    area: str = Field(description="manabase | curva | interazione | sideboard | matchup | regole | slot")
    finding: str = Field(description="Il punto debole, con le carte e gli archetipi coinvolti")
    recommendation: str = Field(description="Correzione concreta e motivata")


class AICriticSwap(BaseModel):
    board: Literal["main", "side"]
    card_out: str
    card_in: str
    quantity: int = Field(ge=1, le=4)
    reason: str
    matchups: List[str] = Field(default_factory=list)


class AIDeckCriticOutput(BaseModel):
    verdict: Literal["solida", "da_rivedere"]
    summary: str = Field(description="Giudizio sintetico sulla lista contro il campo atteso")
    issues: List[AICriticIssue] = Field(default_factory=list)
    oracle_errors: List[str] = Field(
        default_factory=list,
        description="Affermazioni della proposta contraddette dal testo Oracle fornito, citando carta e frase",
    )
    swaps: List[AICriticSwap] = Field(
        default_factory=list, description="Cambi raccomandati, solo se motivati contro il campo"
    )


class AIDeckGenerationRequest(BaseModel):
    format_id: Literal["standard", "pioneer", "modern"] = "standard"
    prompt: str = ""
    archetype: Optional[str] = None  # aggro | midrange | control | combo | tempo | ramp
    colors: List[str] = Field(default_factory=list)  # es. ["U", "B"]
    color_preset_name: Optional[str] = None  # es. "Dimir (UB)", "Jund (BRG)"
    build_around_cards: List[str] = Field(default_factory=list)
    # Archetipo del meta da cui partire (lista di consenso); None = brew dalla tesi dell'utente.
    base_archetype_id: Optional[int] = None
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
        description="Perché esattamente questo numero di copie nel campo atteso, come sequenziarla, interazioni di regole e quando tagliarla post-side"
    )
    alternatives_considered: str = Field(
        default="",
        description="Alternative concrete per lo stesso slot (nomi di carte) e perché questa è preferita nel campo atteso",
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
    reason: str = Field(description="Motivo leggibile, 8-20 parole: contro quali carte avversarie o in quale ruolo")


class OpponentKeyCard(BaseModel):
    card_name: str = Field(description="Carta dell'avversario presente nel profilo fornito, nome inglese esatto")
    why_it_matters: str = Field(description="Cosa ci fa: soglie di danno, timing, bersagli, quando arriva")
    our_answer: str = Field(description="La nostra risposta concreta: carta, finestra di timing o modo di giocarci attorno")


class FlexSlot(BaseModel):
    card_name: str
    trigger: str = Field(description="Condizione di meta verificabile per cambiarla e con cosa sostituirla")


class MatchupSideboardPlan(BaseModel):
    opponent_archetype: str
    tier: int
    expected_winrate_pct: float = Field(
        ge=0, le=100, description="Stima teorica Bo3 del modello, non un dato di partite"
    )
    matchup_difficulty: str = Field(
        description="Favorevole | Equilibrato | Sfavorevole"
    )
    confidence: str = Field(
        default="",
        description="bassa | media | alta: quanto è affidabile la stima, dati i profili disponibili",
    )
    role_pre_side: str = Field(
        default="",
        description="Chi è il beatdown in Game 1 e perché, in una frase",
    )
    role_post_side: str = Field(
        default="",
        description="Come cambia il ruolo dopo la sideboard, in una frase",
    )
    opponent_key_cards: List[OpponentKeyCard] = Field(
        default_factory=list,
        description="Almeno 2 carte dell'avversario, prese dal profilo fornito, con la nostra risposta",
    )
    expected_opponent_sideboard: List[str] = Field(
        default_factory=list,
        description="Carte che l'avversario porta dentro contro di noi, prese dalla sua sideboard probabile",
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
    on_the_play_uses_base: bool = Field(
        default=False,
        description="True solo se la sidata OTP è identica al piano base; lascia vuoti on_the_play_in/out e spiega le differenze tattiche nelle note",
    )
    on_the_draw_uses_base: bool = Field(
        default=False,
        description="True solo se la sidata OTD è identica al piano base; lascia vuoti on_the_draw_in/out",
    )
    estimate_rationale: str = ""


class AIDeckGuideOutput(BaseModel):
    executive_summary: str = Field(
        description="Introduzione da guida Pro Tour: filosofia dell'archetipo, perché giocare questa versione (Thesis) ed evoluzione della lista"
    )
    tier_assessment: str = Field(
        default="",
        description="Posizione qualitativa nel campo atteso (es. 'scelta solida contro un campo aggressivo') con confidenza e motivo; nessun punteggio numerico",
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
        description="Carte chiave di main e sideboard, terre comprese quando la scelta è rilevante"
    )
    flex_slots: List[FlexSlot] = Field(
        default_factory=list,
        description="Slot flessibili della lista con il trigger di meta per cambiarli",
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


class GuideJSONPatch(BaseModel):
    path: str = Field(
        description="JSON Pointer esistente, es. /card_roles/0/explanation"
    )
    original_json: str = Field(
        description="Valore originale JSON; per testi lunghi preferisci un frammento errato esatto e univoco, con virgolette JSON"
    )
    replacement_json: str = Field(
        description="Valore corretto serializzato come JSON, dello stesso tipo"
    )
    reason: str = Field(
        description="Contraddizione letterale e correzione; non segnalare frasi che già esprimono il vincolo corretto"
    )
    source_quote: str = Field(
        default="",
        description="Breve estratto esatto dell’Oracle o regola fornita; vuoto solo per errori di copie o struttura",
    )


class GuideReviewOutput(BaseModel):
    patches: List[GuideJSONPatch] = Field(
        default_factory=list,
        description="Una patch per percorso, correggere tutte le occorrenze nello stesso passaggio",
    )
    unresolved_issues: List[str] = Field(
        default_factory=list,
        description="Solo errori concreti non risolvibili con una patch; vuoto se nessuno",
    )
