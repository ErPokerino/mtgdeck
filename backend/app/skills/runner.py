import math
import time
import logging
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.models import (
    GuideVersion,
    GuideJob,
    utcnow,
    AIRun,
    Card,
    Deck,
    MetaArchetype,
    MetaCardStat,
)
from app.services.ai_provider import get_active_ai_provider, get_skill_model_and_config
from app.services.deck_validator import (
    castable_with_colors,
    export_decklist_formats,
    parse_decklist_text,
    resolve_card_by_name,
    validate_deck_entries,
)
from app.services.guide_quality import (
    validate_swaps,
    weighted_meta_estimate,
    evidence_context,
    legality_report,
    require_fresh_catalog,
)
from app.skills.schemas import (
    AIDeckGuideRequest,
    AIDeckImprovementOutput,
    AIDeckImprovementRequest,
    AIMatchupSpotOutput,
    AIMatchupSpotRequest,
)

from app.services import deck_engine
from app.services.card_knowledge import rulings_for
from app.services.guide_quality import key
from app.skills.common import load_skill_prompt
from app.skills.deck_generation import (
    analysis_text,
    card_line,
    card_stats,
    consensus_block,
    field_text_block,
    oracle_text,
)


def _resolve_deck_entries_for_ai(
    db: Session,
    deck_id: Optional[int],
    decklist_text: Optional[str],
) -> Tuple[Optional[Deck], List[Tuple[Card, str, int]]]:
    if deck_id:
        deck = db.query(Deck).filter(Deck.id == deck_id).first()
        if not deck:
            raise ValueError("Mazzo non trovato.")
        if deck:
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
            return deck, entries
    if decklist_text:
        entries, unresolved = parse_decklist_text(db, decklist_text)
        if unresolved:
            raise ValueError("Carte non riconosciute: " + ", ".join(unresolved))
        return None, entries
    return None, []


GUIDE_FIELD_SIZE = 8
GUIDE_CONSENSUS_LISTS = 4
GUIDE_OPPONENT_CARDS = 100
RULINGS_PER_CARD = 4


def _rulings_text(db: Session, entries) -> str:
    rulings = rulings_for(db, [c.oracle_id for c, _, _ in entries])
    lines = []
    for card, _, _ in entries:
        for r in (rulings.get(card.oracle_id) or [])[-RULINGS_PER_CARD:]:
            lines.append(f"- {card.name}: {r.get('comment')}")
    return "\n".join(dict.fromkeys(lines))


def _guide_context(db: Session, snapshot, entries) -> Dict[str, Any]:
    """Observed facts for every main matchup plus app-computed facts on our list."""
    analysis = deck_engine.analyze_list(db, entries)
    ruling_text = _rulings_text(db, entries)
    if not snapshot:
        return {
            "archetypes": [],
            "field": field_text_block(None, [], 0.0),
            "consensus": "",
            "opponent_oracle": "",
            "known_cards": {},
            "analysis": analysis_text(analysis),
            "rulings": ruling_text,
        }
    field_model = deck_engine.field_model(db, snapshot, GUIDE_FIELD_SIZE)
    archs = [f.archetype for f in field_model]
    all_shares = sum(
        a.meta_share_pct
        for a in db.query(MetaArchetype).filter(MetaArchetype.snapshot_id == snapshot.id)
    )
    consensus = []
    for arch in archs[:GUIDE_CONSENSUS_LISTS]:
        con = deck_engine.consensus_list(db, arch)
        if con:
            consensus.append(consensus_block(con, with_oracle=False))
    opp_ids: List[str] = []
    for f in field_model:
        for c in f.interaction_cards + f.core + f.likely_sideboard:
            if not c.is_land and c.oracle_id not in opp_ids:
                opp_ids.append(c.oracle_id)
    opp_ids = opp_ids[:GUIDE_OPPONENT_CARDS]
    cards = {c.oracle_id: c for c in db.query(Card).filter(Card.oracle_id.in_(opp_ids))}
    return {
        "archetypes": archs,
        "field": field_text_block(snapshot, field_model, all_shares),
        "consensus": "\n\n".join(consensus),
        "opponent_oracle": "\n".join(card_line(cards[o]) for o in opp_ids if o in cards),
        "known_cards": {
            key(a.name): {key(u.card_name) for u in a.cards} for a in archs
        },
        "analysis": analysis_text(analysis),
        "rulings": ruling_text,
    }


