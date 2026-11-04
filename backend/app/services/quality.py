"""Quality measurement: automatic metrics for decks and guides, run statistics,
human ratings and the user's real results.

Every number is computed from stored data; nothing here calls the AI. The report
answers one question: did a prompt or model change make results better?
"""

from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models import (
    AIJob,
    AIRun,
    Card,
    Deck,
    GuideVersion,
    MatchRecord,
    MetaArchetype,
    QualityRating,
)
from app.config import settings
from app.services import deck_engine
from app.services.guide_quality import (
    key,
    validate_guide,
    validate_meta_coverage,
    validate_opponent_cards,
)

INTERACTION_CORE = ("rimozioni", "counter", "sweeper", "scarto")
REFERENCE_ARCHETYPES = 5
MAIN_MATCHUPS = 4
MATCHUP_TEXT_FIELDS = (
    "role_pre_side",
    "role_post_side",
    "gameplan_pre_side",
    "gameplan_post_side",
    "on_the_play_notes",
    "on_the_draw_notes",
)


# ---------------------------------------------------------------------------
# Decks (M2)
# ---------------------------------------------------------------------------


def consensus_index(db: Session, snapshot) -> List[Tuple[MetaArchetype, deck_engine.Consensus]]:
    if not snapshot:
        return []
    out = []
    for arch in (
        db.query(MetaArchetype)
        .filter(MetaArchetype.snapshot_id == snapshot.id)
        .order_by(MetaArchetype.meta_share_pct.desc())
    ):
        con = deck_engine.consensus_list(db, arch)
        if con:
            out.append((arch, con))
    return out


def deck_metrics(db: Session, entries, index=()) -> dict:
    analysis = deck_engine.analyze_list(db, entries)
    main = Counter()
    for card, board, qty in entries:
        if board == "main":
            main[card.oracle_id] += qty
    nearest, overlap = None, 0.0
    for arch, con in index:
        stock = Counter({c.card.oracle_id: c.quantity for c in con.main})
        shared = sum(min(qty, stock[oid]) for oid, qty in main.items())
        pct = round(100 * shared / max(1, sum(stock.values())), 1)
        if pct > overlap:
            nearest, overlap = arch.name, pct
    deficits = [c for c in analysis["colors"] if c["deficit"]]
    return {
        "land_count": analysis["land_count"],
        "avg_mana_value": analysis["avg_mana_value_nonland"],
        "color_deficits": [f"{c['color']} -{c['deficit']}" for c in deficits],
        "total_deficit": sum(c["deficit"] for c in deficits),
        "always_tapped": analysis["tapped_lands"]["tapped"],
        "interaction_main": sum(
            analysis["interaction_main"].get(g, {}).get("copies", 0) for g in INTERACTION_CORE
        ),
        "nearest_archetype": nearest,
        "consensus_overlap_pct": overlap,
    }


def deck_entries(db: Session, deck: Deck):
    ids = [dc.oracle_id for dc in deck.cards]
    cards = {c.oracle_id: c for c in db.query(Card).filter(Card.oracle_id.in_(ids))}
    return [(cards[dc.oracle_id], dc.board, dc.quantity) for dc in deck.cards if dc.oracle_id in cards]


# ---------------------------------------------------------------------------
# Guides (M3)
# ---------------------------------------------------------------------------


def _words(text) -> int:
    return len(str(text or "").split())


def guide_metrics(guide: dict, entries, archetypes: Sequence[MetaArchetype], known_cards) -> dict:
    plans = guide.get("sideboard_guide") or []
    required = [a.name for a in archetypes]
    errors = (
        validate_guide(guide, entries)
        + validate_meta_coverage(guide, archetypes)
        + validate_opponent_cards(guide, known_cards, required)
    )
    by_name = {key(p.get("opponent_archetype", "")): p for p in plans}
    main_plans = [by_name[key(n)] for n in required[:MAIN_MATCHUPS] if key(n) in by_name]

    def plan_words(plan):
        words = sum(_words(plan.get(f)) for f in MATCHUP_TEXT_FIELDS)
        words += sum(
            _words(k.get("why_it_matters")) + _words(k.get("our_answer"))
            for k in plan.get("opponent_key_cards") or []
        )
        return words

    review = guide.get("quality_review") or {}
    return {
        "legacy_schema": "tier_assessment" not in guide,
        "matchups_required": len(required),
        "matchups_covered": sum(1 for n in required if key(n) in by_name),
        "avg_words_main_matchups": round(
            sum(plan_words(p) for p in main_plans) / len(main_plans), 0
        ) if main_plans else 0,
        "avg_opponent_cards": round(
            sum(len(p.get("opponent_key_cards") or []) for p in plans) / len(plans), 1
        ) if plans else 0,
        "play_draw_differentiated": sum(
            1
            for p in plans
            if not (p.get("on_the_play_uses_base") and p.get("on_the_draw_uses_base"))
        ),
        "validator_errors": len(errors),
        "open_issues": len(review.get("open_issues") or []),
        "review_status": review.get("status", "n/d"),
        "revision_count": review.get("revision_count"),
    }


