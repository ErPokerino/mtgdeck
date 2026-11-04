"""Metagame sync from MTGTop8: archetype shares, tournament lists and observed card usage.

Only plainly served pages are read, with an identifying User-Agent and a delay between
requests. Every number stored is observed in the source or computed from collected
lists; nothing is filled with plausible defaults.
"""

import asyncio
import logging
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Card,
    MetaArchetype,
    MetaArchetypeCard,
    MetaCardStat,
    MetaSnapshot,
    SyncLog,
    TournamentDecklist,
    utcnow,
)
from app.services.deck_validator import (
    export_decklist_formats,
    get_color_combination_label,
    parse_decklist_text,
)

log = logging.getLogger("uvicorn.error")

SOURCE = "mtgtop8"
BASE_URL = "https://www.mtgtop8.com"
FORMAT_CODES = {"standard": "ST", "pioneer": "PI", "modern": "MO"}
PERIOD_LABEL = "Last 2 Months"


class MetaSyncState:
    def __init__(self) -> None:
        self.status: str = "idle"
        self.message: str = "Pronto"


meta_state = MetaSyncState()


# --------------------------------------------------------------------------- parsing


@dataclass
class SourceArchetype:
    name: str
    source_archetype_id: str
    share_pct: float
    category: str


@dataclass
class SourceDeckRow:
    deck_id: str
    title: str
    pilot: str
    event: str
    placement: str
    played_on: Optional[str]


def parse_period_links(html: str) -> Dict[str, str]:
    """Metagame periods offered by the format page: label -> meta id."""
    soup = BeautifulSoup(html, "lxml")
    periods = {}
    for a in soup.select("#metas_list a[href*='meta=']"):
        m = re.search(r"meta=(\d+)", a.get("href", ""))
        label = a.get_text(" ", strip=True)
        if m and label:
            periods.setdefault(label, m.group(1))
    return periods


def parse_format_breakdown(html: str) -> Tuple[int, List[SourceArchetype]]:
    """Archetypes with their share of the period, grouped under AGGRO/CONTROL/COMBO headers."""
    soup = BeautifulSoup(html, "lxml")
    total = 0
    for div in soup.select("div.S14"):
        m = re.fullmatch(r"(\d+)\s+decks", div.get_text(" ", strip=True), re.I)
        if m:
            total = int(m.group(1))
            break
    archetypes: List[SourceArchetype] = []
    category = "other"
    for node in soup.select("div.meta_arch, div.hover_tr"):
        if "meta_arch" in (node.get("class") or []):
            category = node.get_text(" ", strip=True).split()[0].lower()
            continue
        link = node.select_one("a[href*='archetype?a=']")
        if not link:
            continue
        arch_id = re.search(r"a=(\d+)", link["href"])
        shares = [
            re.fullmatch(r"([\d.]+)\s*%", d.get_text(" ", strip=True))
            for d in node.select("div.S14")
        ]
        share = next((float(s.group(1)) for s in shares if s), None)
        if arch_id and share is not None:
            archetypes.append(
                SourceArchetype(
                    name=link.get_text(" ", strip=True),
                    source_archetype_id=arch_id.group(1),
                    share_pct=share,
                    category=category,
                )
            )
    return total, archetypes


def _iso_date(raw: str) -> Optional[str]:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{2})", raw.strip())
    if not m:
        return None
    day, month, year = (int(x) for x in m.groups())
    try:
        return date(2000 + year, month, day).isoformat()
    except ValueError:
        return None


