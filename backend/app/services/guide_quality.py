"""Deterministic checks and transparent estimates; never fabricate empirical samples."""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import re
from app.models import MetaSnapshot, SyncLog

# Above and below these Bo3 estimates a matchup stops being even.
FAVORABLE_WR = 55.0
UNFAVORABLE_WR = 45.0
# Fields that are data about the guide, not text written by the model.
_NOT_PROSE = {
    "meta_estimate",
    "legality",
    "quality_review",
    "decklist",
    "deck_name",
    "format_id",
    "model_id",
    "generated_at",
    "rules_warnings",
    "evidence",
}


def key(name):
    return re.sub(r"\s+", " ", name.split(" // ")[0].strip().casefold())


def _swap_counter(items):
    return Counter({key(i["card_name"]): i["quantity"] for i in items or []})


def normalize_guide(guide, entries):
    """Fix what is mechanically decidable, so that it never costs a review round:
    copies come from the list, a side plan equal to the base plan is the base plan and
    the difficulty label follows the estimate."""
    fixed = deepcopy(guide)
    totals = Counter()
    for card, _, qty in entries:
        totals[key(card.name)] += qty
    for role in fixed.get("card_roles", []):
        if totals[key(role["card_name"])]:
            role["quantity"] = totals[key(role["card_name"])]
    for plan in fixed.get("sideboard_guide", []):
        base_in, base_out = plan.get("cards_in"), plan.get("cards_out")
        for side in ("play", "draw"):
            inf, outf, flag = f"on_the_{side}_in", f"on_the_{side}_out", f"on_the_{side}_uses_base"
            distinct = bool(plan.get(inf) or plan.get(outf))
            same = (
                distinct
                and _swap_counter(plan.get(inf)) == _swap_counter(base_in)
                and _swap_counter(plan.get(outf)) == _swap_counter(base_out)
            )
            if same:
                plan[inf], plan[outf] = [], []
            if base_in or base_out:
                plan[flag] = same or not distinct
        wr = plan.get("expected_winrate_pct")
        if isinstance(wr, (int, float)):
            plan["matchup_difficulty"] = (
                "Favorevole"
                if wr >= FAVORABLE_WR
                else "Sfavorevole"
                if wr <= UNFAVORABLE_WR
                else "Equilibrato"
            )
    return fixed


