from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.database import Base
from app.migrations import (
    detach_stale_deck_links,
    ensure_decks_autoincrement,
    repair_card_copy_limits,
    repair_meta_card_archetypes,
)
from app.models import (
    AIRun,
    Card,
    Deck,
    Format,
    GuideJob,
    MetaArchetype,
    MetaCardStat,
    MetaSnapshot,
)
from app.services.deck_validator import (
    castable_mana_value,
    castable_with_colors,
    compute_deck_analytics,
    export_decklist_formats,
    parse_decklist_text,
    validate_deck_entries,
)
from app.services.guide_jobs import _is_provider_failure
from app.services.scryfall_sync import apply_set_legality
from app.skills import runner
from app.skills.schemas import AIDeckCardSlot, AIDeckGenerationOutput


def add_card(db, name, **fields):
    defaults = dict(
        oracle_id=name,
        scryfall_id=name,
        name=name,
        normalized_name=name.lower(),
        type_line="Instant",
        set_code="tst",
        legality_standard="legal",
        legality_pioneer="legal",
        legality_modern="legal",
    )
    card = Card(**{**defaults, **fields})
    db.add(card)
    db.commit()
    return card


def test_stale_copy_limits_are_repaired_from_oracle(db):
    rats = add_card(
        db,
        "Relentless Rats",
        type_line="Creature - Rat",
        oracle_text="A deck can have any number of cards named Relentless Rats.",
        max_copies=4,
    )
    plains = db.get(Card, "Plains")
    plains.max_copies = 4
    db.commit()
    assert repair_card_copy_limits(db) == 2
    assert rats.max_copies is None and plains.max_copies is None
    assert validate_deck_entries("modern", [(rats, "main", 20), (plains, "main", 40)]).is_valid
    assert repair_card_copy_limits(db) == 0


def old_schema_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    old_ddl = str(CreateTable(Deck.__table__).compile(engine)).replace(" AUTOINCREMENT", "")
    with engine.begin() as conn:
        conn.exec_driver_sql(old_ddl)
    Base.metadata.create_all(engine)
    return engine


def test_deck_ids_are_never_reused_and_stale_links_are_detached(tmp_path):
    engine = old_schema_engine(tmp_path)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add(Format(id="modern", name="Modern"))
        db.commit()
        db.add_all([Deck(name="A", format_id="modern"), Deck(name="B", format_id="modern")])
        db.commit()
        db.add(AIRun(skill_name="deck_generation", prompt_version="v", model_id="m", provider="p", deck_id=2))
        db.add(GuideJob(format_id="modern", deck_id=2, request_json={}, status="queued"))
        db.commit()
        db.execute(text("DELETE FROM decks WHERE id = 2"))
        db.commit()

    assert ensure_decks_autoincrement(engine) is True
    assert ensure_decks_autoincrement(engine) is False
    with Session() as db:
        deck = Deck(name="C", format_id="modern")
        db.add(deck)
        db.commit()
        assert deck.id == 3
        assert detach_stale_deck_links(db) == 2
        assert db.query(AIRun).one().deck_id is None
        job = db.query(GuideJob).one()
        assert job.deck_id is None and job.status == "cancelled"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_deleting_a_deck_unlinks_runs_and_cancels_jobs(client, payload, db):
    did = client.post("/api/decks", json=payload).json()["id"]
    db.add(AIRun(skill_name="deck_guide", prompt_version="v", model_id="m", provider="p", deck_id=did))
    db.add(GuideJob(format_id="modern", deck_id=did, request_json={}, status="running"))
    db.commit()
    assert client.delete(f"/api/decks/{did}").status_code == 200
    db.expire_all()
    assert db.query(AIRun).one().deck_id is None
    job = db.query(GuideJob).one()
    assert (job.deck_id, job.status) == (None, "cancelled")