def parse_archetype_decks(html: str) -> List[SourceDeckRow]:
    """Deck rows of an archetype page, newest first as served."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("tr.hover_tr"):
        link = tr.select_one("a[href*='d=']")
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        deck_id = re.search(r"[?&]d=(\d+)", link.get("href", "")) if link else None
        if not deck_id or len(tds) < 7:
            continue
        rows.append(
            SourceDeckRow(
                deck_id=deck_id.group(1),
                title=tds[1],
                pilot=tds[2],
                event=tds[3],
                placement=tds[5],
                played_on=_iso_date(tds[6]),
            )
        )
    return rows


# --------------------------------------------------------------------------- statistics


@dataclass
class CardUsage:
    oracle_id: str
    card_name: str
    main_lists: int = 0
    main_copies: int = 0
    side_lists: int = 0
    side_copies: int = 0
    any_lists: int = 0


@dataclass
class ArchetypeStats:
    lists: int
    cards: Dict[str, CardUsage] = field(default_factory=dict)

    def main_inclusion(self, oid: str) -> float:
        u = self.cards.get(oid)
        return 100.0 * u.main_lists / self.lists if u and self.lists else 0.0


def archetype_card_stats(decklists: Iterable[List[Dict[str, Any]]]) -> ArchetypeStats:
    """Inclusion rate and average copies (over the lists that play the card) per board."""
    stats = ArchetypeStats(lists=0)
    for cards in decklists:
        stats.lists += 1
        boards: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        names = {}
        for c in cards:
            board = "main" if c["board"] == "main" else "side"
            boards[c["oracle_id"]][board] += c["quantity"]
            names[c["oracle_id"]] = c["card_name"]
        for oid, qty in boards.items():
            u = stats.cards.setdefault(oid, CardUsage(oid, names[oid]))
            u.any_lists += 1
            if qty.get("main"):
                u.main_lists += 1
                u.main_copies += qty["main"]
            if qty.get("side"):
                u.side_lists += 1
                u.side_copies += qty["side"]
    return stats


def archetype_colors(stats: ArchetypeStats, cards_by_oid: Dict[str, Any]) -> List[str]:
    """Colours the archetype must pay for, from the main-deck spells in at least 25% of lists.

    Card colours overstate hybrid cards (Leyline of the Guildpact is all five colours), so
    only mana symbols count: single-colour symbols always, a hybrid symbol only when none
    of its colours is already required. {2/W} and Phyrexian symbols never require a colour.
    """
    required: set = set()
    hybrids: List[List[str]] = []
    for oid in stats.cards:
        card = cards_by_oid.get(oid)
        if not card or stats.main_inclusion(oid) < 25:
            continue
        if "Land" in (card.type_line or "").split("//")[0]:
            continue
        costs = [f.get("mana_cost") or "" for f in card.card_faces or []] or [
            card.mana_cost or ""
        ]
        for symbol in re.findall(r"\{([^}]+)\}", " ".join(costs)):
            parts = symbol.split("/")
            if "P" in parts or any(p.isdigit() for p in parts):
                continue
            colored = [p for p in parts if p in "WUBRG"]
            if len(colored) == 1:
                required.add(colored[0])
            elif colored:
                hybrids.append(colored)
    for options in hybrids:
        if not required.intersection(options):
            required.add(options[0])
    return sorted(required)


def decklist_label(archetype: str, title: Optional[str], pilot: Optional[str]) -> str:
    """'Archetype · pilot', or the deck title when it says more than the archetype."""
    if title and title.casefold() != archetype.casefold():
        return f"{archetype} ({title})"
    return f"{archetype} · {pilot}" if pilot else archetype


def _avg(copies: int, lists: int) -> float:
    return round(copies / lists, 2) if lists else 0.0


def _tier(share_pct: float) -> int:
    # MTGTop8 has no tiers: the app's convention by share of the period.
    return 1 if share_pct >= 5 else 2 if share_pct >= 2 else 3


# --------------------------------------------------------------------------- fetching


class PoliteClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": settings.meta_user_agent},
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
        )
        self._last = 0.0
        self.requests = 0

    def get(self, path: str, **params: str) -> str:
        wait = settings.meta_request_delay_ms / 1000 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        response = self._client.get(f"{BASE_URL}{path}", params=params)
        response.raise_for_status()
        return response.text

    def close(self) -> None:
        self._client.close()


def _usable(deck: TournamentDecklist, cards_by_oid: Dict[str, Card], fmt: str) -> bool:
    """Complete when fetched and still legal today (bans can invalidate cached lists)."""
    if not deck.is_complete:
        return False
    return all(
        (card := cards_by_oid.get(c["oracle_id"])) is not None
        and getattr(card, f"legality_{fmt}", "not_legal") == "legal"
        for c in deck.cards or []
    )


def _store_decklist(
    db: Session, fmt: str, arch: SourceArchetype, row: SourceDeckRow, text: str
) -> TournamentDecklist:
    entries, unresolved = parse_decklist_text(db, text)
    issues = [f"Carta non riconosciuta: {n}" for n in unresolved]
    main = sum(q for _, b, q in entries if b == "main")
    if main < 60:
        issues.append(f"Mainboard di {main} carte")
    illegal = [c.name for c, _, _ in entries if getattr(c, f"legality_{fmt}") != "legal"]
    issues += [f"Non legale in {fmt}: {n}" for n in illegal]
    deck = TournamentDecklist(
        source=SOURCE,
        source_deck_id=row.deck_id,
        format_id=fmt,
        source_archetype_id=arch.source_archetype_id,
        archetype_name=arch.name,
        deck_title=row.title,
        pilot=row.pilot,
        event_name=row.event,
        placement=row.placement,
        played_on=row.played_on,
        cards=[
            {"oracle_id": c.oracle_id, "card_name": c.name, "board": b, "quantity": q}
            for c, b, q in entries
        ],
        raw_text=text,
        is_complete=not issues,
        issues=issues,
    )
    db.add(deck)
    db.flush()
    return deck


def _select_archetypes(archetypes: List[SourceArchetype]) -> List[SourceArchetype]:
    ordered = sorted(archetypes, key=lambda a: a.share_pct, reverse=True)
    selected, covered = [], 0.0
    for arch in ordered:
        if len(selected) >= settings.meta_max_archetypes:
            break
        if covered >= settings.meta_coverage_target_pct and len(selected) >= 5:
            break
        selected.append(arch)
        covered += arch.share_pct
    return selected


def _run_meta_sync_blocking(format_id: str) -> Dict[str, Any]:
    fmt = format_id.lower()
    if fmt not in FORMAT_CODES:
        raise ValueError(f"Formato non valido: {format_id}")
    code = FORMAT_CODES[fmt]
    meta_state.status = "running"
    meta_state.message = f"{fmt.capitalize()}: lettura del metagame da MTGTop8…"

    db: Session = SessionLocal()
    client = PoliteClient()
    sync_log = SyncLog(source=SOURCE, format_id=fmt, status="running")
    db.add(sync_log)
    db.commit()
    try:
        periods = parse_period_links(client.get("/format", f=code))
        meta_id = periods.get(PERIOD_LABEL)
        if not meta_id:
            raise RuntimeError(
                f"Periodo '{PERIOD_LABEL}' non trovato su MTGTop8: il layout potrebbe essere cambiato."
            )
        total_decks, archetypes = parse_format_breakdown(
            client.get("/format", f=code, meta=meta_id)
        )
        share_sum = sum(a.share_pct for a in archetypes)
        if len(archetypes) < 5 or not 60 <= share_sum <= 102:
            raise RuntimeError(
                f"Ripartizione del metagame non riconosciuta ({len(archetypes)} archetipi, "
                f"quote {share_sum:.1f}%): il layout di MTGTop8 potrebbe essere cambiato."
            )

        selected = _select_archetypes(archetypes)
        lists_by_arch: Dict[str, List[TournamentDecklist]] = {}
        fetched = reused = 0
        for index, arch in enumerate(selected, start=1):
            meta_state.message = (
                f"{fmt.capitalize()}: {arch.name} ({index}/{len(selected)}) · "
                f"{fetched} liste scaricate, {reused} dalla cache"
            )
            rows = parse_archetype_decks(
                client.get("/archetype", a=arch.source_archetype_id, meta=meta_id, f=code)
            )
            decks = []
            for row in rows[: settings.meta_lists_per_archetype]:
                cached = (
                    db.query(TournamentDecklist)
                    .filter_by(source=SOURCE, source_deck_id=row.deck_id)
                    .first()
                )
                if cached:
                    reused += 1
                    decks.append(cached)
                    continue
                try:
                    text = client.get("/mtgo", d=row.deck_id)
                except httpx.HTTPError as exc:
                    log.warning("MTGTop8 deck %s skipped: %s", row.deck_id, type(exc).__name__)
                    continue
                decks.append(_store_decklist(db, fmt, arch, row, text))
                fetched += 1
            lists_by_arch[arch.source_archetype_id] = decks
            db.commit()

        result = _build_snapshot(db, fmt, total_decks, archetypes, selected, lists_by_arch)
        _prune(db, fmt)

        sync_log.status = "completed"
        sync_log.records_processed = fetched
        sync_log.message = (
            f"{len(selected)} archetipi, {result['decklists']} liste complete "
            f"({fetched} nuove, {reused} dalla cache), copertura {result['coverage_pct']}%."
        )
        sync_log.completed_at = utcnow()
        db.commit()
        meta_state.status = "completed"
        meta_state.message = f"Meta {fmt.capitalize()} aggiornato: {sync_log.message}"
        return {"status": "completed", "format_id": fmt, **result}
    except Exception as exc:
        db.rollback()
        sync_log.status = "failed"
        sync_log.message = str(exc)
        sync_log.completed_at = utcnow()
        db.commit()
        meta_state.status = "failed"
        meta_state.message = f"Errore sync Meta {fmt}: {exc}"
        raise
    finally:
        client.close()
        db.close()


def _build_snapshot(
    db: Session,
    fmt: str,
    total_decks: int,
    archetypes: List[SourceArchetype],
    selected: List[SourceArchetype],
    lists_by_arch: Dict[str, List[TournamentDecklist]],
) -> Dict[str, Any]:
    oids = {c["oracle_id"] for decks in lists_by_arch.values() for d in decks for c in d.cards or []}
    cards_by_oid = {
        c.oracle_id: c for c in db.query(Card).filter(Card.oracle_id.in_(oids))
    } if oids else {}

    snap = MetaSnapshot(
        format_id=fmt,
        source=f"MTGTop8 · {PERIOD_LABEL}",
        fetched_at=utcnow(),
        total_decks_analyzed=total_decks,
        period_label=PERIOD_LABEL,
        notes=(
            f"{len(archetypes)} archetipi nella fonte; analizzati i primi {len(selected)} per quota. "
            "Nessun winrate né matchup testa a testa: la fonte non li pubblica."
        ),
    )
    db.add(snap)
    db.flush()

    warnings: List[str] = []
    covered = 0.0
    used_total = 0
    format_usage: Dict[str, Dict[str, Any]] = {}
    min_lists = settings.meta_min_lists_per_archetype
    for arch in selected:
        usable = [
            d
            for d in lists_by_arch.get(arch.source_archetype_id, [])
            if _usable(d, cards_by_oid, fmt)
        ]
        usable.sort(key=lambda d: d.played_on or "", reverse=True)
        stats = archetype_card_stats(d.cards for d in usable)
        if len(usable) < min_lists:
            warnings.append(
                f"{arch.name}: {len(usable)} liste complete (minimo {min_lists}); statistiche non affidabili."
            )
        else:
            covered += arch.share_pct
        used_total += len(usable)

        colors, color_name = get_color_combination_label(
            archetype_colors(stats, cards_by_oid)
        )
        nonland = sorted(
            (
                u
                for u in stats.cards.values()
                if u.main_lists
                and "Land" not in (cards_by_oid[u.oracle_id].type_line or "")
            ),
            key=lambda u: (u.main_lists, u.main_copies),
            reverse=True,
        )
        samples = []
        for d in usable[:3]:
            entries = [
                (cards_by_oid[c["oracle_id"]], c["board"], c["quantity"]) for c in d.cards
            ]
            _, mtgo = export_decklist_formats(entries)
            samples.append(
                {
                    "decklist_id": d.id,
                    "name": decklist_label(arch.name, d.deck_title, d.pilot),
                    "pilot": d.pilot,
                    "event": f"{d.event_name} (#{d.placement})" if d.placement else d.event_name,
                    "played_on": d.played_on,
                    "decklist_text": "Deck\n" + mtgo,
                }
            )
        archetype = MetaArchetype(
            snapshot_id=snap.id,
            format_id=fmt,
            name=arch.name,
            slug=f"{SOURCE}-{arch.source_archetype_id}",
            category=arch.category,
            tier=_tier(arch.share_pct),
            colors=colors,
            color_name=color_name if colors else None,
            meta_share_pct=arch.share_pct,
            winrate_pct=None,
            matches_count=0,
            key_cards=[u.card_name for u in nonland[:6]],
            sample_decklists=samples,
            source_url=f"{BASE_URL}/archetype?a={arch.source_archetype_id}&f={FORMAT_CODES[fmt]}",
            source_archetype_id=arch.source_archetype_id,
            decklist_ids=[d.id for d in usable],
            decklists_count=len(usable),
        )
        db.add(archetype)
        db.flush()
        for u in stats.cards.values():
            db.add(
                MetaArchetypeCard(
                    snapshot_id=snap.id,
                    archetype_id=archetype.id,
                    oracle_id=u.oracle_id,
                    card_name=u.card_name,
                    lists_count=stats.lists,
                    main_inclusion_pct=round(100 * u.main_lists / stats.lists, 1),
                    main_avg_copies=_avg(u.main_copies, u.main_lists),
                    side_inclusion_pct=round(100 * u.side_lists / stats.lists, 1),
                    side_avg_copies=_avg(u.side_copies, u.side_lists),
                )
            )
            if len(usable) >= min_lists:
                entry = format_usage.setdefault(
                    u.oracle_id, {"name": u.card_name, "rows": []}
                )
                entry["rows"].append((arch, stats.lists, u))

    _store_format_card_stats(db, snap, fmt, format_usage, covered)

    snap.coverage_pct = round(covered, 1)
    snap.decklists_count = used_total
    if covered < 70:
        warnings.insert(
            0,
            f"Copertura del meta {covered:.0f}%: meno del 70% della quota ha liste sufficienti.",
        )
    snap.quality_warnings = warnings
    snap.quality_status = "degraded" if covered < 70 else "ok"
    db.flush()
    return {
        "archetypes_count": len(selected),
        "decklists": used_total,
        "coverage_pct": snap.coverage_pct,
        "quality_status": snap.quality_status,
    }


def _store_format_card_stats(
    db: Session,
    snap: MetaSnapshot,
    fmt: str,
    format_usage: Dict[str, Dict[str, Any]],
    covered: float,
) -> None:
    """Format-wide presence, weighted by each archetype's share of the covered meta."""
    if not covered:
        return
    for oid, entry in format_usage.items():
        main = side = anywhere = main_weight = side_weight = 0.0
        main_copies = side_copies = 0.0
        per_arch = []
        for arch, lists, u in entry["rows"]:
            w = arch.share_pct / covered
            main += w * u.main_lists / lists
            side += w * u.side_lists / lists
            anywhere += w * u.any_lists / lists
            if u.main_lists:
                main_weight += w * u.main_lists
                main_copies += w * u.main_copies
            if u.side_lists:
                side_weight += w * u.side_lists
                side_copies += w * u.side_copies
            per_arch.append(
                {
                    "archetype": arch.name,
                    "main_inclusion_pct": round(100 * u.main_lists / lists, 1),
                    "main_avg_copies": _avg(u.main_copies, u.main_lists),
                    "side_inclusion_pct": round(100 * u.side_lists / lists, 1),
                    "side_avg_copies": _avg(u.side_copies, u.side_lists),
                    "weight": arch.share_pct * u.any_lists / lists,
                }
            )
        per_arch.sort(key=lambda r: r.pop("weight"), reverse=True)
        db.add(
            MetaCardStat(
                snapshot_id=snap.id,
                format_id=fmt,
                card_name=entry["name"],
                oracle_id=oid,
                overall_presence_pct=round(100 * anywhere, 1),
                main_presence_pct=round(100 * main, 1),
                main_avg_copies=round(main_copies / main_weight, 2) if main_weight else 0.0,
                side_presence_pct=round(100 * side, 1),
                side_avg_copies=round(side_copies / side_weight, 2) if side_weight else 0.0,
                top_archetypes=per_arch[:4],
            )
        )


