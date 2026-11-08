"""True tool-using AI Agent for AetherDeck (Interactions API function_call / function_result loop).

Provides deterministic tools to inspect user decks, compute Karsten/curve/interaction analytics,
simulate card swaps, query the live metagame and Karsten consensus lists, search the Scryfall
catalog + official rulings, and explain how AetherDeck works.
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    AIRun,
    Card,
    CardTag,
    Deck,
    DeckArchive,
    MetaArchetype,
    MetaCardStat,
    MetaMatchup,
)
from app.services import deck_engine, quality
from app.services.ai_provider import get_active_ai_provider, get_skill_model_and_config
from app.services.card_knowledge import rulings_for, tags_for
from app.services.deck_validator import (
    resolve_card_by_name,
    validate_deck_entries,
)
from app.skills.deck_generation import analysis_text, oracle_text

log = logging.getLogger("uvicorn.error")

MAX_AGENT_STEPS = 6


class AgentMessageItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    previous_interaction_id: Optional[str] = None
    history: List[AgentMessageItem] = Field(default_factory=list, max_length=20)
    format_id: Literal["standard", "pioneer", "modern"] = "pioneer"
    active_tab: Optional[str] = None
    active_deck_id: Optional[int] = None
    active_deck_name: Optional[str] = None
    model_id: Optional[str] = None


AGENT_TOOL_DECLARATIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "list_user_decks",
        "description": (
            "Elenca i mazzi salvati dall'utente nel database, opzionalmente filtrati per formato "
            "(standard, pioneer, modern). Restituisce ID, nome, formato, archetipo, colori, numero carte e se ha una guida."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "format_id": {
                    "type": "string",
                    "description": "Filtra per formato: 'standard', 'pioneer' o 'modern'. Ometti per vedere tutti i formati.",
                },
                "include_archived": {
                    "type": "boolean",
                    "description": "Se true include anche i mazzi archiviati (default false).",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "get_deck_details",
        "description": (
            "Recupera la lista completa 60/15 di un mazzo salvato dell'utente (per deck_id o deck_name), "
            "con i testi Oracle completi, l'analisi deterministica di Karsten (fonti per colore vs requisiti, "
            "terre tappate/condizionali, curva di mana, densità di interazione, probabilità ipergeometriche), "
            "il confronto strutturale col metagame, lo storico match reali e il riepilogo della guida se presente."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deck_id": {
                    "type": "integer",
                    "description": "ID numerico del mazzo salvato.",
                },
                "deck_name": {
                    "type": "string",
                    "description": "Nome (anche parziale) del mazzo se non si conosce il deck_id.",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "get_metagame_overview",
        "description": (
            "Restituisce la panoramica del metagame attuale per un formato ('standard', 'pioneer', 'modern'): "
            "snapshot attivo, top archetipi con tier, quota di metagame (%), colori, profilo medio di interazione "
            "e le carte più giocate del formato (staples main e side)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "format_id": {
                    "type": "string",
                    "enum": ["standard", "pioneer", "modern"],
                    "description": "Formato di riferimento: 'standard', 'pioneer' o 'modern'.",
                },
            },
            "required": ["format_id"],
        },
    },
    {
        "type": "function",
        "name": "get_archetype_details",
        "description": (
            "Recupera i dettagli di uno specifico archetipo del metagame (es. 'Izzet Phoenix', 'Azorius Control', "
            "'Rakdos Midrange', 'Boros Energy'): lista di consenso a 75 carte calcolata col metodo di Karsten "
            "(core >=80%, flex e sideboard), analisi deterministica della lista di consenso e dati di matchup."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "format_id": {
                    "type": "string",
                    "enum": ["standard", "pioneer", "modern"],
                    "description": "Formato dell'archetipo ('standard', 'pioneer', 'modern').",
                },
                "archetype_name": {
                    "type": "string",
                    "description": "Nome (anche parziale) dell'archetipo del metagame da cercare.",
                },
            },
            "required": ["format_id", "archetype_name"],
        },
    },
    {
        "type": "function",
        "name": "search_cards_and_rulings",
        "description": (
            "Cerca carte nel catalogo locale Scryfall per nome, testo Oracle, legalità nel formato, colori, "
            "tipo di carta, costo di mana massimo (CMC) o tag funzionale ('removal', 'counterspell', 'sweeper', "
            "'discard', 'hate-graveyard', 'card-advantage-net', 'cantrip', 'ramp', 'burn'). "
            "Restituisce testo Oracle con paragrafi separati da ¶, statistiche nel meta e i RULING UFFICIALI Scryfall."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Nome inglese (esatto o parziale) della carta da cercare.",
                },
                "oracle_query": {
                    "type": "string",
                    "description": "Parola o frase da cercare dentro il testo Oracle (es. 'can\\'t be countered', 'ninjutsu', 'prowess').",
                },
                "format_id": {
                    "type": "string",
                    "enum": ["standard", "pioneer", "modern"],
                    "description": "Se specificato, filtra solo carte legali nel formato e mostra la loro presenza nel meta.",
                },
                "colors": {
                    "type": "string",
                    "description": "Filtra carte lanciabili nei colori indicati (es. 'UB', 'R', 'WUG').",
                },
                "card_type": {
                    "type": "string",
                    "description": "Filtra per tipo (es. 'Instant', 'Creature', 'Land', 'Enchantment', 'Artifact', 'Planeswalker').",
                },
                "cmc_max": {
                    "type": "number",
                    "description": "Valore di mana (CMC) massimo.",
                },
                "tag": {
                    "type": "string",
                    "description": "Tag funzionale Scryfall Tagger (es. 'removal', 'counterspell', 'sweeper', 'discard', 'hate-graveyard', 'card-advantage-net', 'cantrip').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Numero massimo di carte da restituire (default 8, max 15).",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "simulate_deck_changes",
        "description": (
            "Simula uno o più cambi di carte (OUT -> IN) su un mazzo salvato dell'utente e ricalcola "
            "deterministicamente le metriche prima/dopo: fonti per colore Karsten, deficit, curva di mana, "
            "terre tappate, densità di interazione e validità 60/15."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deck_id": {
                    "type": "integer",
                    "description": "ID del mazzo salvato su cui simulare i cambi.",
                },
                "swaps": {
                    "type": "array",
                    "description": "Lista dei cambi da simulare.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "board": {
                                "type": "string",
                                "enum": ["main", "side"],
                                "description": "Board in cui effettuare il cambio ('main' o 'side').",
                            },
                            "card_out": {
                                "type": "string",
                                "description": "Nome inglese della carta da togliere.",
                            },
                            "card_in": {
                                "type": "string",
                                "description": "Nome inglese della carta da inserire.",
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "Numero di copie da scambiare.",
                            },
                        },
                        "required": ["board", "card_out", "card_in", "quantity"],
                    },
                },
            },
            "required": ["deck_id", "swaps"],
        },
    },
    {
        "type": "function",
        "name": "get_app_help",
        "description": (
            "Restituisce la documentazione ufficiale sul funzionamento delle sezioni e funzionalità di AetherDeck "
            "(Deck Builder, Libreria & Revisioni, AI Studio con Crea Mazzo / Migliora Mazzo / Guida e Sideboard / "
            "Confronta Matchup, Playtest, Format Explorer, Meta Explorer, Qualità e Impostazioni)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": [
                        "overview",
                        "builder",
                        "ai_studio",
                        "playtest",
                        "meta_explorer",
                        "quality_and_settings",
                    ],
                    "description": "Sezione dell'app da approfondire (default 'overview').",
                },
            },
        },
    },
]


APP_HELP_TOPICS: Dict[str, Dict[str, Any]] = {
    "overview": {
        "title": "Panoramica di AetherDeck",
        "summary": (
            "AetherDeck è una workbench competitiva per Magic: The Gathering (formati Standard, Pioneer e Modern) "
            "che unisce dati reali di torneo (MTGTop8), catalogo completo Scryfall con ruling ufficiali e tag funzionali "
            "Tagger, calcoli matematici deterministici (tabelle di Frank Karsten per le fonti di mana, distribuzione "
            "ipergeometrica, liste di consenso Karsten) e quattro skill AI avanzate."
        ),
        "sections": {
            "Esplora Formato": "Ricerca avanzata di carte legali nel formato per nome, testo Oracle, colori, CMC, rarità, espansione e funzione tattica (rimozione, counter, sweeper, hate cimitero, ecc.).",
            "Metagame": "Analisi live del metagame con Tier List, quote % osservate, liste di consenso a 75 carte (metodo Karsten), carte più giocate (staples main e side) e matrici di matchup.",
            "Deck Builder": "Editor completo 60/15 con validazione di legalità in tempo reale, analisi matematica Karsten delle fonti di mana, curva di mana, densità di interazione, import/export Arena e MTGO.",
            "Libreria Mazzi": "Gestione dei mazzi salvati, storico completo delle revisioni con ripristino, duplicazione, archiviazione e registro dei risultati reali Bo3 per matchup.",
            "AI Studio": "Include 4 modalità: 1) Crea mazzo, 2) Migliora mazzo, 3) Guida e sideboard (con export PDF illustrato), 4) Confronta matchup.",
            "Playtest": "Simulatore di mano iniziale a 7 carte con London Mulligan, calcolo probabilità e test di pescata turno per turno.",
            "Qualità": "Dashboard delle metriche di qualità su mazzi generati, guide, valutazioni utente e stima costi/token dei modelli AI.",
        },
    },
    "builder": {
        "title": "Deck Builder e Libreria Mazzi",
        "how_it_works": [
            "Puoi creare un mazzo da zero, importare una lista in formato MTG Arena o MTGO, oppure partire dalla lista di consenso di un archetipo del metagame.",
            "Il validatore deterministico controlla legalità per formato, limite di 4 copie tra main e side (escluse terre base e carte con eccezione da Oracle), minimo 60 carte di main e massimo 15 di sideboard (companion incluso nei 15).",
            "Il pannello di analisi competitiva calcola in automatico: fonti di mana per colore rispetto ai requisiti di Karsten (~90% di lanciare ogni carta in curva), terre sempre stappate / condizionali all'ingresso / sempre tappate, densità di interazione (rimozioni, counter, sweeper, scarto, hate cimitero, vantaggio carte netto) e somiglianza strutturale con gli archetipi del meta.",
            "Ogni modifica salvata crea una revisione nello storico del mazzo, ripristinabile in qualsiasi momento. Puoi anche registrare i tuoi risultati di torneo Bo3 contro specifici archetipi: verranno usati dall'AI nelle guide e nel miglioramento mazzo.",
        ],
    },
    "ai_studio": {
        "title": "Funzionamento di AI Studio (4 Modalità)",
        "modes": {
            "1. Crea mazzo (deck_generation)": (
                "Genera una lista competitiva 60/15 partendo da un archetipo del metagame (ottimizzando gli slot flessibili "
                "e motivando ogni differenza rispetto al consenso) oppure come brew originale attorno a 1-4 carte build-around. "
                "Include una revisione automatica del 'Deck Critic' AI e piani di sideboard per i principali archetipi."
            ),
            "2. Migliora mazzo (deck_improvement)": (
                "Analizza un tuo mazzo salvato o una lista incollata rispetto alle metriche di Karsten e al metagame attuale. "
                "Individua i punti di forza da preservare, i punti deboli ordinati per gravità e area (manabase, curva, "
                "interazione, minacce, sideboard, posizionamento meta), propone cambi concreti bilanciati (OUT -> IN) "
                "validati sul catalogo Scryfall, elenca ulteriori carte papabili alternative e mostra il confronto "
                "deterministico Prima vs Dopo con un pulsante per applicare le migliorie al mazzo in un click."
            ),
            "3. Guida e sideboard (deck_guide)": (
                "Genera una guida da torneo completa per il mazzo: tesi e posizionamento nel meta, magic numbers del formato, "
                "analisi della manabase, ruoli delle singole carte, slot flessibili, 4 mani di mulligan commentate (inclusa trap hand), "
                "e piani pre/post-sideboard completi (con differenze On the Play vs On the Draw) contro tutti i top archetipi. "
                "Sottopone la bozza a verifica deterministica e revisione Oracle automatica, ed è esportabile in PDF illustrato."
            ),
            "4. Confronta matchup (matchup_spot)": (
                "Analisi chirurgica testa a testa tra due mazzi (o tra il tuo mazzo e un archetipo del meta): stabilisce chi è "
                "il beatdown pre e post-side, i turni critici, le carte chiave da entrambi i lati e le sidate incrociate."
            ),
        },
    },
    "playtest": {
        "title": "Simulatore di Playtest e Mulligan",
        "how_it_works": [
            "Permette di pescare mani iniziali di 7 carte dal mazzo attivo con mescolamento casuale reale.",
            "Supporta il London Mulligan (peschi 7 carte e rimetti in fondo al grimorio N carte pari al numero di mulligan effettuati).",
            "Puoi simulare i turni successivi pescando carta per carta per verificare la fluidità della curva di mana e dei colori nei primi 3-4 turni.",
        ],
    },
    "meta_explorer": {
        "title": "Esplora Formato e Metagame",
        "how_it_works": [
            "Metagame mostra lo snapshot più recente del formato selezionato (Standard, Pioneer, Modern), diviso per Tier 1, Tier 2 e Rogue.",
            "Cliccando su un archetipo puoi ispezionare la sua Lista di Consenso Karsten (che aggrega tutte le liste complete di torneo distinguendo carte Core >=80% e carte Flex) e importarla direttamente nel Builder.",
            "La vista 'Carte più giocate' mostra le staples del formato con percentuale di presenza e media copie sia in Mainboard che in Sideboard.",
        ],
    },
    "quality_and_settings": {
        "title": "Qualità, Modelli AI e Impostazioni",
        "how_it_works": [
            "Nelle Impostazioni (icona ingranaggio in alto a destra) puoi scegliere il provider AI (Gemini API Key locale o GCP Vertex AI) e il modello strategico per i task complessi ('Gemini Flash 3.8' per velocità ed equilibrio, oppure 'Gemini Argon' per la massima profondità di ragionamento).",
            "Da Impostazioni puoi anche lanciare la sincronizzazione del catalogo Scryfall (carte, ruling e tag funzionali) e degli snapshot del metagame.",
            "La scheda Qualità mostra le statistiche oggettive dei mazzi e delle guide generate, i tempi/token medi per modello e ti permette di valutare con un voto (1-5) profondità, correttezza e utilità di ogni guida o mazzo.",
        ],
    },
}


def _tool_list_user_decks(db: Session, args: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    fmt = (args.get("format_id") or "").strip().lower()
    include_archived = bool(args.get("include_archived", False))
    archived_ids = {r[0] for r in db.query(DeckArchive.deck_id).all()}
    q = db.query(Deck)
    if fmt in ("standard", "pioneer", "modern"):
        q = q.filter(Deck.format_id == fmt)
    if not include_archived and archived_ids:
        q = q.filter(~Deck.id.in_(archived_ids))
    decks = q.order_by(Deck.updated_at.desc()).limit(30).all()
    items = []
    for d in decks:
        main_qty = sum(c.quantity for c in d.cards if c.board == "main")
        side_qty = sum(c.quantity for c in d.cards if c.board != "main")
        items.append(
            {
                "id": d.id,
                "name": d.name,
                "format_id": d.format_id,
                "archetype": d.archetype,
                "colors": d.colors or [],
                "mainboard_count": main_qty,
                "sideboard_count": side_qty,
                "has_guide": bool(d.guide_json),
                "is_archived": d.id in archived_ids,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
        )
    label = f"Mazzi utente ({fmt.upper() if fmt else 'tutti'}): {len(items)} trovati"
    return {"count": len(items), "decks": items}, label


def _tool_get_deck_details(db: Session, args: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    deck_id = args.get("deck_id")
    deck_name = (args.get("deck_name") or "").strip()
    deck: Optional[Deck] = None
    if deck_id is not None:
        deck = db.get(Deck, int(deck_id))
    if not deck and deck_name:
        deck = (
            db.query(Deck)
            .filter(Deck.name.ilike(f"%{deck_name}%"))
            .order_by(Deck.updated_at.desc())
            .first()
        )
    if not deck:
        return (
            {"error": f"Mazzo non trovato (deck_id={deck_id}, deck_name='{deck_name}')."},
            "Mazzo non trovato",
        )

    oracle_ids = [dc.oracle_id for dc in deck.cards]
    cmap = (
        {
            c.oracle_id: c
            for c in db.query(Card).filter(Card.oracle_id.in_(oracle_ids)).all()
        }
        if oracle_ids
        else {}
    )
    entries = [
        (cmap[dc.oracle_id], dc.board, dc.quantity)
        for dc in deck.cards
        if dc.oracle_id in cmap
    ]
    analysis = deck_engine.analyze_list(db, entries)
    structure = deck_engine.structure_summary(db, entries, deck.format_id, deck.archetype)
    records = quality.records_text(db, deck.id)

    main_cards = []
    side_cards = []
    for c, board, qty in entries:
        item = {
            "quantity": qty,
            "name": c.name,
            "mana_cost": c.mana_cost or "",
            "cmc": c.cmc,
            "type_line": c.type_line,
            "oracle_text": oracle_text(c),
        }
        if board == "main":
            main_cards.append(item)
        else:
            side_cards.append(item)

    guide_summary = None
    if isinstance(deck.guide_json, dict):
        g = deck.guide_json
        guide_summary = {
            "executive_summary": g.get("executive_summary"),
            "tier_assessment": g.get("tier_assessment"),
            "strengths": g.get("strengths", []),
            "weaknesses": g.get("weaknesses", []),
            "matchups_covered": [
                m.get("opponent_archetype")
                for m in (g.get("sideboard_guide") or [])
                if isinstance(m, dict)
            ],
        }

    return (
        {
            "id": deck.id,
            "name": deck.name,
            "format_id": deck.format_id,
            "archetype": deck.archetype,
            "colors": deck.colors or [],
            "description": deck.description or "",
            "mainboard": main_cards,
            "sideboard": side_cards,
            "deterministic_analysis_summary": analysis_text(analysis),
            "deterministic_analysis": analysis,
            "structure_comparison": structure,
            "match_records": records or "Nessun risultato registrato.",
            "saved_guide_summary": guide_summary,
        },
        f"Dettagli mazzo: {deck.name} (#{deck.id})",
    )


def _tool_get_metagame_overview(
    db: Session, args: Dict[str, Any]
) -> Tuple[Dict[str, Any], str]:
    fmt = (args.get("format_id") or "pioneer").strip().lower()
    if fmt not in ("standard", "pioneer", "modern"):
        return {"error": f"Formato non valido: {fmt}"}, "Formato non valido"

    snap = deck_engine.latest_snapshot(db, fmt)
    if not snap:
        return (
            {"error": f"Nessuno snapshot del metagame presente per {fmt}."},
            f"Metagame {fmt.upper()} (vuoto)",
        )

    field = deck_engine.field_model(db, snap, 12)
    f_map = {f.archetype.id: f for f in field}
    archs = (
        db.query(MetaArchetype)
        .filter(MetaArchetype.snapshot_id == snap.id)
        .order_by(MetaArchetype.meta_share_pct.desc())
        .limit(15)
        .all()
    )
    arch_list = []
    for a in archs:
        fa = f_map.get(a.id)
        arch_list.append(
            {
                "id": a.id,
                "name": a.name,
                "tier": a.tier,
                "category": a.category,
                "colors": a.colors or [],
                "meta_share_pct": a.meta_share_pct,
                "decklists_count": a.decklists_count,
                "core_cards": [
                    f"{c.expected_copies:.1f}x {c.name}" for c in (fa.core[:8] if fa else [])
                ],
                "interaction_profile": fa.interaction if fa else {},
            }
        )

    top_cards = (
        db.query(MetaCardStat)
        .filter(MetaCardStat.snapshot_id == snap.id)
        .order_by(MetaCardStat.overall_presence_pct.desc())
        .limit(15)
        .all()
    )
    staples = [
        {
            "card_name": s.card_name,
            "overall_presence_pct": s.overall_presence_pct,
            "main_presence_pct": s.main_presence_pct,
            "main_avg_copies": s.main_avg_copies,
            "side_presence_pct": s.side_presence_pct,
            "side_avg_copies": s.side_avg_copies,
        }
        for s in top_cards
    ]

    return (
        {
            "format_id": fmt,
            "source": snap.source,
            "period_label": snap.period_label,
            "coverage_pct": snap.coverage_pct,
            "decklists_count": snap.decklists_count,
            "top_archetypes": arch_list,
            "format_staples": staples,
        },
        f"Metagame {fmt.upper()}: {len(arch_list)} archetipi",
    )


def _tool_get_archetype_details(
    db: Session, args: Dict[str, Any]
) -> Tuple[Dict[str, Any], str]:
    fmt = (args.get("format_id") or "pioneer").strip().lower()
    name = (args.get("archetype_name") or "").strip()
    snap = deck_engine.latest_snapshot(db, fmt)
    if not snap:
        return {"error": f"Nessuno snapshot per {fmt}."}, "Snapshot non trovato"

    arch = (
        db.query(MetaArchetype)
        .filter(
            MetaArchetype.snapshot_id == snap.id,
            MetaArchetype.name.ilike(f"%{name}%"),
        )
        .order_by(MetaArchetype.meta_share_pct.desc())
        .first()
    )
    if not arch:
        available = [
            a.name
            for a in db.query(MetaArchetype)
            .filter(MetaArchetype.snapshot_id == snap.id)
            .order_by(MetaArchetype.meta_share_pct.desc())
            .limit(15)
        ]
        return (
            {
                "error": f"Archetipo '{name}' non trovato in {fmt.upper()}.",
                "available_archetypes": available,
            },
            f"Archetipo '{name}' non trovato",
        )

    con = deck_engine.consensus_list(db, arch)
    consensus_data = None
    if con:
        analysis = deck_engine.analyze_list(db, con.entries())
        consensus_data = {
            "lists_aggregated": con.lists_count,
            "mainboard": [
                {
                    "quantity": c.quantity,
                    "card_name": c.card.name,
                    "inclusion_pct": c.inclusion_pct,
                    "avg_copies": c.avg_copies,
                    "is_core": c.inclusion_pct >= deck_engine.CORE_INCLUSION_PCT,
                    "mana_cost": c.card.mana_cost or "",
                    "type_line": c.card.type_line,
                    "oracle_text": oracle_text(c.card),
                }
                for c in con.main
            ],
            "sideboard": [
                {
                    "quantity": c.quantity,
                    "card_name": c.card.name,
                    "inclusion_pct": c.inclusion_pct,
                    "avg_copies": c.avg_copies,
                    "mana_cost": c.card.mana_cost or "",
                    "type_line": c.card.type_line,
                    "oracle_text": oracle_text(c.card),
                }
                for c in con.side
            ],
            "analysis_summary": analysis_text(analysis),
        }

    matchups = (
        db.query(MetaMatchup)
        .filter(
            MetaMatchup.snapshot_id == snap.id,
            or_(
                MetaMatchup.archetype_a_name == arch.name,
                MetaMatchup.archetype_b_name == arch.name,
            ),
        )
        .limit(12)
        .all()
    )
    matchup_rows = []
    for m in matchups:
        if m.archetype_a_name == arch.name:
            opp, wr = m.archetype_b_name, m.winrate_a_pct
        else:
            opp, wr = m.archetype_a_name, round(100.0 - (m.winrate_a_pct or 50.0), 1)
        matchup_rows.append(
            {
                "opponent": opp,
                "winrate_pct": wr,
                "matches_count": m.matches_count,
            }
        )

    return (
        {
            "id": arch.id,
            "name": arch.name,
            "format_id": fmt,
            "tier": arch.tier,
            "category": arch.category,
            "colors": arch.colors or [],
            "meta_share_pct": arch.meta_share_pct,
            "key_cards": arch.key_cards or [],
            "consensus_75": consensus_data,
            "recorded_matchups": matchup_rows,
        },
        f"Archetipo: {arch.name} ({fmt.upper()})",
    )


def _tool_search_cards_and_rulings(
    db: Session, args: Dict[str, Any]
) -> Tuple[Dict[str, Any], str]:
    query_str = (args.get("query") or "").strip()
    oracle_query = (args.get("oracle_query") or "").strip()
    fmt = (args.get("format_id") or "").strip().lower()
    colors_str = (args.get("colors") or "").strip().upper()
    card_type = (args.get("card_type") or "").strip()
    cmc_max = args.get("cmc_max")
    tag = (args.get("tag") or "").strip().lower()
    limit = min(max(int(args.get("limit") or 8), 1), 15)

    # Fast exact name resolution first if query is provided
    exact_card = resolve_card_by_name(db, query_str) if query_str else None

    q = db.query(Card)
    if fmt in ("standard", "pioneer", "modern"):
        q = q.filter(getattr(Card, f"legality_{fmt}") == "legal")
    if query_str:
        q = q.filter(Card.name.ilike(f"%{query_str}%"))
    if oracle_query:
        q = q.filter(Card.oracle_text.ilike(f"%{oracle_query}%"))
    if card_type:
        q = q.filter(Card.type_line.ilike(f"%{card_type}%"))
    if cmc_max is not None:
        q = q.filter(Card.cmc <= float(cmc_max))
    if tag:
        tagged_ids = (
            db.query(CardTag.oracle_id).filter(CardTag.tag == tag).subquery()
        )
        q = q.filter(Card.oracle_id.in_(tagged_ids))

    candidates = q.limit(60).all()
    if exact_card and all(c.oracle_id != exact_card.oracle_id for c in candidates):
        candidates.insert(0, exact_card)

    allowed_colors = {c for c in colors_str if c in deck_engine.WUBRG}
    if allowed_colors:
        filtered = []
        for c in candidates:
            c_cols = set(c.colors or c.color_identity or [])
            if c_cols <= allowed_colors:
                filtered.append(c)
        candidates = filtered

    # Sort by meta presence if format is known, keeping exact match first
    snap = (
        deck_engine.latest_snapshot(db, fmt)
        if fmt in ("standard", "pioneer", "modern")
        else None
    )
    stats_map: Dict[str, MetaCardStat] = {}
    if snap and candidates:
        oids = [c.oracle_id for c in candidates]
        stats_map = {
            s.oracle_id: s
            for s in db.query(MetaCardStat).filter(
                MetaCardStat.snapshot_id == snap.id,
                MetaCardStat.oracle_id.in_(oids),
            )
            if s.oracle_id
        }
        candidates.sort(
            key=lambda c: (
                0 if (exact_card and c.oracle_id == exact_card.oracle_id) else 1,
                -(stats_map[c.oracle_id].overall_presence_pct if c.oracle_id in stats_map else 0.0),
                c.name,
            )
        )

    selected = candidates[:limit]
    oids = [c.oracle_id for c in selected]
    rulings_map = rulings_for(db, oids) if oids else {}
    tags_map = tags_for(db, oids) if oids else {}

    results = []
    for c in selected:
        st = stats_map.get(c.oracle_id)
        card_rulings = [
            f"[{r.get('published_at')}] {r.get('comment')}"
            for r in (rulings_map.get(c.oracle_id) or [])[-6:]
        ]
        results.append(
            {
                "name": c.name,
                "mana_cost": c.mana_cost or "",
                "cmc": c.cmc,
                "type_line": c.type_line,
                "oracle_text": oracle_text(c),
                "power": c.power,
                "toughness": c.toughness,
                "loyalty": c.loyalty,
                "produced_mana": c.produced_mana or [],
                "legalities": {
                    "standard": c.legality_standard,
                    "pioneer": c.legality_pioneer,
                    "modern": c.legality_modern,
                },
                "functional_tags": sorted(tags_map.get(c.oracle_id) or []),
                "meta_presence": (
                    {
                        "overall_pct": st.overall_presence_pct,
                        "main_pct": st.main_presence_pct,
                        "main_avg_copies": st.main_avg_copies,
                        "side_pct": st.side_presence_pct,
                        "side_avg_copies": st.side_avg_copies,
                    }
                    if st
                    else None
                ),
                "official_rulings": card_rulings,
            }
        )

    desc_parts = [p for p in (query_str, oracle_query, tag, card_type) if p]
    label = f"Ricerca carte ({', '.join(desc_parts) or fmt or 'catalogo'}): {len(results)} risultati"
    return {"count": len(results), "cards": results}, label


def _tool_simulate_deck_changes(
    db: Session, args: Dict[str, Any]
) -> Tuple[Dict[str, Any], str]:
    deck_id = args.get("deck_id")
    swaps = args.get("swaps") or []
    deck = db.get(Deck, int(deck_id)) if deck_id is not None else None
    if not deck:
        return {"error": f"Mazzo #{deck_id} non trovato."}, "Simulazione: mazzo non trovato"

    oracle_ids = [dc.oracle_id for dc in deck.cards]
    cmap = (
        {
            c.oracle_id: c
            for c in db.query(Card).filter(Card.oracle_id.in_(oracle_ids)).all()
        }
        if oracle_ids
        else {}
    )
    entries = [
        (cmap[dc.oracle_id], dc.board, dc.quantity)
        for dc in deck.cards
        if dc.oracle_id in cmap
    ]
    before_analysis = deck_engine.analyze_list(db, entries)

    board_map: Dict[Tuple[str, str], Tuple[Card, int]] = {}
    for card, board, qty in entries:
        b = "side" if board in ("side", "companion") else "main"
        k = (b, card.name.casefold())
        prev_c, prev_q = board_map.get(k, (card, 0))
        board_map[k] = (prev_c, prev_q + qty)

    applied_log = []
    errors = []
    for s in swaps:
        b = s.get("board", "main")
        c_out_name = (s.get("card_out") or "").strip()
        c_in_name = (s.get("card_in") or "").strip()
        qty = int(s.get("quantity") or 0)
        if qty <= 0:
            continue
        out_k = (b, c_out_name.casefold())
        if out_k not in board_map or board_map[out_k][1] < qty:
            errors.append(
                f"Impossibile rimuovere {qty}x '{c_out_name}' da {b} (copie insufficienti o assente)."
            )
            continue
        c_in = resolve_card_by_name(db, c_in_name)
        if not c_in:
            errors.append(f"Carta '{c_in_name}' non trovata nel catalogo Scryfall.")
            continue
        c_out_obj, avail = board_map[out_k]
        if avail - qty > 0:
            board_map[out_k] = (c_out_obj, avail - qty)
        else:
            del board_map[out_k]
        in_k = (b, c_in.name.casefold())
        _, prev_in = board_map.get(in_k, (c_in, 0))
        board_map[in_k] = (c_in, prev_in + qty)
        applied_log.append(f"{b.upper()}: -{qty} {c_out_obj.name} / +{qty} {c_in.name}")

    after_entries = [
        (c_obj, b, q) for (b, _), (c_obj, q) in board_map.items() if q > 0
    ]
    after_analysis = deck_engine.analyze_list(db, after_entries)
    validation = validate_deck_entries(deck.format_id, after_entries)

    return (
        {
            "deck_name": deck.name,
            "format_id": deck.format_id,
            "applied_swaps": applied_log,
            "swap_errors": errors,
            "is_valid_after": validation.is_valid,
            "validation_issues": [i.message for i in validation.issues],
            "before_summary": analysis_text(before_analysis),
            "after_summary": analysis_text(after_analysis),
            "before_colors": before_analysis["colors"],
            "after_colors": after_analysis["colors"],
            "before_curve": before_analysis["curve"],
            "after_curve": after_analysis["curve"],
        },
        f"Simulazione cambi su {deck.name} ({len(applied_log)} applicati)",
    )


def _tool_get_app_help(args: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    topic = (args.get("topic") or "overview").strip().lower()
    if topic not in APP_HELP_TOPICS:
        return (
            {"topics": APP_HELP_TOPICS},
            "Guida applicazione (completa)",
        )
    return (
        {
            "topic": topic,
            "documentation": APP_HELP_TOPICS[topic],
            "all_available_topics": list(APP_HELP_TOPICS.keys()),
        },
        f"Guida applicazione: {topic}",
    )


def execute_agent_tool(
    db: Session, name: str, args: Dict[str, Any]
) -> Tuple[Dict[str, Any], str]:
    try:
        if name == "list_user_decks":
            return _tool_list_user_decks(db, args)
        if name == "get_deck_details":
            return _tool_get_deck_details(db, args)
        if name == "get_metagame_overview":
            return _tool_get_metagame_overview(db, args)
        if name == "get_archetype_details":
            return _tool_get_archetype_details(db, args)
        if name == "search_cards_and_rulings":
            return _tool_search_cards_and_rulings(db, args)
        if name == "simulate_deck_changes":
            return _tool_simulate_deck_changes(db, args)
        if name == "get_app_help":
            return _tool_get_app_help(args)
        return {"error": f"Tool sconosciuto: {name}"}, f"Tool sconosciuto: {name}"
    except Exception as exc:  # noqa: BLE001
        log.warning("agent tool %s error: %s", name, exc)
        return {"error": str(exc)}, f"Errore in {name}"


def _build_saved_decks_index(db: Session) -> str:
    try:
        archived_ids = {r[0] for r in db.query(DeckArchive.deck_id).all()}
        q = db.query(Deck)
        if archived_ids:
            q = q.filter(~Deck.id.in_(archived_ids))
        decks = q.order_by(Deck.updated_at.desc()).limit(25).all()
        if not decks:
            return "Nessun mazzo attivo salvato al momento."
        lines = []
        for d in decks:
            main_qty = sum(c.quantity for c in d.cards if c.board == "main")
            side_qty = sum(c.quantity for c in d.cards if c.board != "main")
            cols = "".join(d.colors or []) or "C"
            guide_tag = ", con guida AI" if d.guide_json else ""
            lines.append(
                f"- deck_id={d.id}: \"{d.name}\" [{d.format_id.upper()} · {d.archetype} · {cols} · {main_qty}/{side_qty}{guide_tag}]"
            )
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        return "Usa il tool list_user_decks per elencare i mazzi salvati."


def _build_agent_system_instruction(
    db: Session, req: AgentChatRequest, is_voice: bool = False
) -> str:
    ctx_parts = [f"Formato attivo nell'interfaccia: {req.format_id.upper()}"]
    if req.active_tab:
        ctx_parts.append(f"Sezione aperta dall'utente: {req.active_tab}")
    if req.active_deck_id:
        ctx_parts.append(
            f"Mazzo attualmente selezionato: '{req.active_deck_name or 'Mazzo attivo'}' (deck_id={req.active_deck_id})"
        )
    ui_context = " | ".join(ctx_parts)
    decks_index = _build_saved_decks_index(db)

    style_rules = (
        """3. **Stile di risposta (VOICE MODE CON GEMINI 3.8 LIVE)**:
   - Stai parlando a voce in tempo reale con l'utente: rispondi in **ITALIANO** naturale, fluido, diretto e conversazionale, come un coach di Magic al tavolo di preparazione.
   - Evita elenchi infiniti o simboli markdown complessi nel parlato: vai dritto al punto con i numeri chiave e le carte più importanti."""
        if is_voice
        else """3. **Stile di risposta**:
   - Rispondi in **ITALIANO** in modo chiaro, strutturato (usa paragrafi, elenchi puntati ben formattati e grassetti) e orientato alle decisioni pratiche.
   - Scrivi i nomi delle carte di Magic in **INGLESE** esatto racchiudendoli tra doppie parentesi quadre, es. `[[Fatal Push]]`, `[[Gloomlake Verge]]`, `[[Thing in the Ice]]`, così l'interfaccia li renderà cliccabili per mostrare l'anteprima della carta."""
    )

    return f"""Sei **AetherDeck Agent**, un agente esperto di Magic: The Gathering (strategia competitiva, deckbuilding, analisi del metagame, regole ufficiali CR/Oracle) e assistente integrato nella piattaforma AetherDeck.