def test_blank_lines_group_the_main_deck_until_it_is_complete(db):
    entries, missing = parse_decklist_text(db, "20 Plains\n\n40 Island\n\n4 Plains\n11 Island")
    assert not missing
    assert sorted((c.name, b, q) for c, b, q in entries) == [
        ("Island", "main", 40),
        ("Island", "side", 11),
        ("Plains", "main", 20),
        ("Plains", "side", 4),
    ]


def test_exports_cite_only_arena_printings_and_name_split_cards(db):
    split = add_card(
        db,
        "Fire // Ice",
        layout="split",
        mana_cost="{1}{R} // {1}{U}",
        cmc=4,
        card_faces=[{"mana_cost": "{1}{R}"}, {"mana_cost": "{1}{U}"}],
        collector_number="1",
    )
    bolt = db.get(Card, "Lightning Bolt")
    bolt.arena_id, bolt.collector_number = 123, "9"
    db.commit()
    arena, mtgo = export_decklist_formats([(split, "main", 4), (bolt, "main", 4)])
    assert "4 Fire // Ice\n" in arena + "\n" and "(TST)" not in arena.splitlines()[1]
    assert "4 Lightning Bolt (TST) 9" in arena
    assert "4 Fire/Ice" in mtgo
    entries, missing = parse_decklist_text(db, mtgo)
    assert not missing and {c.name for c, _, _ in entries} == {"Fire // Ice", "Lightning Bolt"}
    assert castable_mana_value(split) == 2
    curve = compute_deck_analytics([(split, "main", 4)]).mana_curve
    assert curve["2"]["total"] == 4


@pytest.mark.parametrize(
    "cost,faces,colors,expected",
    [
        ("{R}", None, {"W"}, False),
        ("{R/W}", None, {"W"}, True),
        ("{2/R}", None, {"W"}, True),
        ("{U/P}", None, {"B"}, True),
        ("{2}{R} // ", [{"mana_cost": "{2}{R}"}, {"mana_cost": ""}], {"B"}, False),
        ("{B} // {R}", [{"mana_cost": "{B}"}, {"mana_cost": "{R}"}], {"B"}, True),
    ],
)
def test_castable_with_colors(cost, faces, colors, expected):
    card = SimpleNamespace(type_line="Instant", mana_cost=cost, card_faces=faces)
    assert castable_with_colors(card, colors) is expected


def test_generation_rejects_cards_outside_requested_colors(db):
    add_card(db, "Red Spell", mana_cost="{R}", colors=["R"])
    add_card(db, "White Spell", mana_cost="{W}", colors=["W"])

    def slot(name, qty):
        return AIDeckCardSlot(card_name=name, quantity=qty, role="r", reason="r")

    out = AIDeckGenerationOutput(
        deck_name="d",
        archetype="aggro",
        color_combination_name="W",
        strategy_overview="s",
        mana_curve_notes="m",
        key_synergies=[],
        mainboard=[slot("Plains", 52), slot("White Spell", 4), slot("Red Spell", 4)],
        sideboard=[slot("Island", 15)],
    )
    errors = runner._validate_ai_deck_against_format_rules(db, "modern", out, [], ["W"])
    assert len(errors) == 1 and "FUORI COLORE" in errors[0] and "Red Spell" in errors[0]
    assert not runner._validate_ai_deck_against_format_rules(db, "modern", out, ["Red Spell"], ["W"])


