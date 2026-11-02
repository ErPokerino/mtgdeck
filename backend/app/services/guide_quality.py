"""Deterministic checks and transparent estimates; never fabricate empirical samples."""

from collections import Counter
from datetime import datetime, timezone
import re
from app.models import MetaSnapshot, SyncLog


def key(name):
    return re.sub(r"\s+", " ", name.split(" // ")[0].strip().casefold())


def validate_swaps(plan, entries, in_field="cards_in", out_field="cards_out"):
    errors = []
    for field, board in ((in_field, "side"), (out_field, "main")):
        available = Counter()
        for card, b, quantity in entries:
            if b == board:
                available[key(card.name)] += quantity
        requested = Counter()
        for item in plan.get(field, []):
            requested[key(item["card_name"])] += item["quantity"]
        for name, qty in requested.items():
            if qty <= 0 or qty > available[name]:
                errors.append(
                    f"{field}: {name} ({qty}) supera le copie disponibili ({available[name]})."
                )
    if sum(i["quantity"] for i in plan.get(in_field, [])) != sum(
        i["quantity"] for i in plan.get(out_field, [])
    ):
        errors.append(
            f"{in_field}/{out_field}: IN ({sum(i['quantity'] for i in plan.get(in_field, []))}) "
            f"e OUT ({sum(i['quantity'] for i in plan.get(out_field, []))}) non bilanciati."
        )
    return errors


def validate_guide(guide, entries, include_rules=True):
    errors = []
    main = Counter()
    for card, board, qty in entries:
        if board == "main":
            main[key(card.name)] += qty
    quantities = Counter()
    for card, _, qty in entries:
        quantities[key(card.name)] += qty
    for role in guide.get("card_roles", []):
        if role["quantity"] != quantities[key(role["card_name"])]:
            errors.append(
                f"Card breakdown: {role['card_name']}: ricevute {role['quantity']} copie, "
                f"attese {quantities[key(role['card_name'])]} copie complessive tra main e side. "
                "Usa un’unica voce con il nome esatto e il totale fornito dalla lista."
            )
    for ex in guide.get("mulligan_examples", []):
        hand = Counter(key(n) for n in ex["hand_cards"])
        if sum(hand.values()) != 7 or any(qty > main[n] for n, qty in hand.items()):
            errors.append(
                "Esempio mulligan: la mano deve contenere 7 carte realmente disponibili nel mainboard."
            )
    for plan in guide.get("sideboard_guide", []):
        for side in ("play", "draw"):
            if (
                (plan.get("cards_in") or plan.get("cards_out"))
                and not plan.get(f"on_the_{side}_uses_base")
                and not (
                    plan.get(f"on_the_{side}_in") or plan.get(f"on_the_{side}_out")
                )
            ):
                errors.append(
                    f"{plan['opponent_archetype']}: manca la sidata {side}. Se identica al piano base usa on_the_{side}_uses_base=true, altrimenti fornisci gli array completi."
                )
            if plan.get(f"on_the_{side}_uses_base") and (
                plan.get(f"on_the_{side}_in") or plan.get(f"on_the_{side}_out")
            ):
                errors.append(
                    f"{plan['opponent_archetype']}: {side} usa il piano base ma contiene anche una sidata distinta. Scegli una rappresentazione univoca."
                )
        for inf, outf in (
            ("cards_in", "cards_out"),
            ("on_the_play_in", "on_the_play_out"),
            ("on_the_draw_in", "on_the_draw_out"),
        ):
            errors.extend(
                f"{plan['opponent_archetype']}: {e}"
                for e in validate_swaps(plan, entries, inf, outf)
            )
    if include_rules:
        errors.extend(reflection_copy_errors(guide, entries))
    return errors


def reflection_copy_errors(guide, entries):
    """Flag a specific, high-impact Oracle contradiction in new and archived guides."""
    if not any("reflection of kiki-jiki" in c.name.casefold() for c, _, _ in entries):
        return []
    legends = []
    for card, _, _ in entries:
        if (
            "legendary" in (card.type_line or "").casefold()
            and "creature" in (card.type_line or "").casefold()
        ):
            front = card.name.split(" // ")[0]
            legends.append((front, front.split(",")[0].strip().casefold()))
    errors = []
    sections = [
        (str(role.get("card_name", "")), role.get("explanation", ""))
        for role in guide.get("card_roles", [])
    ]
    sections += [
        (" ".join(syn.get("cards_involved", [])), syn.get("description", ""))
        for syn in guide.get("synergies", [])
    ]
    sections += [
        ("", str(guide.get(field, "")))
        for field in (
            "executive_summary",
            "early_game_plan",
            "mid_game_plan",
            "late_game_plan",
        )
    ]
    for context, text in sections:
        for sentence in re.split(r"[.;\n]", str(text)):
            lower = sentence.casefold()
            verb = re.search(r"copi(?:a|e|i|o|are|ando)|duplic(?:a|are|azione)", lower)
            if not verb:
                continue
            if re.search(
                r"(?:non|cannot|can't|impossibile|evita)\s+(?:pu[oò]\s+|di\s+)?(?:essere\s+)?(?:copi|duplic)",
                lower,
            ):
                continue
            if not any(
                k in (context + " " + sentence).casefold()
                for k in ("reflection", "kiki-jiki", "fable")
            ):
                continue
            for full, short in legends:
                if len(short) >= 4 and short in lower[verb.end() :]:
                    errors.append(
                        f"Reflection of Kiki-Jiki non può bersagliare {full}: è una creatura leggendaria. Rivedi: {sentence.strip()}"
                    )
    return list(dict.fromkeys(errors))