def _format_entries_with_oracle(entries: List[Tuple[Card, str, int]]) -> str:
    main_lines = []
    side_lines = []
    total = sum(q for _, b, q in entries if b == "main")
    for c, board, qty in entries:
        probabilities = ""
        if board == "main" and total >= 10:

            def at_least_one(draws, qty=qty):
                return 100 * (
                    1
                    - (
                        math.comb(total - qty, draws) / math.comb(total, draws)
                        if total - qty >= draws
                        else 0
                    )
                )

            probabilities = f" | P(almeno 1 copia): iniziali 7={at_least_one(7):.1f}%, viste 9={at_least_one(9):.1f}%, viste 10={at_least_one(10):.1f}%. Senza mulligan, cantrip o selezione; non è probabilità di lancio."
        facts = card_stats(c)
        if not deck_engine.is_land_card(c):
            facts += f" MV {float(c.cmc or 0):g}"
        line = f"{qty}x {c.name} ({c.mana_cost or 'Land'}) [{c.type_line}]{facts} — {oracle_text(c)}{probabilities}"
        if board == "main":
            main_lines.append(line)
        else:
            side_lines.append(line)
    return (
        "MAINBOARD:\n"
        + "\n".join(main_lines)
        + "\n\nSIDEBOARD:\n"
        + "\n".join(side_lines)
    )


def run_deck_guide_skill(
    db: Session,
    req: AIDeckGuideRequest,
    progress=None,
    resume_draft=None,
    expected_signature=None,
    job_id=None,
) -> Dict[str, Any]:
    trace = {
        "phase": "preflight",
        "attempts": 1,
        "progress": progress,
        "resume_draft": resume_draft,
        "expected_signature": expected_signature,
        "job_id": job_id,
    }
    started = time.time()
    try:
        return _run_deck_guide_skill(db, req, trace)
    except Exception as exc:
        db.rollback()
        # Keep rejected drafts out of the guide library, but retain enough evidence
        # to diagnose a failed review without paying for another complete draft.
        # Provider exceptions may contain request credentials: persist only their type.
        error = (
            str(exc)
            if isinstance(exc, ValueError) and str(exc).startswith("Guida non salvata:")
            else type(exc).__name__
        )
        try:
            db.add(
                AIRun(
                    skill_name="deck_guide",
                    prompt_version=trace.get("prompt_version", "unknown"),
                    model_id=trace.get("model_id", req.model_id or "unknown"),
                    provider=trace.get("provider", "unknown"),
                    format_id=trace.get("format_id", req.format_id),
                    usage_json=dict(getattr(trace.get("provider_obj"), "usage", None) or {})
                    or None,
                    deck_id=req.deck_id,
                    validation_attempts=trace["attempts"],
                    duration_ms=int((time.time() - started) * 1000),
                    input_summary={"status": "failed", "phase": trace["phase"]},
                    output_json={
                        "status": "failed",
                        "phase": trace["phase"],
                        "error": error,
                        "validation_errors": trace.get("errors", []),
                        "draft": trace.get("draft"),
                        "review": trace.get("last_review"),
                    },
                )
            )
            db.commit()
        except Exception:  # noqa: BLE001 - recording a failure must not hide the original error
            db.rollback()
            logging.getLogger("uvicorn.error").warning(
                "Unable to record failed deck_guide run"
            )
        raise