def test_standard_window_is_contiguous_and_excludes_future_sets():
    sets = [
        SimpleNamespace(code=c, set_type=t, released_at=d, digital=False)
        for c, t, d in [
            ("old", "core", "2018-07-13"),
            ("rot", "expansion", "2022-09-09"),
            ("anc", "expansion", "2023-09-08"),
            ("mid", "expansion", "2024-02-09"),
            ("cmm", "masters", "2025-01-01"),
            ("fut", "expansion", "2999-01-01"),
        ]
    ]
    counts = {
        "old": {"total": 100, "std": 60, "pio": 100, "mod": 100},
        "rot": {"total": 200, "std": 0, "pio": 200, "mod": 200},
        "anc": {"total": 250, "std": 250, "pio": 250, "mod": 250},
        "mid": {"total": 20, "std": 5, "pio": 20, "mod": 20},
        "cmm": {"total": 400, "std": 400, "pio": 0, "mod": 400},
        "fut": {"total": 300, "std": 300, "pio": 300, "mod": 300},
    }
    apply_set_legality(sets, counts)
    assert [s.code for s in sets if s.is_standard_legal] == ["anc", "mid"]
    assert not sets[-1].is_pioneer_legal and not sets[-1].is_modern_legal


def test_set_flags_are_recomputed_from_the_catalog(db):
    from app.migrations import recompute_set_legality
    from app.models import SetModel

    db.add(SetModel(code="new", name="New", set_type="expansion", released_at="2025-01-01"))
    db.add(SetModel(code="old", name="Old", set_type="expansion", released_at="2019-01-01"))
    for i in range(20):
        add_card(db, f"New {i}", set_code="new")
        add_card(db, f"Old {i}", set_code="old", legality_standard="not_legal")
    recompute_set_legality(db)
    assert db.get(SetModel, "new").is_standard_legal
    assert not db.get(SetModel, "old").is_standard_legal
    assert db.get(SetModel, "old").is_pioneer_legal


def test_meta_card_archetypes_use_observed_copies_only(db):
    snap = MetaSnapshot(format_id="modern", source="t")
    db.add(snap)
    db.flush()
    db.add(
        MetaArchetype(
            snapshot_id=snap.id,
            format_id="modern",
            name="Burn",
            slug="burn",
            sample_decklists=[{"decklist_text": "Deck\n4 Lightning Bolt\n56 Mountain"}],
        )
    )
    db.add(MetaArchetype(snapshot_id=snap.id, format_id="modern", name="Control", slug="c"))
    stat = MetaCardStat(
        snapshot_id=snap.id,
        format_id="modern",
        card_name="Lightning Bolt",
        top_archetypes=[
            {"archetype": "Burn", "presence_pct": 84.8},
            {"archetype": "Control", "presence_pct": 65.0},
        ],
    )
    db.add(stat)
    db.commit()
    assert repair_meta_card_archetypes(db) == 1
    assert stat.top_archetypes == [{"archetype": "Burn", "sample_copies": 4}]
    assert repair_meta_card_archetypes(db) == 0


def test_invented_matchup_counts_are_cleared(db):
    from app.migrations import clear_synthetic_matchup_counts
    from app.models import MetaMatchup

    snap = MetaSnapshot(format_id="modern", source="t")
    db.add(snap)
    db.flush()
    db.add(
        MetaMatchup(
            snapshot_id=snap.id,
            format_id="modern",
            archetype_a_name="A",
            archetype_b_name="B",
            winrate_a_pct=55.9,
            matches_count=66,
        )
    )
    db.commit()
    assert clear_synthetic_matchup_counts(db) == 1
    assert db.query(MetaMatchup).one().matches_count == 0


def test_cross_site_writes_are_rejected():
    import main

    client = TestClient(main.app)
    assert client.post("/api/nothing", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/nothing", headers={"Origin": "http://127.0.0.1:5173"}).status_code != 403
    assert client.post("/api/nothing").status_code != 403
    preflight = client.options(
        "/api/decks",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "DELETE"},
    )
    assert "access-control-allow-origin" not in preflight.headers


def test_only_provider_failures_are_reported_as_provider_timeouts():
    import httpx

    assert _is_provider_failure(TimeoutError())
    assert _is_provider_failure(httpx.ReadTimeout("t"))
    assert _is_provider_failure(RuntimeError("Il modello x ha restituito un output vuoto."))
    assert not _is_provider_failure(KeyError("bug"))