def guide_entries(db: Session, version: GuideVersion):
    ids = [c.get("oracle_id") for c in version.deck_snapshot if c.get("oracle_id")]
    cards = {c.oracle_id: c for c in db.query(Card).filter(Card.oracle_id.in_(ids))}
    return [
        (cards[c["oracle_id"]], c["board"], c["quantity"])
        for c in version.deck_snapshot
        if c.get("oracle_id") in cards
    ]


# ---------------------------------------------------------------------------
# Runs, ratings and real results (M4-M6)
# ---------------------------------------------------------------------------


def model_pricing() -> Dict[str, dict]:
    """Optional per-model prices from config/ai-models.json (`pricing`); never guessed."""
    out = {}
    for m in settings.load_ai_models_config().get("models", []):
        price = m.get("pricing") or {}
        if price.get("inputPerMillion") is not None and price.get("outputPerMillion") is not None:
            out[m["id"]] = price
    return out


def run_cost(usage: Optional[dict], price: Optional[dict]) -> Optional[float]:
    if not usage or not price or not (usage.get("input") or usage.get("output")):
        return None
    # Thinking tokens are billed as output tokens.
    return (
        usage.get("input", 0) * price["inputPerMillion"]
        + (usage.get("output", 0) + usage.get("thought", 0)) * price["outputPerMillion"]
    ) / 1_000_000


def run_stats(db: Session, fmt: Optional[str] = None) -> List[dict]:
    """Per skill, prompt version and model: volume, failures, time and attempts."""
    groups: Dict[tuple, list] = defaultdict(list)
    q = db.query(AIRun)
    if fmt:
        q = q.filter(AIRun.format_id == fmt)
    for run in q:
        groups[(run.skill_name, run.prompt_version, run.model_id)].append(run)
    out = []
    prices = model_pricing()
    for (skill, version, model), runs in sorted(groups.items()):
        metered = [r.usage_json for r in runs if r.usage_json]
        costs = [c for c in (run_cost(u, prices.get(model)) for u in metered) if c is not None]
        failed = [
            r for r in runs
            if (r.output_json or {}).get("status") == "failed"
            or (r.input_summary or {}).get("status") == "failed"
        ]
        ok = [r for r in runs if r not in failed]
        warned = [
            r for r in ok
            if (r.output_json or {}).get("warnings")
            or ((r.output_json or {}).get("quality_review") or {}).get("status") == "warnings"
        ]
        out.append(
            {
                "skill": skill,
                "prompt_version": version,
                "model_id": model,
                "runs": len(runs),
                "failed": len(failed),
                "with_warnings": len(warned),
                "avg_duration_s": round(sum(r.duration_ms or 0 for r in runs) / len(runs) / 1000, 1),
                "avg_attempts": round(sum(r.validation_attempts or 1 for r in runs) / len(runs), 1),
                "metered_runs": len(metered),
                "avg_input_tokens": round(sum(u.get("input", 0) for u in metered) / len(metered)) if metered else None,
                "avg_output_tokens": round(
                    sum(u.get("output", 0) + u.get("thought", 0) for u in metered) / len(metered)
                ) if metered else None,
                "avg_cost": round(sum(costs) / len(costs), 4) if costs else None,
                "currency": (prices.get(model) or {}).get("currency"),
                "last_run": max(r.created_at for r in runs).isoformat() if runs else None,
            }
        )
    return out


def job_stats(db: Session, fmt: Optional[str] = None) -> List[dict]:
    counts: Dict[str, Counter] = defaultdict(Counter)
    q = db.query(AIJob)
    if fmt:
        q = q.filter(AIJob.format_id == fmt)
    for job in q:
        counts[job.kind][job.status] += 1
    return [{"kind": k, **dict(v)} for k, v in sorted(counts.items())]