def _run_deck_guide_skill(
    db: Session, req: AIDeckGuideRequest, trace: dict
) -> Dict[str, Any]:
    start_ts = time.time()
    require_fresh_catalog(db)
    provider = get_active_ai_provider(db)
    skill_cfg = get_skill_model_and_config(db, "deck_guide", req.model_id)
    trace["provider_obj"] = provider
    prompt_ver, sys_prompt = load_skill_prompt(
        "deck_guide", skill_cfg["prompt_version"]
    )
    trace.update(
        model_id=skill_cfg["model_id"],
        provider=provider.provider_name,
        prompt_version=prompt_ver,
    )

    def phase(name):
        trace["phase"] = name
        if trace.get("progress"):
            trace["progress"](trace)
        logging.getLogger("uvicorn.error").info(
            "deck_guide deck=%s phase=%s attempt=%s",
            req.deck_id,
            name,
            trace["attempts"],
        )

    deck_obj, entries = _resolve_deck_entries_for_ai(db, req.deck_id, req.decklist_text)
    if not entries:
        raise ValueError(
            "Il mazzo selezionato è vuoto o non valido. Aggiungi carte prima di generare la guida."
        )

    fmt = (deck_obj.format_id if deck_obj else req.format_id).lower()
    trace["format_id"] = fmt
    deck_title = deck_obj.name if deck_obj else req.deck_name
    report = validate_deck_entries(fmt, entries)
    if not report.is_valid:
        raise ValueError(
            "Correggi la lista prima della guida: "
            + "; ".join(i.message for i in report.issues if i.severity == "error")
        )

    latest_snap = deck_engine.latest_snapshot(db, fmt)
    ctx = _guide_context(db, latest_snap, entries)
    from app.services.quality import records_text

    records = records_text(db, deck_obj.id if deck_obj else None)
    archs = ctx["archetypes"]
    oracle_block = _format_entries_with_oracle(entries)
    user_prompt = (
        evidence_context(db, fmt, latest_snap)
        + f"""
GUIDA COMPETITIVA E SIDEBOARD GUIDE PER QUESTA LISTA:
- Nome: {deck_title}
- Formato: {fmt.upper()}

=== LISTA COMPLETA CON TESTI ORACLE ===
{oracle_block}

=== RULING UFFICIALI DELLE NOSTRE CARTE (Scryfall) ===
{ctx["rulings"] or "nessuno"}

=== RISULTATI REALI DEL GIOCATORE CON QUESTA LISTA ===
{records or "nessuno registrato"}

=== ANALISI DELLA LISTA (calcolata dall'app: citala, non ricalcolarla) ===
{ctx["analysis"]}

{ctx["field"]}

=== LISTE DI CONSENSO DEI PRINCIPALI ARCHETIPI (core e flex osservati) ===
{ctx["consensus"] or "non disponibili"}

=== TESTI ORACLE DELLE CARTE AVVERSARIE CHIAVE ===
{ctx["opponent_oracle"] or "non disponibili"}

MATCHUP OBBLIGATORI (usa questi nomi esatti): {", ".join(a.name for a in archs) or "nessun metagame disponibile"}
""".strip()
    )

    from app.services.guide_pipeline import review_guide

    signature = hashlib.sha256(
        json.dumps(
            [
                fmt,
                skill_cfg["model_id"],
                sorted((c.oracle_id, b, q) for c, b, q in entries),
            ]
        ).encode()
    ).hexdigest()
    trace["signature"] = signature
    if trace.get("expected_signature") and signature != trace["expected_signature"]:
        raise ValueError(
            "La lista o il modello sono cambiati. Avvia una nuova guida per questa configurazione."
        )
    guide_out = review_guide(
        provider,
        skill_cfg["model_id"],
        sys_prompt,
        user_prompt,
        f"{oracle_block}\nANALISI CALCOLATA DALL'APP (fatti, citabili):\n{ctx['analysis']}"
        f"\nRULING:\n{ctx['rulings']}\nCARTE AVVERSARIE:\n{ctx['opponent_oracle']}",
        entries,
        archs,
        trace,
        phase,
        trace.get("resume_draft"),
        max_reviews=1 + max(0, skill_cfg["max_retries"]),
        known_opponent_cards=ctx["known_cards"],
    )
    attempts = trace["attempts"]
    phase("weighted_estimate")
    guide = guide_out.model_dump()
    guide["meta_estimate"] = weighted_meta_estimate(guide, archs, latest_snap)
    guide["legality"] = legality_report(db, fmt, entries)
    guide["deck_name"] = deck_title
    guide["format_id"] = fmt
    guide["model_id"] = skill_cfg["model_id"]
    guide["generated_at"] = utcnow().isoformat()
    guide["quality_review"] = {
        "status": "passed",
        "open_issues": [],
        "revision_count": attempts - 1,
        "checked_at": guide["generated_at"],
        "checks": [
            "Legalità della lista nel formato",
            "Copie, mani tenute lanciabili e sidate",
            "Conteggi e forza/costituzione citati nel testo",
            "Copertura dei matchup e carte avversarie osservate",
            "Revisione Oracle e ruling, con verifica di ogni correzione",
        ],
    }
    snapshot = [
        {"oracle_id": c.oracle_id, "card_name": c.name, "board": b, "quantity": q}
        for c, b, q in entries
    ]
    guide["decklist"] = snapshot
    phase("ready_to_save")
    version = GuideVersion(
        deck_id=deck_obj.id if deck_obj else None,
        deck_name=deck_title,
        format_id=fmt,
        model_id=skill_cfg["model_id"],
        deck_snapshot=snapshot,
        guide_json=guide,
    )
    db.add(version)
    if deck_obj:
        deck_obj.guide_json = guide
    duration_ms = int((time.time() - start_ts) * 1000)
    db.add(
        AIRun(
            skill_name="deck_guide",
            prompt_version=prompt_ver,
            model_id=skill_cfg["model_id"],
            provider=provider.provider_name,
            format_id=fmt,
            deck_id=deck_obj.id if deck_obj else None,
            usage_json=dict(getattr(provider, "usage", None) or {}) or None,
            validation_attempts=attempts,
            duration_ms=duration_ms,
            input_summary={"deck_name": deck_title},
            output_json=guide,
        )
    )
    phase("save")
    db.flush()
    result = {
        "guide": guide,
        "meta": {
            "guide_id": version.id,
            "model_id": skill_cfg["model_id"],
            "duration_ms": duration_ms,
            "prompt_version": prompt_ver,
        },
    }
    if trace.get("job_id"):
        published = (
            db.query(GuideJob)
            .filter(GuideJob.id == trace["job_id"], GuideJob.status == "running")
            .update(
                {
                    "status": "completed",
                    "phase": "completed",
                    "result_json": result,
                    "finished_at": utcnow(),
                },
                synchronize_session=False,
            )
        )
        if published != 1:
            raise ValueError("Generazione annullata prima della pubblicazione.")
    db.commit()
    return result


