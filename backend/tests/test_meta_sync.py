import gzip
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.migrations import add_missing_columns
from app.models import (
    Card,
    CardRuling,
    CardTag,
    MetaArchetype,
    MetaArchetypeCard,
    MetaCardStat,
    MetaSnapshot,
    SyncLog,
    TournamentDecklist,
)
from app.routers import cards as cards_router
from app.routers import meta as meta_router
from app.services import meta_scraper
from app.services.card_knowledge import expand_tags, ingest_rulings, ingest_tags

PERIODS = """
<div id=metas_list><div>
<a href="?f=PI&meta=194&a="><div class="S14 chosen_tr">Last 2 Weeks</div></a>
<a href="?f=PI&meta=193&a="><div class="S14 hover_tr">Last 2 Months</div></a>
</div></div>"""


def format_page(archetypes, total=500):
    blocks = [PERIODS, f"<div class=S14 align=center>{total} decks</div>"]
    category = None
    for cat, arch_id, name, share in archetypes:
        if cat != category:
            blocks.append(f"<div class=meta_arch>{cat} 50%</div>")
            category = cat
        blocks.append(
            f"""<div class=hover_tr><div style="display:flex;"><div><img></div><div>
            <div class=S14><a href=archetype?a={arch_id}&meta=193&f=PI>{name}</a></div>
            <div><div class=S14>{share} %</div><div class=S14></div></div></div></div></div>"""
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


def archetype_page(deck_ids):
    rows = "".join(
        f"""<tr class=hover_tr><td></td><td><a href=/event?e=1&d={d}&f=PI>List {d}</a></td>
        <td>Pilot {d}</td><td>Challenge</td><td></td><td>{i + 1}</td><td>0{i + 1}/10/26</td></tr>"""
        for i, d in enumerate(deck_ids)
    )
    return f"<table>{rows}</table>"


COMPLETE = "4 Lightning Bolt\n56 Plains\nSideboard\n4 Lesson Test\n11 Island"
SHORT = "4 Lightning Bolt\n46 Plains\nSideboard\n15 Island"

ARCHETYPES = [
    ("AGGRO", "1", "Burn", 30),
    ("AGGRO", "2", "Mono White", 20),
    ("CONTROL", "3", "UW Control", 15),
    ("CONTROL", "4", "Lessons", 10),
    ("COMBO", "5", "Tron", 10),
    ("COMBO", "6", "Storm", 5),
    ("COMBO", "7", "Rogue", 4),
]
DECKS = {"1": [101, 102, 103, 104], "2": [201, 202, 203], "3": [301, 302, 303],
         "4": [401, 402, 403], "5": [501, 502, 503], "6": [601, 602], "7": [701]}


class FakeSite:
    def __init__(self, archetypes=ARCHETYPES, periods=True):
        self.archetypes, self.periods, self.calls = archetypes, periods, []

    def __call__(self):
        return self

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "/format":
            if "meta" not in params:
                return PERIODS if self.periods else "<html></html>"
            return format_page(self.archetypes)
        if path == "/archetype":
            return archetype_page(DECKS[params["a"]])
        if path == "/mtgo":
            return SHORT if params["d"] == "104" else COMPLETE
        raise AssertionError(path)

    def close(self):
        pass


@pytest.fixture
def site(db, monkeypatch):
    fake = FakeSite()
    monkeypatch.setattr(meta_scraper, "PoliteClient", fake)
    monkeypatch.setattr(meta_scraper, "SessionLocal", sessionmaker(bind=db.get_bind()))
    bolt = db.get(Card, "Lightning Bolt")
    bolt.colors, bolt.mana_cost = ["R"], "{R}"
    db.commit()
    return fake


def test_parsers_read_periods_shares_categories_and_rows():
    assert meta_scraper.parse_period_links(PERIODS) == {"Last 2 Weeks": "194", "Last 2 Months": "193"}
    total, archs = meta_scraper.parse_format_breakdown(format_page(ARCHETYPES))
    assert total == 500
    assert [(a.name, a.share_pct, a.category) for a in archs][:3] == [
        ("Burn", 30.0, "aggro"), ("Mono White", 20.0, "aggro"), ("UW Control", 15.0, "control")
    ]
    rows = meta_scraper.parse_archetype_decks(archetype_page([9, 8]))
    assert (rows[0].deck_id, rows[0].placement, rows[0].played_on) == ("9", "1", "2026-10-01")


def test_card_stats_are_observed_per_board():
    lists = [
        [{"oracle_id": "a", "card_name": "A", "board": "main", "quantity": 4}],
        [{"oracle_id": "a", "card_name": "A", "board": "main", "quantity": 2},
         {"oracle_id": "b", "card_name": "B", "board": "side", "quantity": 3}],
    ]
    stats = meta_scraper.archetype_card_stats(lists)
    assert stats.lists == 2
    assert stats.main_inclusion("a") == 100 and stats.cards["a"].main_copies == 6
    assert (stats.cards["b"].side_lists, stats.cards["b"].main_lists) == (1, 0)


def test_archetype_colors_ignore_hybrid_and_rare_cards():
    from types import SimpleNamespace as NS

    cards = {
        "elf": NS(type_line="Creature", mana_cost="{G}", card_faces=[]),
        "leyline": NS(type_line="Enchantment", mana_cost="{G/W}{G/U}{B/G}{R/G}", card_faces=[]),
        "splash": NS(type_line="Instant", mana_cost="{W}", card_faces=[]),
        "mutagen": NS(type_line="Instant", mana_cost="{G/P}{2/U}", card_faces=[]),
    }
    lists = [[{"oracle_id": o, "card_name": o, "board": "main", "quantity": 4} for o in ("elf", "leyline", "mutagen")]] * 9
    lists.append([{"oracle_id": "splash", "card_name": "s", "board": "main", "quantity": 1}])
    stats = meta_scraper.archetype_card_stats(lists)
    assert meta_scraper.archetype_colors(stats, cards) == ["G"]


def test_sync_builds_an_observed_snapshot(db, site):
    result = meta_scraper._run_meta_sync_blocking("pioneer")
    assert result["status"] == "completed"
    snap = db.query(MetaSnapshot).one()
    archs = {a.name: a for a in db.query(MetaArchetype)}
    # Rogue (7th) is beyond the 90% coverage target; Storm has 2 lists only.
    assert set(archs) == {"Burn", "Mono White", "UW Control", "Lessons", "Tron", "Storm"}
    assert archs["Burn"].decklists_count == 3  # the 50-card list is excluded
    assert archs["Burn"].winrate_pct is None and archs["Burn"].tier == 1
    assert archs["Burn"].category == "aggro" and archs["Burn"].colors == ["R"]
    assert archs["Burn"].sample_decklists[0]["decklist_id"] in archs["Burn"].decklist_ids
    assert snap.coverage_pct == 85.0 and snap.quality_status == "ok"
    assert any("Storm" in w for w in snap.quality_warnings)
    bolt = db.query(MetaArchetypeCard).filter_by(archetype_id=archs["Burn"].id, card_name="Lightning Bolt").one()
    assert (bolt.main_inclusion_pct, bolt.main_avg_copies) == (100.0, 4.0)
    stat = db.query(MetaCardStat).filter_by(card_name="Lesson Test").one()
    assert stat.main_presence_pct == 0 and stat.side_presence_pct == 100.0
    assert stat.top_archetypes[0]["side_avg_copies"] == 4.0
    incomplete = db.query(TournamentDecklist).filter_by(source_deck_id="104").one()
    assert not incomplete.is_complete and "Mainboard di 50 carte" in incomplete.issues


def test_second_sync_reuses_cached_lists_and_prunes_snapshots(db, site, monkeypatch):
    meta_scraper._run_meta_sync_blocking("pioneer")
    first_downloads = sum(1 for p, _ in site.calls if p == "/mtgo")
    site.calls.clear()
    monkeypatch.setattr(meta_scraper.settings, "meta_keep_snapshots", 1)
    meta_scraper._run_meta_sync_blocking("pioneer")
    assert first_downloads == 18
    assert not [c for c in site.calls if c[0] == "/mtgo"]
    assert db.query(MetaSnapshot).count() == 1
    assert db.query(MetaArchetype).count() == 6


def test_banned_card_invalidates_cached_lists(db, site):
    meta_scraper._run_meta_sync_blocking("pioneer")
    db.get(Card, "Lesson Test").legality_pioneer = "banned"
    db.commit()
    meta_scraper._run_meta_sync_blocking("pioneer")
    latest = db.query(MetaSnapshot).order_by(MetaSnapshot.id.desc()).first()
    assert latest.decklists_count == 0 and latest.quality_status == "degraded"


def test_unrecognised_layout_fails_without_a_snapshot(db, site):
    site.periods = False
    with pytest.raises(RuntimeError, match="layout"):
        meta_scraper._run_meta_sync_blocking("pioneer")
    assert db.query(MetaSnapshot).count() == 0
    assert db.query(SyncLog).filter_by(source="mtgtop8").one().status == "failed"


def test_archetype_detail_and_loading_a_specific_list(db, site):
    meta_scraper._run_meta_sync_blocking("pioneer")
    app = FastAPI()
    app.include_router(meta_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    burn = db.query(MetaArchetype).filter_by(name="Burn").one()
    detail = client.get(f"/api/meta/pioneer/archetypes/{burn.id}").json()
    assert detail["decklists_count"] == 3 and len(detail["decklists"]) == 3
    assert detail["cards"][0]["main_inclusion_pct"] == 100.0
    deck_id = detail["decklists"][1]["id"]
    loaded = client.post(f"/api/meta/pioneer/load-archetype-deck/{burn.id}?decklist_id={deck_id}")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["validation"]["mainboard_count"] == 60
    other = db.query(TournamentDecklist).filter_by(source_deck_id="201").one()
    assert client.post(
        f"/api/meta/pioneer/load-archetype-deck/{burn.id}?decklist_id={other.id}"
    ).status_code == 404


def write_jsonl_gz(path, items):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")


def test_rulings_and_functional_tags_are_ingested(db, tmp_path):
    rulings = tmp_path / "rulings.jsonl.gz"
    write_jsonl_gz(rulings, [
        {"oracle_id": "Lightning Bolt", "published_at": "2024-01-01", "source": "wotc", "comment": "Second"},
        {"oracle_id": "Lightning Bolt", "published_at": "2020-01-01", "source": "wotc", "comment": "First"},
    ])
    tags = tmp_path / "tags.jsonl.gz"
    write_jsonl_gz(tags, [
        {"id": "r", "slug": "removal", "parent_ids": [], "taggings": []},
        {"id": "b", "slug": "burn-creature", "parent_ids": ["r"], "taggings": [{"oracle_id": "Lightning Bolt"}]},
        {"id": "c", "slug": "counterspell", "parent_ids": [], "taggings": [{"oracle_id": "Island"}]},
    ])
    assert ingest_rulings(db, rulings) == 1
    assert [r["comment"] for r in db.get(CardRuling, "Lightning Bolt").rulings] == ["First", "Second"]
    assert ingest_tags(db, tags) == 2
    assert {(t.oracle_id, t.tag) for t in db.query(CardTag)} == {
        ("Lightning Bolt", "removal"), ("Island", "counterspell")
    }
    app = FastAPI()
    app.include_router(cards_router.router)
    app.dependency_overrides[get_db] = lambda: db
    detail = TestClient(app).get("/api/cards/Lightning Bolt?format_id=modern").json()
    assert detail["functional_tags"] == ["removal"] and len(detail["rulings"]) == 2


def test_tag_expansion_survives_cycles():
    tags = [
        {"id": "a", "slug": "a", "parent_ids": ["b"], "taggings": [{"oracle_id": "x"}]},
        {"id": "b", "slug": "b", "parent_ids": ["a"], "taggings": [{"oracle_id": "y"}]},
    ]
    assert expand_tags(tags, ["a", "missing"]) == {"a": {"x", "y"}}


def test_new_nullable_columns_are_added_to_existing_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE meta_snapshots (id INTEGER PRIMARY KEY, format_id VARCHAR(32) NOT NULL, "
            "source VARCHAR(64) NOT NULL, fetched_at DATETIME, total_decks_analyzed INTEGER, notes TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO meta_snapshots (format_id, source) VALUES ('modern', 'x')")
    added = add_missing_columns(engine)
    assert "meta_snapshots.coverage_pct" in added
    assert "coverage_pct" in {c["name"] for c in inspect(engine).get_columns("meta_snapshots")}
    assert add_missing_columns(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT quality_status FROM meta_snapshots")).scalar() is None
    engine.dispose()


def test_net_card_advantage_drops_cantrips_loot_and_rummage():
    tags = [
        {"id": "ca", "slug": "card-advantage", "parent_ids": [], "taggings": []},
        {"id": "d", "slug": "draw", "parent_ids": ["ca"], "taggings": []},
        {"id": "pd", "slug": "pure-draw", "parent_ids": ["d"], "taggings": [{"oracle_id": "Divination"}]},
        {"id": "ct", "slug": "cantrip", "parent_ids": ["pd"], "taggings": [{"oracle_id": "Opt"}]},
        {"id": "lo", "slug": "rummage", "parent_ids": ["d"], "taggings": [{"oracle_id": "Faithless Looting"}]},
        {"id": "tv", "slug": "tormenting-voice", "parent_ids": ["lo"], "taggings": [{"oracle_id": "Tormenting Voice"}]},
        {"id": "im", "slug": "impulse", "parent_ids": ["ca"], "taggings": [{"oracle_id": "Memory Deluge"}]},
    ]
    from app.services.card_knowledge import DERIVED_TAGS, FUNCTIONAL_TAGS

    out = expand_tags(tags, FUNCTIONAL_TAGS, DERIVED_TAGS)
    assert out["card-advantage"] == {"Divination", "Opt", "Faithless Looting", "Tormenting Voice", "Memory Deluge"}
    assert out["card-advantage-net"] == {"Divination", "Tormenting Voice", "Memory Deluge"}
    assert out["cantrip"] == {"Opt"}