def _text_fields(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _text_fields(item, f"{path}/{i}")
    elif isinstance(node, dict):
        for name, item in node.items():
            yield from _text_fields(item, f"{path}/{name}")


# "le 10 terre con sottotipo Island o Swamp (6 Island, 1 Swamp, 4 Watery Grave)"
STATED_SUM = re.compile(
    r"\b(\d+)\b[^\d().;:]{1,80}\(((?:\s*\d+\s+[A-Z][^()]*?)(?:,\s*\d+\s+[A-Z][^()]*?)+)\)"
)
SUM_TERM = re.compile(r"(?:^|,)\s*(\d+)\s+[A-Z]")
STATS = r"\s*\(?\s*(-?\d+)/(-?\d+)\b"


def _card_stats(entries):
    """Exact power/toughness of every face in the list, by face name."""
    stats = {}
    for card, _, _ in entries:
        faces = card.card_faces or [
            {"name": card.name, "power": card.power, "toughness": card.toughness}
        ]
        for face in faces:
            if face.get("power") is not None and face.get("toughness") is not None:
                stats[face.get("name") or card.name] = f"{face['power']}/{face['toughness']}"
    return stats


def validate_stated_facts(guide, entries):
    """Facts written in the prose that the app can check on its own: sums of copies and
    the power/toughness of our cards. The reviewer can always rewrite a false positive."""
    errors = []
    stats = _card_stats(entries)
    patterns = {name: re.compile(r"(?<![\w'])" + re.escape(name) + STATS) for name in stats}
    prose = {k: v for k, v in guide.items() if k not in _NOT_PROSE}
    for path, text in _text_fields(prose):
        for match in STATED_SUM.finditer(text):
            stated = int(match.group(1))
            total = sum(int(n) for n in SUM_TERM.findall(match.group(2)))
            if total != stated:
                errors.append(
                    f"Conteggio errato ({path}): '{match.group(0).strip()}' dichiara {stated}, "
                    f"ma la somma tra parentesi fa {total}. Correggi tutte le occorrenze nella guida."
                )
        for name, pattern in patterns.items():
            for match in pattern.finditer(text):
                written = f"{match.group(1)}/{match.group(2)}"
                if written != stats[name]:
                    errors.append(
                        f"Forza/costituzione errata ({path}): {name} è scritta {written}, "
                        f"ma per l'Oracle è {stats[name]}. Correggi tutte le occorrenze nella guida."
                    )
    return list(dict.fromkeys(errors))


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


def validate_guide(guide, entries):
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
    errors.extend(mulligan_castability_errors(guide, entries))
    errors.extend(kept_hand_land_errors(guide, entries))
    errors.extend(validate_stated_facts(guide, entries))
    return errors


def kept_hand_land_errors(guide, entries):
    """A one-lander is not a keep in constructed, whatever the cantrip count."""
    from app.services.deck_engine import land_face

    by_key = {key(c.name): c for c, board, _ in entries if board == "main"}
    errors = []
    for i, ex in enumerate(guide.get("mulligan_examples", [])):
        if not str(ex.get("verdict", "")).strip().upper().startswith("KEEP"):
            continue
        cards = [by_key.get(key(n)) for n in ex.get("hand_cards", [])]
        if len(cards) != 7 or any(c is None for c in cards):
            continue  # reported by the availability check
        if sum(1 for c in cards if land_face(c)) == 1:
            errors.append(
                f"Mano tenuta con una sola terra (/mulligan_examples/{i}): "
                f"{', '.join(ex.get('hand_cards', []))}. Cambia il verdetto in MULLIGAN o la mano."
            )
    return errors


def mulligan_castability_errors(guide, entries):
    """A kept hand needs lands and at least one spell its lands can pay for.

    Generic replacement for card-specific rule patches: it catches hands such as
    "only black lands with red spells" for any deck.
    """
    from app.services.deck_engine import WUBRG, fetch_colors, is_land_card, land_face
    from app.services.deck_validator import castable_with_colors

    by_key = {key(c.name): c for c, board, _ in entries if board == "main"}
    deck_lands = [(c, land_face(c)) for c in by_key.values() if land_face(c)]
    errors = []
    for ex in guide.get("mulligan_examples", []):
        if not str(ex.get("verdict", "")).strip().upper().startswith("KEEP"):
            continue
        cards = [by_key.get(key(n)) for n in ex.get("hand_cards", [])]
        if any(c is None for c in cards):
            continue  # reported by the availability check
        label = ", ".join(ex.get("hand_cards", []))
        lands = [c for c in cards if land_face(c)]
        spells = [c for c in cards if not is_land_card(c)]
        if not lands:
            errors.append(f"Mano tenuta senza terre ({label}): rivedi il verdetto o la mano.")
            continue
        if not spells:
            errors.append(f"Mano tenuta senza magie ({label}): rivedi il verdetto o la mano.")
            continue
        colors = set()
        for card in lands:
            colors |= {c for c in card.produced_mana or [] if c in WUBRG}
            colors |= fetch_colors(land_face(card).get("oracle_text") or "", deck_lands)
        if not any(castable_with_colors(s, colors) for s in spells):
            errors.append(
                f"Mano tenuta in cui le terre ({''.join(sorted(colors)) or 'incolori'}) non lanciano nessuna magia ({label}): "
                "rivedi il verdetto o la mano."
            )
    return errors


def validate_opponent_cards(guide, known_cards, required_names):
    """Each main matchup names >= 2 opponent cards that really appear in that archetype's lists."""
    errors = []
    required = {key(n) for n in required_names}
    for i, plan in enumerate(guide.get("sideboard_guide", [])):
        name = key(plan.get("opponent_archetype", ""))
        cited = plan.get("opponent_key_cards") or []
        if name in required and len(cited) < 2:
            errors.append(
                f"{plan['opponent_archetype']}: servono almeno 2 carte avversarie chiave con la nostra risposta (/sideboard_guide/{i}/opponent_key_cards)."
            )
        known = known_cards.get(name)
        if not known:
            continue
        for j, item in enumerate(cited):
            if key(item.get("card_name", "")) not in known:
                errors.append(
                    f"{plan['opponent_archetype']}: '{item.get('card_name')}' non compare nelle liste osservate dell'archetipo "
                    f"(/sideboard_guide/{i}/opponent_key_cards/{j}/card_name). Cita una carta del profilo fornito."
                )
        for card in plan.get("expected_opponent_sideboard") or []:
            if key(card) not in known:
                errors.append(
                    f"{plan['opponent_archetype']}: '{card}' non compare nelle liste osservate dell'archetipo "
                    f"(/sideboard_guide/{i}/expected_opponent_sideboard)."
                )
    return errors


# Archived guides are re-checked with the same generic rules when they are read.
archived_guide_warnings = mulligan_castability_errors


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
        "note": reason
        or f"Stima del modello sul {round(covered, 1):g}% del meta coperto, non risultati di partite.",
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


def _latest_catalog_sync(db):
    return (
        db.query(SyncLog)
        .filter_by(source="scryfall", status="completed")
        .order_by(SyncLog.completed_at.desc())
        .first()
    )


def legality_report(db, fmt, entries, missing=()):
    """The app's own legality check of a list, against the catalog it holds right now."""
    from app.services.deck_validator import validate_deck_entries

    report = validate_deck_entries(fmt, entries)
    issues = [i.message for i in report.issues if i.severity == "error"]
    issues += [f"{name}: carta non più presente nel catalogo." for name in missing]
    sync = _latest_catalog_sync(db)
    return {
        "status": "not_legal" if issues else "legal",
        "format_id": fmt,
        "issues": issues,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "catalog_synced_at": sync.completed_at.isoformat() if sync and sync.completed_at else None,
    }


def evidence_context(db, fmt, snapshot=None):
    if snapshot is None:
        snapshot = (
            db.query(MetaSnapshot)
            .filter_by(format_id=fmt)
            .order_by(MetaSnapshot.fetched_at.desc())
            .first()
        )
    sync = _latest_catalog_sync(db)
    return (
        f"Data analisi UTC: {datetime.now(timezone.utc).isoformat()}. Formato: {fmt}. "
        f"Catalogo Scryfall e banlist aggiornati al: {sync.completed_at.isoformat() if sync and sync.completed_at else 'non documentato'}. "
        f"Snapshot meta: {snapshot.id if snapshot else 'assente'}; fonte: {snapshot.source if snapshot else 'assente'}; "
        f"rilevazione: {snapshot.fetched_at.isoformat() if snapshot else 'non disponibile'}. "
        "La legalità delle liste è verificata automaticamente dall'app: non scrivere avvertenze in proposito. "
        "Le stime strategiche non sono risultati di partite.\n"
    )


def require_fresh_catalog(db):
    sync = _latest_catalog_sync(db)
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
