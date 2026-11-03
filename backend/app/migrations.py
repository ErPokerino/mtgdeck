"""Idempotent startup repairs for databases written by earlier versions of the app."""

import logging

from sqlalchemy import Integer, cast, func, or_, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.models import AIRun, Card, Deck, DeckRevision, GuideJob, GuideVersion, utcnow

log = logging.getLogger("uvicorn.error")


def repair_card_copy_limits(db: Session) -> int:
    from app.services.scryfall_sync import detect_max_copies

    changed = 0
    candidates = db.query(Card).filter(
        or_(
            Card.is_basic_land.is_(True),
            Card.type_line.ilike("%basic%"),
            Card.oracle_text.ilike("%cards named%"),
        )
    )
    for card in candidates:
        limit, basic = detect_max_copies(card.name, card.type_line, card.oracle_text)
        if card.max_copies != limit or bool(card.is_basic_land) != basic:
            card.max_copies, card.is_basic_land = limit, basic
            changed += 1
    db.commit()
    return changed


def ensure_decks_autoincrement(engine: Engine) -> bool:
    """Rebuild `decks` with AUTOINCREMENT (SQLite only) without touching child rows."""
    if engine.dialect.name != "sqlite":
        return False
    with engine.connect() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='decks'")
        ).scalar()
        if not ddl or "AUTOINCREMENT" in ddl.upper():
            return False
        highest = conn.execute(
            text(
                "SELECT MAX(v) FROM ("
                " SELECT MAX(id) AS v FROM decks"
                " UNION ALL SELECT MAX(deck_id) FROM ai_runs"
                " UNION ALL SELECT MAX(deck_id) FROM guide_jobs"
                " UNION ALL SELECT MAX(deck_id) FROM guide_versions"
                " UNION ALL SELECT MAX(deck_id) FROM deck_revisions)"
            )
        ).scalar() or 0
        columns = ", ".join(c.name for c in Deck.__table__.columns)
        new_ddl = str(CreateTable(Deck.__table__).compile(engine)).replace(
            "CREATE TABLE decks ", "CREATE TABLE decks_rebuild ", 1
        )
        # foreign_keys must be off for the drop/rename; it can't change inside a transaction.
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            conn.exec_driver_sql("DROP TABLE IF EXISTS decks_rebuild")
            conn.exec_driver_sql(new_ddl)
            conn.exec_driver_sql(
                f"INSERT INTO decks_rebuild ({columns}) SELECT {columns} FROM decks"
            )
            conn.exec_driver_sql("DROP TABLE decks")
            conn.exec_driver_sql("ALTER TABLE decks_rebuild RENAME TO decks")
            for index in Deck.__table__.indexes:
                index.create(conn, checkfirst=True)
            conn.exec_driver_sql("DELETE FROM sqlite_sequence WHERE name='decks'")
            conn.execute(
                text("INSERT INTO sqlite_sequence(name, seq) VALUES ('decks', :seq)"),
                {"seq": highest},
            )
            problems = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise RuntimeError(f"Ricostruzione decks: vincoli violati {problems[:3]}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    log.info("decks rebuilt with AUTOINCREMENT (next id > %s)", highest)
    return True


def detach_stale_deck_links(db: Session) -> int:
    """Unlink runs and jobs that point to a missing deck or to a newer deck reusing the id."""
    detached = 0
    decks = {d.id: d.created_at for d in db.query(Deck.id, Deck.created_at)}
    for model in (AIRun, GuideJob):
        for row in db.query(model).filter(model.deck_id.isnot(None)):
            created = decks.get(row.deck_id)
            if created is None or (row.created_at and row.created_at < created):
                row.deck_id = None
                if model is GuideJob and row.status in ("queued", "running"):
                    row.status, row.finished_at = "cancelled", utcnow()
                detached += 1
    for version in db.query(GuideVersion).filter(GuideVersion.deck_id.isnot(None)):
        created = decks.get(version.deck_id)
        if created is None or (version.created_at and version.created_at < created):
            version.deck_id = None
            detached += 1
    db.commit()
    return detached


def repair_meta_card_archetypes(db: Session) -> int:
    """Replace synthetic per-archetype percentages with copies observed in reference lists."""
    import re

    from app.models import MetaArchetype, MetaCardStat

    line = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")
    snapshots = {
        sid
        for (sid,) in db.query(MetaCardStat.snapshot_id).distinct()
        if sid is not None
    }
    repaired = 0
    for sid in snapshots:
        stats = db.query(MetaCardStat).filter_by(snapshot_id=sid).all()
        if not any(
            "presence_pct" in item for st in stats for item in st.top_archetypes or []
        ):
            continue
        copies_by_arch = {}
        for arch in db.query(MetaArchetype).filter_by(snapshot_id=sid):
            copies = {}
            for sample in arch.sample_decklists or []:
                for raw in (sample.get("decklist_text") or "").splitlines():
                    m = line.match(raw)
                    if m:
                        name = re.split(r"\s*/+\s*", m[2])[0].strip().casefold()
                        copies[name] = copies.get(name, 0) + int(m[1])
            copies_by_arch[arch.name] = copies
        for st in stats:
            front = st.card_name.split(" // ")[0].casefold()
            st.top_archetypes = [
                {"archetype": name, "sample_copies": copies[front]}
                for name, copies in copies_by_arch.items()
                if copies.get(front)
            ]
            repaired += 1
    db.commit()
    return repaired


def recompute_set_legality(db: Session) -> None:
    from app.models import SetModel
    from app.services.scryfall_sync import apply_set_legality

    legal = ("legal", "banned")

    def count_legal(column):
        # Without the cast SQLAlchemy types SUM(boolean) as boolean and returns True.
        return func.sum(cast(column.in_(legal), Integer))

    set_counts = {
        code: {"total": total, "std": std or 0, "pio": pio or 0, "mod": mod or 0}
        for code, total, std, pio, mod in db.query(
            Card.set_code,
            func.count(),
            count_legal(Card.legality_standard),
            count_legal(Card.legality_pioneer),
            count_legal(Card.legality_modern),
        ).group_by(Card.set_code)
    }
    apply_set_legality(db.query(SetModel).all(), set_counts)
    db.commit()


def clear_synthetic_matchup_counts(db: Session) -> int:
    """Earlier scrapers stored invented match counts next to heuristic winrates."""
    from app.models import MetaMatchup

    cleared = (
        db.query(MetaMatchup)
        .filter(MetaMatchup.matches_count != 0)
        .update({"matches_count": 0}, synchronize_session=False)
    )
    db.commit()
    return cleared


def backfill_missing_revisions(db: Session) -> int:
    from app.routers.decks import record_revision

    with_revision = db.query(DeckRevision.deck_id).distinct()
    missing = db.query(Deck).filter(~Deck.id.in_(with_revision)).all()
    for deck in missing:
        record_revision(db, deck)
    db.commit()
    return len(missing)


def run_startup_repairs(engine: Engine, session_factory) -> None:
    ensure_decks_autoincrement(engine)
    with session_factory() as db:
        if db.query(func.count(Card.oracle_id)).scalar():
            fixed = repair_card_copy_limits(db)
            if fixed:
                log.info("copy limits repaired for %s cards", fixed)
            recompute_set_legality(db)
        detached = detach_stale_deck_links(db)
        if detached:
            log.info("detached %s stale deck links", detached)
        if clear_synthetic_matchup_counts(db):
            log.info("cleared invented match counts from heuristic matchups")
        meta_fixed = repair_meta_card_archetypes(db)
        if meta_fixed:
            log.info("replaced synthetic archetype stats on %s meta cards", meta_fixed)
        backfilled = backfill_missing_revisions(db)
        if backfilled:
            log.info("created initial revisions for %s decks", backfilled)