def _archetype_entries(db: Session, archetype: MetaArchetype) -> List[Tuple[Card, str, int]]:
    """The field's stock list stands for an archetype; a single sample list only as a fallback."""
    consensus = deck_engine.consensus_list(db, archetype)
    if consensus and sum(c.quantity for c in consensus.main) >= 60:
        return consensus.entries()
    if archetype.sample_decklists:
        entries, _ = parse_decklist_text(db, archetype.sample_decklists[0].get("decklist_text", ""))
        return entries
    return []


def bo3_winrate(game1_pct: float, postboard_pct: float) -> float:
    """Match win probability from Game 1 and post-board estimates: W-W, W-L-W, L-W-W."""
    g1, post = game1_pct / 100, postboard_pct / 100
    return round(100 * (g1 * post + g1 * (1 - post) * post + (1 - g1) * post * post), 1)


def _deck_colors(entries: List[Tuple[Card, str, int]]) -> List[str]:
    """Colours the spells ask for. Lands say what the deck can pay, not what it plays: a
    five-colour utility land must not turn a two-colour deck into a five-colour one."""
    colors = {
        col
        for card, _, _ in entries
        if not deck_engine.is_land_card(card)
        for col in (card.colors or card.color_identity or [])
    }
    if not colors:
        colors = {col for card, _, _ in entries for col in (card.produced_mana or [])}
    return [c for c in deck_engine.WUBRG if c in colors]