def _prune(db: Session, fmt: str) -> None:
    old = (
        db.query(MetaSnapshot)
        .filter_by(format_id=fmt)
        .order_by(MetaSnapshot.fetched_at.desc())
        .offset(settings.meta_keep_snapshots)
        .all()
    )
    for snap in old:
        db.delete(snap)
    cutoff = (date.today() - timedelta(days=settings.meta_decklist_cache_days)).isoformat()
    db.query(TournamentDecklist).filter(
        TournamentDecklist.format_id == fmt, TournamentDecklist.played_on < cutoff
    ).delete(synchronize_session=False)
    db.flush()


# --------------------------------------------------------------------------- entry points

_sync_lock = threading.Lock()


def _run_meta_sync_exclusive(format_id: str) -> Dict[str, Any]:
    # Scheduler and manual syncs must not overlap and write duplicate snapshots.
    if not _sync_lock.acquire(blocking=False):
        return {
            "status": "already_running",
            "format_id": format_id,
            "message": meta_state.message,
        }
    try:
        return _run_meta_sync_blocking(format_id)
    finally:
        _sync_lock.release()


async def run_meta_sync_for_format(format_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_run_meta_sync_exclusive, format_id)


async def run_meta_sync_all() -> None:
    for fmt in FORMAT_CODES:
        try:
            await run_meta_sync_for_format(fmt)
        except Exception:
            # Already recorded in SyncLog; one failing format must not block the others.
            log.exception("Meta sync %s failed", fmt)