CONTESTO ATTIVO DELL'UTENTE NELL'APP:
{ui_context}

INDICE DEI MAZZI ATTIVI SALVATI DALL'UTENTE NEL DATABASE:
{decks_index}

REGOLE OPERATIVE DELL'AGENTE (OBBLIGATORIE):
1. **Usa i tuoi Tools in modo mirato ed efficiente**:
   - Hai già qui sopra l'indice aggiornato dei mazzi salvati dall'utente (con i loro `deck_id` esatti). Se l'utente chiede solo quali mazzi ha salvato o se hai accesso ai suoi mazzi, usa direttamente l'indice (o chiama `list_user_decks` una sola volta): **NON** chiamare `get_deck_details` in serie su tutti i mazzi e **NON** tirare a indovinare `deck_id` non presenti nell'indice!
   - Chiama `get_deck_details(deck_id=...)` solo per il mazzo specifico (o i 2 mazzi) che l'utente vuole analizzare nel dettaglio.
   - Se l'utente chiede del metagame, dei tier o degli archetipi più giocati, chiama `get_metagame_overview` e/o `get_archetype_details`.
   - Se l'utente nomina carte specifiche, interazioni, costi di mana, counterspell, terre o regole, chiama `search_cards_and_rulings` per leggere il testo Oracle esatto e i ruling ufficiali Scryfall. Non andare mai a memoria sui testi delle carte.
   - Se l'utente propone o chiede l'effetto di alcuni cambi su un mazzo salvato, usa `simulate_deck_changes` per verificare l'impatto reale su fonti di Karsten, curva e legalità.
   - Se l'utente chiede come funziona AetherDeck o una sua sezione (Builder, AI Studio, Migliora Mazzo, Guida, Playtest, Qualità), chiama `get_app_help`.