def weighted_meta_estimate(guide, archetypes, snapshot=None):
    # Exact normalized names only: ambiguous/fuzzy matching can double-count opponents.
    plans = {}
    for plan in guide.get("sideboard_guide", []):
        name = key(plan["opponent_archetype"])
        if name in plans:
            raise ValueError(
                "Matchup duplicato nella guida: " + plan["opponent_archetype"]
            )
        wr = float(plan["expected_winrate_pct"])
        if not 0 <= wr <= 100:
            raise ValueError("Winrate fuori intervallo")
        plans[name] = wr
    rows, missing = [], []
    for arch in archetypes:
        share = max(0, float(arch.meta_share_pct))
        if key(arch.name) in plans and share:
            rows.append(
                {
                    "archetype": arch.name,
                    "share_pct": share,
                    "winrate_pct": plans[key(arch.name)],
                }
            )
        elif share:
            missing.append(arch.name)
    covered = sum(r["share_pct"] for r in rows)
    total = sum(max(0, float(a.meta_share_pct)) for a in archetypes)
    # Do not silently normalize inconsistent scraped percentages into an entire metagame.
    valid_shares = 0 < total <= 100.5 and covered <= 100.5
    weighted = (
        round(sum(r["share_pct"] * r["winrate_pct"] for r in rows) / covered, 2)
        if covered and valid_shares
        else None
    )
    status = (
        "no_meta"
        if not total
        else "invalid_shares"
        if not valid_shares
        else "no_matchups"
        if not covered
        else "available"
    )
    reason = {
        "no_meta": "Nessuno snapshot con quote del metagame disponibile per questo formato. Aggiorna il metagame prima dell’analisi.",
        "invalid_shares": "Quote della fonte incoerenti: calcolo non disponibile.",
        "no_matchups": "Nessun matchup della guida corrisponde agli archetipi dello snapshot.",
        "available": "",
    }[status]
    return {
        "status": status,
        "reason": reason,
        "weighted_winrate_pct": weighted,
        "coverage_pct": round(covered, 2),
        "snapshot_share_pct": round(total, 2),
        "rows": rows,
        "missing_archetypes": missing,
        "uncovered_share_pct": round(max(0, 100 - covered), 2),
        "snapshot_id": snapshot.id if snapshot else None,
        "source": snapshot.source if snapshot else None,
        "fetched_at": snapshot.fetched_at.isoformat() if snapshot else None,
        "formula": "Somma(quota meta × WR teorico Bo3) / somma(quote coperte)",
        "note": "Stima teorica AI, non risultati di partite. Valida solo sul meta coperto; il resto resta ignoto. "
        + reason,
    }


def validate_meta_coverage(guide, required_archetypes):
    """The model must supply one justified Bo3 estimate per requested opponent."""
    plans = guide.get("sideboard_guide", [])
    names = Counter(key(p["opponent_archetype"]) for p in plans)
    errors = [
        f"Matchup duplicato: {name}." for name, count in names.items() if count > 1
    ]
    for arch in required_archetypes:
        if not names[key(arch.name)]:
            errors.append(
                f"Manca il matchup obbligatorio '{arch.name}': usa esattamente questo nome e includi WR teorico Bo3 e motivazione."
            )
    for plan in plans:
        if not plan.get("estimate_rationale", "").strip():
            errors.append(
                f"{plan['opponent_archetype']}: manca la motivazione della stima Bo3."
            )
    return errors


def evidence_context(db, fmt, snapshot=None):
    if snapshot is None:
        snapshot = (
            db.query(MetaSnapshot)
            .filter_by(format_id=fmt)
            .order_by(MetaSnapshot.fetched_at.desc())
            .first()
        )
    sync = (
        db.query(SyncLog)
        .filter_by(source="scryfall", status="completed")
        .order_by(SyncLog.completed_at.desc())
        .first()
    )
    return (
        f"Data analisi UTC: {datetime.now(timezone.utc).isoformat()}. Formato: {fmt}. "
        f"Ultima sync legalità Scryfall: {sync.completed_at.isoformat() if sync and sync.completed_at else 'non documentata'}. "
        f"Snapshot meta: {snapshot.id if snapshot else 'assente'}; fonte: {snapshot.source if snapshot else 'assente'}; "
        f"rilevazione: {snapshot.fetched_at.isoformat() if snapshot else 'non disponibile'}. "
        "Le legalità sono una fotografia locale, non una verifica live. Le stime strategiche non sono risultati di partite.\n"
    )


def require_fresh_catalog(db):
    sync = (
        db.query(SyncLog)
        .filter_by(source="scryfall", status="completed")
        .order_by(SyncLog.completed_at.desc())
        .first()
    )
    if not sync or not sync.completed_at:
        raise ValueError(
            "Sincronizza Scryfall prima di usare l’analisi competitiva: legalità non documentata."
        )
    stamp = (
        sync.completed_at.replace(tzinfo=timezone.utc)
        if sync.completed_at.tzinfo is None
        else sync.completed_at
    )
    if (datetime.now(timezone.utc) - stamp).total_seconds() > 48 * 3600:
        raise ValueError(
            "Legalità e banlist risalgono a oltre 48 ore fa. Sincronizza Scryfall prima di generare nuove analisi."
        )