def run_matchup_spot_skill(
    db: Session,
    req: AIMatchupSpotRequest,
    progress=None,
) -> Dict[str, Any]:
    start_ts = time.time()

    def step(phase: str) -> None:
        if progress:
            progress(phase)

    step("context")
    require_fresh_catalog(db)
    provider = get_active_ai_provider(db)
    skill_cfg = get_skill_model_and_config(db, "matchup_spot", req.model_id)
    prompt_ver, sys_prompt = load_skill_prompt(
        "matchup_spot", skill_cfg["prompt_version"]
    )

    deck_a_obj, entries_a = _resolve_deck_entries_for_ai(
        db, req.deck_a_id, req.deck_a_text
    )
    if not entries_a:
        raise ValueError("Mazzo A vuoto o non valido.")

    # Mazzo B può venire da un deck_id salvato, da un archetipo del meta o da testo incollato
    deck_b_name = req.deck_b_name
    entries_b: List[Tuple[Card, str, int]] = []
    if req.deck_b_archetype_id:
        arch_b = (
            db.query(MetaArchetype)
            .filter(MetaArchetype.id == req.deck_b_archetype_id)
            .first()
        )
        if arch_b and arch_b.format_id != req.format_id:
            raise ValueError("Archetipo avversario di un formato diverso.")
        if arch_b:
            deck_b_name = arch_b.name
            entries_b = _archetype_entries(db, arch_b)
    if not entries_b:
        deck_b_obj, entries_b = _resolve_deck_entries_for_ai(
            db, req.deck_b_id, req.deck_b_text
        )
        if deck_b_obj:
            deck_b_name = deck_b_obj.name

    if not entries_b:
        raise ValueError("Mazzo B (Avversario) vuoto o non valido.")
    for entries, obj in ((entries_a, deck_a_obj), (entries_b, None)):
        if obj and obj.format_id != req.format_id:
            raise ValueError(
                "Il formato del mazzo non corrisponde al formato selezionato."
            )
        report = validate_deck_entries(req.format_id, entries)
        if not report.is_valid:
            raise ValueError(
                "Lista non valida: "
                + "; ".join(i.message for i in report.issues if i.severity == "error")
            )

    deck_a_name = deck_a_obj.name if deck_a_obj else req.deck_a_name
    fmt = req.format_id.lower()

    user_prompt = f"""
ANALISI MATCHUP SPOT TESTA A TESTA ({fmt.upper()}):

=== MAZZO A (PILOTA: {deck_a_name}) ===
{_format_entries_with_oracle(entries_a)}

=== MAZZO B (AVVERSARIO: {deck_b_name}) ===
{_format_entries_with_oracle(entries_b)}

=== RULING UFFICIALI DELLE CARTE (Scryfall) ===
{_rulings_text(db, entries_a + entries_b) or "nessuno"}
""".strip()

    step("analysis")
    # A paid analysis is not thrown away for an unbalanced sideboard plan: it gets repaired.
    prompt = user_prompt
    max_attempts = 1 + max(0, skill_cfg["max_retries"])
    for attempt in range(max_attempts):
        matchup_out: AIMatchupSpotOutput = provider.generate_structured(
            model_id=skill_cfg["model_id"],
            system_instruction=sys_prompt,
            user_prompt=prompt,
            response_model=AIMatchupSpotOutput,
        )
        errors = [
            f"Mazzo A: {e}"
            for e in validate_swaps(matchup_out.sideboard_plan_for_deck_a.model_dump(), entries_a)
        ] + [
            f"Mazzo B: {e}"
            for e in validate_swaps(matchup_out.sideboard_plan_for_deck_b.model_dump(), entries_b)
        ]
        if not errors:
            break
        if attempt == max_attempts - 1:
            raise ValueError("Analisi non salvata: " + "; ".join(errors))
        step("repair")
        prompt = (
            user_prompt
            + "\n\nCORREGGI QUESTI ERRORI DEI PIANI DI SIDEBOARD (IN dalla side, OUT dal main, bilanciati):\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\n\nANALISI PRECEDENTE (JSON):\n"
            + matchup_out.model_dump_json()
        )
    # The Bo3 figure follows from the two game estimates: it cannot contradict them.
    matchup_out.overall_expected_winrate_deck_a_pct = bo3_winrate(
        matchup_out.expected_winrate_deck_a_pre_side_pct,
        matchup_out.expected_winrate_deck_a_post_side_pct,
    )
    step("save")
    duration_ms = int((time.time() - start_ts) * 1000)
    ai_run = AIRun(
        skill_name="matchup_spot",
        prompt_version=prompt_ver,
        model_id=skill_cfg["model_id"],
        provider=provider.provider_name,
        usage_json=dict(getattr(provider, "usage", None) or {}) or None,
        format_id=fmt,
        validation_attempts=attempt + 1,
        duration_ms=duration_ms,
        input_summary={"deck_a": deck_a_name, "deck_b": deck_b_name, "format_id": fmt},
        output_json=matchup_out.model_dump(),
    )
    db.add(ai_run)
    db.commit()

    return {
        "analysis": matchup_out,
        "meta": {
            "skill": "matchup_spot",
            "prompt_version": prompt_ver,
            "model_id": skill_cfg["model_id"],
            "provider": provider.provider_name,
            "duration_ms": duration_ms,
        },
    }