def ratings_for(db: Session, kind: str, ids: Sequence[int]) -> Dict[int, dict]:
    rows = defaultdict(list)
    if ids:
        for r in db.query(QualityRating).filter(
            QualityRating.target_kind == kind, QualityRating.target_id.in_(list(ids))
        ):
            rows[r.target_id].append(r)
    return {
        tid: {
            "count": len(rs),
            "depth": round(sum(r.depth for r in rs) / len(rs), 1),
            "correctness": round(sum(r.correctness for r in rs) / len(rs), 1),
            "usefulness": round(sum(r.usefulness for r in rs) / len(rs), 1),
        }
        for tid, rs in rows.items()
    }


def record_summary(db: Session, deck_id: int) -> List[dict]:
    """Real results by opponent archetype: matches and games."""
    agg: Dict[str, Counter] = defaultdict(Counter)
    for r in db.query(MatchRecord).filter(MatchRecord.deck_id == deck_id):
        a = agg[r.opponent_archetype]
        a["games_won"] += r.games_won
        a["games_lost"] += r.games_lost
        if r.games_won > r.games_lost:
            a["matches_won"] += 1
        elif r.games_won < r.games_lost:
            a["matches_lost"] += 1
        else:
            a["matches_drawn"] += 1
    return [
        {"opponent_archetype": name, **{k: c[k] for k in (
            "matches_won", "matches_lost", "matches_drawn", "games_won", "games_lost"
        )}}
        for name, c in sorted(agg.items(), key=lambda kv: -sum(kv[1].values()))
    ]


def records_text(db: Session, deck_id: Optional[int]) -> str:
    if not deck_id:
        return ""
    rows = record_summary(db, deck_id)
    if not rows:
        return ""
    lines = [
        f"- contro {r['opponent_archetype']}: match {r['matches_won']}-{r['matches_lost']}"
        + (f"-{r['matches_drawn']}" if r["matches_drawn"] else "")
        + f", game {r['games_won']}-{r['games_lost']}"
        for r in rows
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def report(db: Session, fmt: str) -> dict:
    snapshot = deck_engine.latest_snapshot(db, fmt)
    index = consensus_index(db, snapshot)
    field = deck_engine.field_model(db, snapshot, 8) if snapshot else []
    archetypes = [f.archetype for f in field]
    known = {key(a.name): {key(u.card_name) for u in a.cards} for a in archetypes}

    reference = [
        {
            "name": arch.name,
            "meta_share_pct": arch.meta_share_pct,
            "lists_count": con.lists_count,
            **deck_metrics(db, con.entries(), [(arch, con)]),
        }
        for arch, con in index[:REFERENCE_ARCHETYPES]
    ]

    generated = []
    decks = (
        db.query(Deck)
        .filter(Deck.format_id == fmt, Deck.source == "ai_generated")
        .order_by(Deck.id.desc())
        .limit(20)
        .all()
    )
    deck_ratings = ratings_for(db, "deck", [d.id for d in decks])
    for deck in decks:
        entries = deck_entries(db, deck)
        if not entries:
            continue
        run = (
            db.query(AIRun)
            .filter(AIRun.skill_name == "deck_generation", AIRun.deck_id == deck.id)
            .order_by(AIRun.id.desc())
            .first()
        )
        out = (run.output_json or {}) if run else {}
        warnings = out.get("warnings") or []
        generated.append(
            {
                "deck_id": deck.id,
                "name": deck.name,
                "model_id": run.model_id if run else None,
                "prompt_version": run.prompt_version if run else None,
                "mode": (out.get("starting_point") or {}).get("mode", "n/d"),
                "unmotivated_deltas": sum("non motivata" in w for w in warnings),
                "open_warnings": len(warnings),
                "critic_verdict": (out.get("critic") or {}).get("verdict"),
                "revision_applied": (out.get("revision") or {}).get("applied"),
                "rating": deck_ratings.get(deck.id),
                **deck_metrics(db, entries, index),
            }
        )

    guides = []
    versions = (
        db.query(GuideVersion)
        .filter(GuideVersion.format_id == fmt)
        .order_by(GuideVersion.id.desc())
        .limit(20)
        .all()
    )
    guide_ratings = ratings_for(db, "guide", [v.id for v in versions])
    for version in versions:
        guides.append(
            {
                "guide_id": version.id,
                "deck_name": version.deck_name,
                "model_id": version.model_id,
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "rating": guide_ratings.get(version.id),
                **guide_metrics(version.guide_json or {}, guide_entries(db, version), archetypes, known),
            }
        )

    return {
        "format_id": fmt,
        "snapshot": {
            "id": snapshot.id if snapshot else None,
            "period": snapshot.period_label if snapshot else None,
        },
        "reference": reference,
        "generated_decks": generated,
        "guides": guides,
        "runs": run_stats(db, fmt),
        "jobs": job_stats(db, fmt),
    }