2. **Rigore sulle regole MTG e lettura dell'Oracle (CR 113.1c)**:
   - Nei testi Oracle restituiti dai tool, il simbolo `¶` separa paragrafi e quindi **abilità distinte e indipendenti**. Una restrizione come `"Activate only if..."` si applica SOLO all'abilità nel medesimo paragrafo `¶`, mai alle altre abilità della carta.
   - Distingui sempre tra terre che entrano tappate su condizione (`"enters tapped unless..."`) e terre prive di `"enters tapped"` che entrano sempre stappate.
   - Verifica sempre valore di mana (CMC), bersagli legali e clausole `"can't be countered"` prima di suggerire una risposta o un counterspell.
{style_rules}
"""


def _extract_interaction_text(interaction: Any) -> str:
    txt = getattr(interaction, "output_text", None)
    if txt:
        return txt
    parts: List[str] = []
    for step in getattr(interaction, "steps", None) or []:
        s_type = getattr(step, "type", None) or (
            step.get("type") if isinstance(step, dict) else None
        )
        if s_type == "model_output":
            content = getattr(step, "content", None) or (
                step.get("content") if isinstance(step, dict) else []
            )
            for block in content or []:
                b_text = getattr(block, "text", None) or (
                    block.get("text") if isinstance(block, dict) else None
                )
                if b_text:
                    parts.append(b_text)
    return "\n".join(parts).strip()


def _extract_function_calls(interaction: Any) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for step in getattr(interaction, "steps", None) or []:
        s_type = getattr(step, "type", None) or (
            step.get("type") if isinstance(step, dict) else None
        )
        if s_type == "function_call":
            call_id = getattr(step, "id", None) or (
                step.get("id") if isinstance(step, dict) else ""
            )
            name = getattr(step, "name", None) or (
                step.get("name") if isinstance(step, dict) else ""
            )
            arguments = getattr(step, "arguments", None) or (
                step.get("arguments") if isinstance(step, dict) else {}
            )
            calls.append(
                {
                    "id": str(call_id),
                    "name": str(name),
                    "arguments": dict(arguments or {}),
                }
            )
    return calls


def run_assistant_agent(db: Session, req: AgentChatRequest) -> Dict[str, Any]:
    start_ts = time.time()
    provider = get_active_ai_provider(db)
    # Default to gemini-3.8-flash for fast interactive multi-hop agent responsiveness unless explicitly overridden
    effective_model = req.model_id or "gemini-3.8-flash"
    skill_cfg = get_skill_model_and_config(db, "assistant_agent", effective_model)
    client = provider.get_client()
    resolved_model = provider.resolve_provider_model_id(skill_cfg["model_id"])
    system_instruction = _build_agent_system_instruction(db, req, is_voice=False)

    # Build initial input: use previous_interaction_id when available, or include compact history
    current_input: Any = req.message
    prev_id = req.previous_interaction_id
    if not prev_id and req.history:
        history_lines = []
        for msg in req.history[-10:]:
            speaker = "Utente" if msg.role == "user" else "Agente"
            history_lines.append(f"{speaker}: {msg.content}")
        current_input = (
            "CRONOLOGIA RECENTE DELLA CONVERSAZIONE:\n"
            + "\n\n".join(history_lines)
            + f"\n\nNUOVA RICHIESTA DELL'UTENTE:\n{req.message}"
        )

    tool_calls_trace: List[Dict[str, Any]] = []
    interaction: Any = None

    for _hop in range(MAX_AGENT_STEPS):
        create_kwargs: Dict[str, Any] = {
            "model": resolved_model,
            "system_instruction": system_instruction,
            "input": current_input,
            "tools": AGENT_TOOL_DECLARATIONS,
            "generation_config": {
                "max_output_tokens": 8192,
                "thinking_level": "low",
            },
            "timeout": 120.0,
        }
        if prev_id:
            create_kwargs["previous_interaction_id"] = prev_id

        try:
            interaction = client.interactions.create(**create_kwargs)
        except Exception:
            # If a stale previous_interaction_id failed on the first hop, retry once with history text
            if _hop == 0 and prev_id:
                prev_id = None
                create_kwargs.pop("previous_interaction_id", None)
                if req.history:
                    history_lines = [
                        f"{'Utente' if m.role == 'user' else 'Agente'}: {m.content}"
                        for m in req.history[-10:]
                    ]
                    create_kwargs["input"] = (
                        "CRONOLOGIA RECENTE DELLA CONVERSAZIONE:\n"
                        + "\n\n".join(history_lines)
                        + f"\n\nNUOVA RICHIESTA DELL'UTENTE:\n{req.message}"
                    )
                interaction = client.interactions.create(**create_kwargs)
            else:
                raise

        provider._record_usage(interaction)
        prev_id = getattr(interaction, "id", None)

        fn_calls = _extract_function_calls(interaction)
        if not fn_calls:
            break

        result_steps: List[Dict[str, Any]] = []
        for fc in fn_calls:
            res_data, summary_label = execute_agent_tool(
                db, fc["name"], fc["arguments"]
            )
            is_err = bool(isinstance(res_data, dict) and res_data.get("error"))
            tool_calls_trace.append(
                {
                    "id": fc["id"],
                    "tool_name": fc["name"],
                    "arguments": fc["arguments"],
                    "summary": summary_label,
                    "status": "error" if is_err else "completed",
                }
            )
            step_payload: Dict[str, Any] = {
                "type": "function_result",
                "call_id": fc["id"],
                "name": fc["name"],
                "result": json.dumps(res_data, ensure_ascii=False),
            }
            if is_err:
                step_payload["is_error"] = True
            result_steps.append(step_payload)

        current_input = result_steps

    reply_text = _extract_interaction_text(interaction) if interaction else ""
    if not reply_text:
        reply_text = "Ho completato la consultazione degli strumenti ma non ho ricevuto testo aggiuntivo dal modello. Riprova o riformula la domanda."

    duration_ms = int((time.time() - start_ts) * 1000)
    db.add(
        AIRun(
            skill_name="assistant_agent",
            prompt_version="v1",
            model_id=skill_cfg["model_id"],
            provider=provider.provider_name,
            usage_json=dict(getattr(provider, "usage", None) or {}) or None,
            format_id=req.format_id,
            deck_id=req.active_deck_id,
            validation_attempts=1,
            duration_ms=duration_ms,
            input_summary={
                "message": req.message[:200],
                "tools_called": [t["tool_name"] for t in tool_calls_trace],
            },
            output_json={
                "reply": reply_text,
                "tool_calls": tool_calls_trace,
            },
        )
    )
    db.commit()

    return {
        "reply": reply_text,
        "interaction_id": getattr(interaction, "id", None),
        "tool_calls": tool_calls_trace,
        "model_id": skill_cfg["model_id"],
        "duration_ms": duration_ms,
    }


LIVE_VOICE_MODEL = "gemini-3.8-live"


async def run_live_voice_session(
    websocket: WebSocket,
    db: Session,
    format_id: str = "pioneer",
    active_deck_id: Optional[int] = None,
    active_deck_name: Optional[str] = None,
    active_tab: Optional[str] = None,
) -> None:
    """Bidirectional real-time Voice Mode session powered by Gemini 3.8 Live (`gemini-3.8-live`) with full agent tools."""
    await websocket.accept()
    fmt: Literal["standard", "pioneer", "modern"] = (
        format_id  # type: ignore[assignment]
        if format_id in ("standard", "pioneer", "modern")
        else "pioneer"
    )
    req_ctx = AgentChatRequest(
        message="voice_session",
        format_id=fmt,
        active_tab=active_tab,
        active_deck_id=active_deck_id,
        active_deck_name=active_deck_name,
    )

    try:
        provider = get_active_ai_provider(db)
        client = provider.get_client()
    except Exception as exc:  # noqa: BLE001
        await websocket.send_json(
            {"type": "error", "message": f"Configurazione AI non valida: {exc}"}
        )
        await websocket.close()
        return

    system_instruction = _build_agent_system_instruction(db, req_ctx, is_voice=True)
    fdecls = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            behavior="BLOCKING",
            parameters_json_schema=t["parameters"],
        )
        for t in AGENT_TOOL_DECLARATIONS
    ]
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part(text=system_instruction)]
        ),
        tools=[types.Tool(function_declarations=fdecls)],
    )

    try:
        async with client.aio.live.connect(
            model=LIVE_VOICE_MODEL, config=config
        ) as session:
            await websocket.send_json(
                {
                    "type": "status",
                    "status": "listening",
                    "model_id": LIVE_VOICE_MODEL,
                }
            )

            async def _client_to_gemini() -> None:
                try:
                    while True:
                        raw = await websocket.receive_text()
                        payload = json.loads(raw)
                        msg_type = payload.get("type")
                        if msg_type == "audio":
                            b64 = payload.get("data") or ""
                            if b64:
                                pcm_bytes = base64.b64decode(b64)
                                await session.send_realtime_input(
                                    audio=types.Blob(
                                        data=pcm_bytes,
                                        mime_type="audio/pcm;rate=16000",
                                    )
                                )
                        elif msg_type == "audio_stream_end":
                            await session.send_realtime_input(audio_stream_end=True)
                        elif msg_type == "text":
                            txt = (payload.get("text") or "").strip()
                            if txt:
                                await session.send_realtime_input(text=txt)
                        elif msg_type == "stop":
                            break
                except WebSocketDisconnect:
                    return
                except Exception as exc:  # noqa: BLE001
                    log.debug("live voice client_to_gemini closed: %s", exc)
                    return

            async def _gemini_to_client() -> None:
                try:
                    while True:
                        async for msg in session.receive():
                            if msg.tool_call and msg.tool_call.function_calls:
                                await websocket.send_json(
                                    {"type": "status", "status": "thinking"}
                                )
                                fresps: List[types.FunctionResponse] = []
                                for fc in msg.tool_call.function_calls:
                                    call_id = str(fc.id or fc.name)
                                    call_args = dict(fc.args or {})
                                    await websocket.send_json(
                                        {
                                            "type": "tool_call",
                                            "id": call_id,
                                            "tool_name": fc.name,
                                            "arguments": call_args,
                                            "summary": f"Esecuzione {fc.name}...",
                                            "status": "running",
                                        }
                                    )
                                    res_data, summary_label = execute_agent_tool(
                                        db, fc.name, call_args
                                    )
                                    is_err = bool(
                                        isinstance(res_data, dict)
                                        and res_data.get("error")
                                    )
                                    await websocket.send_json(
                                        {
                                            "type": "tool_call",
                                            "id": call_id,
                                            "tool_name": fc.name,
                                            "arguments": call_args,
                                            "summary": summary_label,
                                            "status": "error" if is_err else "completed",
                                        }
                                    )
                                    fresps.append(
                                        types.FunctionResponse(
                                            id=fc.id,
                                            name=fc.name,
                                            response={"result": res_data},
                                        )
                                    )
                                await session.send_tool_response(
                                    function_responses=fresps
                                )

                            sc = msg.server_content
                            if sc:
                                if sc.model_turn and sc.model_turn.parts:
                                    for part in sc.model_turn.parts:
                                        if (
                                            part.inline_data
                                            and part.inline_data.data
                                        ):
                                            b64_out = base64.b64encode(
                                                part.inline_data.data
                                            ).decode("ascii")
                                            await websocket.send_json(
                                                {
                                                    "type": "audio",
                                                    "data": b64_out,
                                                    "sample_rate": 24000,
                                                }
                                            )
                                if (
                                    sc.input_transcription
                                    and sc.input_transcription.text
                                ):
                                    await websocket.send_json(
                                        {
                                            "type": "input_transcript",
                                            "text": sc.input_transcription.text,
                                        }
                                    )
                                if (
                                    sc.output_transcription
                                    and sc.output_transcription.text
                                ):
                                    await websocket.send_json(
                                        {
                                            "type": "output_transcript",
                                            "text": sc.output_transcription.text,
                                        }
                                    )
                                if sc.interrupted is True:
                                    await websocket.send_json({"type": "interrupted"})
                                if sc.turn_complete is True:
                                    await websocket.send_json(
                                        {"type": "turn_complete"}
                                    )
                except WebSocketDisconnect:
                    return
                except Exception as exc:  # noqa: BLE001
                    log.debug("live voice gemini_to_client closed: %s", exc)
                    return

            t1 = asyncio.create_task(_client_to_gemini())
            t2 = asyncio.create_task(_gemini_to_client())
            done, pending = await asyncio.wait(
                [t1, t2], return_when=asyncio.FIRST_COMPLETED
            )
            for p in pending:
                p.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("Gemini 3.8 Live voice session error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