def _improvement_candidate_pool(
    db: Session,
    fmt: str,
    snapshot,
    entries: List[Tuple[Card, str, int]],
) -> str:
    """Legal spells and lands observed in the format and castable with the deck's colours."""
    leg_col = getattr(Card, f"legality_{fmt}")
    deck_colors = set(_deck_colors(entries))
    in_deck = {card.oracle_id for card, _, _ in entries}
    stats = (
        {
            s.oracle_id: s
            for s in db.query(MetaCardStat).filter(MetaCardStat.snapshot_id == snapshot.id)
            if s.oracle_id
        }
        if snapshot
        else {}
    )
    observed = (
        db.query(Card).filter(leg_col == "legal", Card.oracle_id.in_(list(stats))).all()
        if stats
        else db.query(Card).filter(leg_col == "legal").limit(200).all()
    )
    spells, lands = [], []
    for c in observed:
        if c.oracle_id in in_deck:
            continue
        if deck_engine.is_land_card(c):
            if c.is_basic_land:
                continue
            produced = set(c.produced_mana or [])
            if (
                deck_colors
                and produced
                and not (produced & deck_colors)
                and not (set(c.color_identity or []) <= deck_colors)
            ):
                continue
            lands.append(c)
        elif not deck_colors or castable_with_colors(c, deck_colors):
            spells.append(c)
    if stats:
        spells.sort(key=lambda c: -stats[c.oracle_id].overall_presence_pct)
        lands.sort(key=lambda c: -stats[c.oracle_id].overall_presence_pct)
    spell_lines = [card_line(c, stats.get(c.oracle_id)) for c in spells[:120]]
    land_lines = [card_line(c, stats.get(c.oracle_id)) for c in lands[:40]]
    return (
        f"=== POOL CARTE CANDIDATE LEGALI NEI COLORI DEL MAZZO ({len(spell_lines)} magie, {len(land_lines)} terre) ===\n"
        + ("\n".join(spell_lines) or "Nessuna magia osservata.")
        + "\n\nTerre candidate:\n"
        + ("\n".join(land_lines) or "Nessuna terra osservata.")
    )


