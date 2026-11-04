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
)
from app.services.ai_provider import get_active_ai_provider, get_skill_model_and_config
from app.services.deck_validator import (
    parse_decklist_text,
    validate_deck_entries,
)
from app.services.guide_quality import (
    validate_swaps,
    weighted_meta_estimate,
    evidence_context,
    require_fresh_catalog,
)
from app.skills.schemas import (
    AIDeckGuideRequest,
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


def _guide_context(db: Session, snapshot, entries) -> Dict[str, Any]:
    """Observed facts for every main matchup plus app-computed facts on our list."""
    analysis = deck_engine.analyze_list(db, entries)
    rulings = rulings_for(db, [c.oracle_id for c, _, _ in entries])
    ruling_lines = []
    for card, _, _ in entries:
        for r in (rulings.get(card.oracle_id) or [])[-RULINGS_PER_CARD:]:
            ruling_lines.append(f"- {card.name}: {r.get('comment')}")
    ruling_text = "\n".join(dict.fromkeys(ruling_lines))
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

            def at_least_one(draws):
                return 100 * (
                    1
                    - (
                        math.comb(total - qty, draws) / math.comb(total, draws)
                        if total - qty >= draws
                        else 0
                    )
                )

            probabilities = f" | P(almeno 1 copia): iniziali 7={at_least_one(7):.1f}%, viste 9={at_least_one(9):.1f}%, viste 10={at_least_one(10):.1f}%. Senza mulligan, cantrip o selezione; non è probabilità di lancio."
        line = f"{qty}x {c.name} ({c.mana_cost or 'Land'}) [{c.type_line}] — {oracle_text(c)}{probabilities}"
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
        except Exception:
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
        max_reviews=min(3, 1 + max(0, skill_cfg["max_retries"])),
        known_opponent_cards=ctx["known_cards"],
    )
    guide_out, open_issues = guide_out
    attempts = trace["attempts"]
    phase("weighted_estimate")
    guide = guide_out.model_dump()
    guide["meta_estimate"] = weighted_meta_estimate(guide, archs, latest_snap)
    guide["evidence"] = evidence_context(db, fmt, latest_snap)
    guide["deck_name"] = deck_title
    guide["format_id"] = fmt
    guide["model_id"] = skill_cfg["model_id"]
    guide["generated_at"] = utcnow().isoformat()
    guide["quality_review"] = {
        "status": "warnings" if open_issues else "passed",
        "open_issues": list(dict.fromkeys(open_issues)),
        "revision_count": attempts - 1,
        "checked_at": guide["generated_at"],
        "checks": [
            "Copie, mani tenute lanciabili e sidate",
            "Copertura dei matchup e carte avversarie osservate",
            "Revisione Oracle e ruling",
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
            if arch_b.sample_decklists:
                entries_b, _ = parse_decklist_text(
                    db, arch_b.sample_decklists[0].get("decklist_text", "")
                )
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
""".strip()

    step("analysis")
    matchup_out: AIMatchupSpotOutput = provider.generate_structured(
        model_id=skill_cfg["model_id"],
        system_instruction=sys_prompt,
        user_prompt=user_prompt,
        response_model=AIMatchupSpotOutput,
    )

    errors = validate_swaps(
        matchup_out.sideboard_plan_for_deck_a.model_dump(), entries_a
    )
    errors += validate_swaps(
        matchup_out.sideboard_plan_for_deck_b.model_dump(), entries_b
    )
    if errors:
        raise ValueError("Analisi non salvata: " + "; ".join(errors))
    step("save")
    duration_ms = int((time.time() - start_ts) * 1000)
    ai_run = AIRun(
        skill_name="matchup_spot",
        prompt_version=prompt_ver,
        model_id=skill_cfg["model_id"],
        provider=provider.provider_name,
        usage_json=dict(getattr(provider, "usage", None) or {}) or None,
        format_id=fmt,
        validation_attempts=1,
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