def _validate_and_apply_improvement_swaps(
    db: Session,
    fmt: str,
    entries: List[Tuple[Card, str, int]],
    output: AIDeckImprovementOutput,
) -> Tuple[List[str], List[Tuple[Card, str, int]], List[str]]:
    """Validate suggested_swaps and candidate_cards against the real deck and format catalog.
    Returns (hard_errors, improved_entries, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []
    leg_col = f"legality_{fmt}"

    board_map: Dict[Tuple[str, str], Tuple[Card, int]] = {}
    for card, board, qty in entries:
        b = "side" if board in ("side", "companion") else "main"
        k = (b, key(card.name))
        prev_card, prev_qty = board_map.get(k, (card, 0))
        board_map[k] = (prev_card, prev_qty + qty)

    working: Dict[Tuple[str, str], Tuple[Card, int]] = dict(board_map)
    valid_swaps = []
    payable_colors = {
        col
        for card, board, _ in entries
        if board == "main" and deck_engine.land_face(card)
        for col in (card.produced_mana or [])
    }

    for swap in output.suggested_swaps:
        board = swap.board
        out_k = (board, key(swap.card_out))
        if out_k not in working or working[out_k][1] <= 0:
            errors.append(
                f"Swap non valido ({board}): '{swap.card_out}' non è presente nel {board}."
            )
            continue
        card_out_obj, avail_qty = working[out_k]
        if swap.quantity > avail_qty:
            errors.append(
                f"Swap non valido ({board}): chiedi di rimuovere {swap.quantity}x '{swap.card_out}', ma ne restano solo {avail_qty}x nel {board}."
            )
            continue
        card_in_obj = resolve_card_by_name(db, swap.card_in)
        if not card_in_obj:
            errors.append(
                f"Swap non valido ({board}): '{swap.card_in}' non esiste nel catalogo Scryfall."
            )
            continue
        if getattr(card_in_obj, leg_col, "not_legal") != "legal":
            errors.append(
                f"Swap non valido ({board}): '{card_in_obj.name}' non è legale in {fmt.upper()}."
            )
            continue
        if card_in_obj.oracle_id == card_out_obj.oracle_id:
            errors.append(
                f"Swap ridondante ({board}): '{swap.card_out}' e '{swap.card_in}' sono la stessa carta."
            )
            continue

        # Check copy limit across main + side after applying this swap
        in_k_main = ("main", key(card_in_obj.name))
        in_k_side = ("side", key(card_in_obj.name))
        current_total = (working.get(in_k_main, (card_in_obj, 0))[1]) + (
            working.get(in_k_side, (card_in_obj, 0))[1]
        )
        max_copies = (
            None if card_in_obj.is_basic_land else (card_in_obj.max_copies or 4)
        )
        if max_copies is not None and current_total + swap.quantity > max_copies:
            errors.append(
                f"Swap non valido ({board}): inserire {swap.quantity}x '{card_in_obj.name}' supererebbe il limite di {max_copies} copie totali (attuali: {current_total})."
            )
            continue

        # Apply swap to working copy
        new_out_qty = avail_qty - swap.quantity
        if new_out_qty > 0:
            working[out_k] = (card_out_obj, new_out_qty)
        else:
            del working[out_k]

        in_k = (board, key(card_in_obj.name))
        _, prev_in_qty = working.get(in_k, (card_in_obj, 0))
        working[in_k] = (card_in_obj, prev_in_qty + swap.quantity)

        swap.card_out = card_out_obj.name
        swap.card_in = card_in_obj.name
        valid_swaps.append(swap)
        if not castable_with_colors(card_in_obj, payable_colors):
            warnings.append(
                f"{card_in_obj.name} ({card_in_obj.mana_cost}) chiede colori che le terre del mazzo non "
                "producono: serve un intervento anche sulla manabase."
            )

    valid_candidates = []
    for cand in output.candidate_cards:
        c_obj = resolve_card_by_name(db, cand.card_name)
        if not c_obj:
            errors.append(
                f"Carta papabile non trovata nel catalogo: '{cand.card_name}'."
            )
            continue
        if getattr(c_obj, leg_col, "not_legal") != "legal":
            errors.append(
                f"Carta papabile non legale in {fmt.upper()}: '{c_obj.name}'."
            )
            continue
        cand.card_name = c_obj.name
        valid_candidates.append(cand)

    output.suggested_swaps = valid_swaps
    output.candidate_cards = valid_candidates

    improved_entries: List[Tuple[Card, str, int]] = [
        (card_obj, b, q) for (b, _), (card_obj, q) in working.items() if q > 0
    ]
    return errors, improved_entries, warnings


def run_deck_improvement_skill(
    db: Session,
    req: AIDeckImprovementRequest,
    progress=None,
) -> Dict[str, Any]:
    start_ts = time.time()

    def step(phase: str) -> None:
        if progress:
            progress(phase)

    step("context")
    require_fresh_catalog(db)
    provider = get_active_ai_provider(db)
    skill_cfg = get_skill_model_and_config(db, "deck_improvement", req.model_id)
    prompt_ver, sys_prompt = load_skill_prompt(
        "deck_improvement", skill_cfg["prompt_version"]
    )

    deck_obj, entries = _resolve_deck_entries_for_ai(
        db, req.deck_id, req.decklist_text
    )
    if not entries:
        raise ValueError("Mazzo vuoto o non valido. Seleziona un mazzo o incolla una lista.")

    fmt = (deck_obj.format_id if deck_obj else req.format_id).lower()
    deck_title = deck_obj.name if deck_obj else req.deck_name
    requested_arch = (deck_obj.archetype if deck_obj and deck_obj.archetype else None)

    report = validate_deck_entries(fmt, entries)
    validation_notes = [i.message for i in report.issues] if report.issues else []

    latest_snap = deck_engine.latest_snapshot(db, fmt)
    ctx = _guide_context(db, latest_snap, entries)
    before_analysis = deck_engine.analyze_list(db, entries)
    before_structure = deck_engine.structure_summary(db, entries, fmt, requested_arch)
    pool_block = _improvement_candidate_pool(db, fmt, latest_snap, entries)

    from app.services.quality import records_text

    records = records_text(db, deck_obj.id if deck_obj else None)
    oracle_block = _format_entries_with_oracle(entries)

    structure_lines = []
    if before_structure.get("nearest"):
        structure_lines.append(
            "Archetipi del meta strutturalmente più simili: "
            + ", ".join(
                f"{n['archetype']} ({n['category']}, dist {n['distance']})"
                for n in before_structure["nearest"]
            )
        )
    if before_structure.get("issues"):
        structure_lines.extend(before_structure["issues"])

    base_prompt = (
        evidence_context(db, fmt, latest_snap)
        + f"""
ANALISI PUNTI DEBOLI E MIGLIORAMENTO MAZZO:
- Nome mazzo: {deck_title}
- Formato: {fmt.upper()}
- Archetipo dichiarato: {requested_arch or "da determinare"}
- Focus / Richiesta specifica dell'utente: {req.user_prompt or "Ottimizzazione competitiva generale contro il metagame attuale"}

=== LISTA ATTUALE CON TESTI ORACLE ===
{oracle_block}

=== RULING UFFICIALI DELLE NOSTRE CARTE (Scryfall) ===
{ctx["rulings"] or "nessuno"}

=== ANALISI DETERMINISTICA DELLA LISTA ATTUALE (calcolata dall'app) ===
{ctx["analysis"]}
{"Note di validazione: " + "; ".join(validation_notes) if validation_notes else "Lista legale 60/15."}
{"Struttura: " + " | ".join(structure_lines) if structure_lines else ""}

=== RISULTATI REALI DEL GIOCATORE ===
{records or "nessuno registrato"}

{ctx["field"]}

=== LISTE DI CONSENSO DEI PRINCIPALI ARCHETIPI ===
{ctx["consensus"] or "non disponibili"}

{pool_block}
""".strip()
    )

    step("analysis")
    max_attempts = 1 + max(0, int(skill_cfg.get("max_retries", 1)))
    attempts = 0
    prompt = base_prompt
    improvement_out: Optional[AIDeckImprovementOutput] = None
    improved_entries = entries
    warnings: List[str] = []

    for attempt in range(max_attempts):
        attempts = attempt + 1
        candidate_out: AIDeckImprovementOutput = provider.generate_structured(
            model_id=skill_cfg["model_id"],
            system_instruction=sys_prompt,
            user_prompt=prompt,
            response_model=AIDeckImprovementOutput,
        )
        errors, improved_entries, warnings = _validate_and_apply_improvement_swaps(
            db, fmt, entries, candidate_out
        )
        improvement_out = candidate_out
        if not errors:
            break
        if attempt < max_attempts - 1:
            step("repair")
            prompt = (
                base_prompt
                + "\n\nCORREGGI QUESTI ERRORI DETERMINISTICI NEI CAMBI O NELLE CARTE PAPABILI:\n"
                + "\n".join(f"- {e}" for e in errors)
            )
        else:
            warnings.extend(errors)

    assert improvement_out is not None
    step("after_metrics")
    after_report = validate_deck_entries(fmt, improved_entries)
    warnings.extend(
        f"Lista migliorata: {i.message}" for i in after_report.issues if i.severity == "error"
    )
    after_analysis = deck_engine.analyze_list(db, improved_entries)
    after_structure = deck_engine.structure_summary(
        db, improved_entries, fmt, improvement_out.archetype or requested_arch
    )
    arena_txt, mtgo_txt = export_decklist_formats(improved_entries)

    def serialize_entries(ent_list: List[Tuple[Card, str, int]]) -> List[dict]:
        return [
            {
                "oracle_id": c.oracle_id,
                "card_name": c.name,
                "board": b,
                "quantity": q,
                "mana_cost": c.mana_cost,
                "cmc": c.cmc,
                "type_line": c.type_line,
                "image_uris": c.image_uris,
                "colors": c.colors,
            }
            for c, b, q in ent_list
        ]

    improved_colors = _deck_colors(improved_entries)
    source_colors = _deck_colors(entries)

    result_payload = {
        "improvement": improvement_out.model_dump(),
        "source_deck": {
            "id": deck_obj.id if deck_obj else None,
            "name": deck_title,
            "format_id": fmt,
            "archetype": requested_arch or improvement_out.archetype,
            "colors": source_colors,
            "cards": serialize_entries(entries),
        },
        "improved_deck_preview": {
            "name": improvement_out.deck_name or f"{deck_title} (Ottimizzato)",
            "format_id": fmt,
            "archetype": improvement_out.archetype or requested_arch or "midrange",
            "colors": improved_colors,
            "cards": serialize_entries(improved_entries),
            "exports": {"arena": arena_txt, "mtgo": mtgo_txt},
        },
        "comparison": {
            "before_analysis": before_analysis,
            "after_analysis": after_analysis,
            "before_structure": before_structure,
            "after_structure": after_structure,
        },
        "warnings": warnings,
    }

    step("save")
    duration_ms = int((time.time() - start_ts) * 1000)
    ai_run = AIRun(
        skill_name="deck_improvement",
        prompt_version=prompt_ver,
        model_id=skill_cfg["model_id"],
        provider=provider.provider_name,
        usage_json=dict(getattr(provider, "usage", None) or {}) or None,
        format_id=fmt,
        deck_id=deck_obj.id if deck_obj else None,
        validation_attempts=attempts,
        duration_ms=duration_ms,
        input_summary={
            "deck_name": deck_title,
            "deck_id": deck_obj.id if deck_obj else None,
            "format_id": fmt,
            "user_prompt": req.user_prompt,
        },
        output_json=result_payload,
    )
    db.add(ai_run)
    db.commit()

    return {
        **result_payload,
        "meta": {
            "run_id": ai_run.id,
            "skill": "deck_improvement",
            "prompt_version": prompt_ver,
            "model_id": skill_cfg["model_id"],
            "provider": provider.provider_name,
            "duration_ms": duration_ms,
        },
    }
