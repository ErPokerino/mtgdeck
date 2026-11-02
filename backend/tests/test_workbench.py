from datetime import timedelta
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from app.models import Card, Deck, GuideVersion, DeckRevision, SyncLog, utcnow
from app.services.deck_validator import validate_deck_entries, parse_decklist_text
from app.services.guide_quality import (
    validate_guide,
    weighted_meta_estimate,
    require_fresh_catalog,
)
from app.skills.schemas import (
    AIDeckGenerationOutput,
    AIDeckGenerationRequest,
    AIDeckGuideRequest,
    AIDeckGuideOutput,
)
from app.skills import runner
from app.services.guide_pdf import render_guide_pdf


def test_combined_copy_limit_and_basic_exemption(db):
    bolt, plains = db.get(Card, "Lightning Bolt"), db.get(Card, "Plains")
    report = validate_deck_entries(
        "modern", [(plains, "main", 60), (bolt, "main", 3), (bolt, "side", 2)]
    )
    assert not report.is_valid
    assert any(i.code == "MAX_COPIES_EXCEEDED" for i in report.issues)
    assert validate_deck_entries("modern", [(plains, "main", 80)]).is_valid


@pytest.mark.parametrize(
    "status,code", [("banned", "CARD_BANNED"), ("not_legal", "CARD_NOT_LEGAL")]
)
def test_ban_and_rotation_are_per_oracle(db, status, code):
    card = db.get(Card, "Plains")
    card.legality_modern = status
    assert any(
        i.code == code
        for i in validate_deck_entries("modern", [(card, "main", 60)]).issues
    )


@pytest.mark.parametrize("board,qty", [("unknown", 3), ("main", -3), ("main", 0)])
def test_invalid_raw_entries(db, board, qty):
    assert not validate_deck_entries(
        "modern", [(db.get(Card, "Plains"), board, qty)]
    ).is_valid


def test_companion_counts_inside_fifteen(db):
    report = validate_deck_entries(
        "modern",
        [
            (db.get(Card, "Plains"), "main", 60),
            (db.get(Card, "Island"), "side", 15),
            (db.get(Card, "Lightning Bolt"), "companion", 1),
        ],
    )
    assert report.sideboard_count == 16 and not report.is_valid


def test_lifecycle_revisions_archive_restore_duplicate(client, payload):
    result = client.post("/api/decks", json=payload)
    assert result.status_code == 200, result.text
    deck = result.json()
    did = deck["id"]
    revisions = client.get(f"/api/decks/{did}/revisions").json()
    assert len(revisions) == 1
    assert client.put(f"/api/decks/{did}", json={"name": "Changed"}).status_code == 200
    assert len(client.get(f"/api/decks/{did}/revisions").json()) == 2
    assert (
        client.post(f"/api/decks/{did}/restore/{revisions[0]['id']}").json()["name"]
        == payload["name"]
    )
    assert client.post(f"/api/decks/{did}/duplicate").json()["id"] != did
    assert client.put(f"/api/decks/{did}/archive").status_code == 200
    assert did not in [d["id"] for d in client.get("/api/decks").json()]
    assert did in [d["id"] for d in client.get("/api/decks?archived=true").json()]
    assert client.put(f"/api/decks/{did}/archive?archived=false").status_code == 200


def test_unknown_import_and_invalid_payload_do_not_silently_save(client, payload):
    assert (
        client.post(
            "/api/decks/import",
            json={"text": "60 Plains\n1 Missing Card", "format_id": "modern"},
        ).status_code
        == 422
    )
    assert (
        client.post("/api/decks/import", json={"text": "nonsense"}).status_code == 400
    )
    payload["cards"][0]["card_name"] = "Missing"
    assert client.post("/api/decks", json=payload).status_code == 422
    assert client.get("/api/decks").json() == []


@pytest.mark.parametrize("field,value", [("quantity", -1), ("board", "not-a-board")])
def test_typed_entry_rejects_invalid_inputs(client, payload, field, value):
    payload["cards"][0][field] = value
    assert client.post("/api/decks", json=payload).status_code == 422


def test_import_aggregates_and_exports_companion_separately(db):
    entries, missing = parse_decklist_text(
        db, "Deck\n30 Plains\n30 Plains\n\nSideboard\n15 Island"
    )
    assert not missing and [(b, q) for _, b, q in entries] == [
        ("main", 60),
        ("side", 15),
    ]


def test_weighted_rate_uses_real_shares_and_discloses_uncovered():
    archetypes = [
        SimpleNamespace(name="Aggro", meta_share_pct=30),
        SimpleNamespace(name="Control", meta_share_pct=20),
        SimpleNamespace(name="Combo", meta_share_pct=15),
    ]
    guide = {
        "sideboard_guide": [
            {"opponent_archetype": "Aggro", "expected_winrate_pct": 60},
            {"opponent_archetype": "Control", "expected_winrate_pct": 40},
        ]
    }
    estimate = weighted_meta_estimate(guide, archetypes)
    assert estimate["weighted_winrate_pct"] == 52
    assert estimate["coverage_pct"] == 50 and estimate["uncovered_share_pct"] == 50
    assert estimate["missing_archetypes"] == ["Combo"]


def test_weighted_rate_missing_and_inconsistent_data():
    assert (
        weighted_meta_estimate({"sideboard_guide": []}, [])["weighted_winrate_pct"]
        is None
    )
    arch = [SimpleNamespace(name="A", meta_share_pct=110)]
    assert (
        weighted_meta_estimate(
            {
                "sideboard_guide": [
                    {"opponent_archetype": "A", "expected_winrate_pct": 55}
                ]
            },
            arch,
        )["weighted_winrate_pct"]
        is None
    )


def test_duplicate_matchups_do_not_double_count():
    with pytest.raises(ValueError):
        weighted_meta_estimate(
            {
                "sideboard_guide": [
                    {"opponent_archetype": "A", "expected_winrate_pct": 55}
                ]
                * 2
            },
            [],
        )


def test_sideboard_validation_rejects_aggregate_overdraw_without_mutation(
    db, guide_data
):
    plan = {
        "opponent_archetype": "Aggro",
        "cards_in": [
            {"card_name": "Island", "quantity": 8},
            {"card_name": "Island", "quantity": 8},
        ],
        "cards_out": [{"card_name": "Plains", "quantity": 16}],
    }
    guide_data["sideboard_guide"] = [plan]
    errors = validate_guide(
        guide_data,
        [(db.get(Card, "Plains"), "main", 60), (db.get(Card, "Island"), "side", 15)],
    )
    assert errors and plan["cards_in"][0]["quantity"] == 8


def test_mulligan_cannot_contain_missing_or_excess_cards(db, guide_data):
    guide_data["mulligan_examples"][0]["hand_cards"] = ["Lightning Bolt"] * 7
    assert validate_guide(guide_data, [(db.get(Card, "Lightning Bolt"), "main", 4)])


def test_guide_history_survives_deck_edits_and_delete(client, db, payload, guide_data):
    did = client.post("/api/decks", json=payload).json()["id"]
    deck = db.get(Deck, did)
    deck.guide_json = guide_data
    version = GuideVersion(
        deck_id=did,
        deck_name=deck.name,
        format_id="modern",
        model_id="test",
        deck_snapshot=payload["cards"],
        guide_json=guide_data,
    )
    db.add(version)
    db.commit()
    gid = version.id
    client.put(
        f"/api/decks/{did}",
        json={"cards": [{"card_name": "Plains", "board": "main", "quantity": 61}]},
    )
    assert client.get(f"/api/decks/{did}").json()["guide_json"] is None
    assert client.get(f"/api/guides/{gid}").json()["deck_snapshot"] == payload["cards"]
    assert client.delete(f"/api/decks/{did}").status_code == 200
    assert client.get(f"/api/guides/{gid}").json()["deck_id"] is None
    assert db.query(DeckRevision).count() == 0
    pdf = client.get(f"/api/guides/{gid}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_simple_model_is_not_a_strategic_override(client, db):
    from app.services.ai_provider import get_skill_model_and_config

    with pytest.raises(ValueError):
        get_skill_model_and_config(db, "deck_generation", "gemini-3.5-flash-lite")
    assert (
        client.put(
            "/api/settings", json={"selected_complex_model_id": "gemini-3.5-flash-lite"}
        ).status_code
        == 400
    )


def test_stale_catalog_blocks_ai(db):
    log = db.query(SyncLog).first()
    log.completed_at = utcnow() - timedelta(hours=49)
    db.commit()
    with pytest.raises(ValueError, match="48"):
        require_fresh_catalog(db)


def test_lessons_and_unusual_manabase_are_not_illegal(db):
    output = AIDeckGenerationOutput(
        deck_name="Lesson",
        archetype="combo",
        color_combination_name="U",
        strategy_overview="Test",
        mana_curve_notes="60 land test",
        key_synergies=[],
        mainboard=[
            dict(card_name="Plains", quantity=56, role="Mana", reason="test"),
            dict(card_name="Lesson Test", quantity=4, role="Engine", reason="test"),
        ],
        sideboard=[dict(card_name="Island", quantity=15, role="Mana", reason="test")],
    )
    assert runner._validate_ai_deck_against_format_rules(db, "modern", output, []) == []


def test_generation_never_fills_invalid_slots_or_saves(db, monkeypatch):
    output = AIDeckGenerationOutput(
        deck_name="Bad",
        archetype="combo",
        color_combination_name="W",
        strategy_overview="Test",
        mana_curve_notes="Test",
        key_synergies=[],
        mainboard=[dict(card_name="Plains", quantity=59, role="Mana", reason="test")],
        sideboard=[dict(card_name="Island", quantity=15, role="Mana", reason="test")],
    )

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            return output

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    monkeypatch.setattr(
        runner, "_get_legal_card_pool_context", lambda **kwargs: "test evidence"
    )
    with pytest.raises(ValueError, match="non salvata"):
        runner.run_deck_generation_skill(
            db, AIDeckGenerationRequest(format_id="modern")
        )
    assert db.query(Deck).count() == 0


def test_guide_generation_stores_exact_snapshot_and_weighted_evidence(
    client, db, payload, guide_data, monkeypatch
):
    did = client.post("/api/decks", json=payload).json()["id"]

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            from app.skills.schemas import RulesAuditOutput

            if kwargs["response_model"] is RulesAuditOutput:
                return RulesAuditOutput(issues=[])
            return AIDeckGuideOutput(**guide_data)

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    result = runner.run_deck_guide_skill(
        db, AIDeckGuideRequest(deck_id=did, format_id="modern")
    )
    assert result["meta"]["guide_id"]
    assert result["guide"]["meta_estimate"]["weighted_winrate_pct"] is None
    assert len(result["guide"]["decklist"]) == 2
    assert client.get(f"/api/guides/{result['meta']['guide_id']}").status_code == 200


def test_pdf_escapes_model_text_and_has_paginated_content(guide_data):
    from io import BytesIO
    from pypdf import PdfReader

    pdf = render_guide_pdf(
        guide_data,
        "Guida di prova",
        "modern",
        [{"quantity": 60, "board": "main", "card_name": "Plains"}],
    )
    reader = PdfReader(BytesIO(pdf))
    text = "".join(p.extract_text() for p in reader.pages)
    assert len(reader.pages) >= 2 and "Tesi <verificabile> & coerente" in text


def test_unchanged_save_keeps_current_guide(client, db, payload, guide_data):
    did = client.post("/api/decks", json=payload).json()["id"]
    deck = db.get(Deck, did)
    deck.guide_json = guide_data
    db.commit()
    result = client.put(f"/api/decks/{did}", json=payload)
    assert {
        k: v for k, v in result.json()["guide_json"].items() if k != "rules_warnings"
    } == guide_data


def test_arena_companion_roundtrip_is_not_double_counted(db):
    from app.services.deck_validator import export_decklist_formats

    plains, bolt = db.get(Card, "Plains"), db.get(Card, "Lightning Bolt")
    arena, _ = export_decklist_formats([(plains, "main", 60), (bolt, "companion", 1)])
    parsed, missing = parse_decklist_text(db, arena)
    assert not missing and sum(q for _, b, q in parsed if b != "main") == 1


def test_sync_upsert_preserves_foreign_keys_and_invalidates_absent_cards(
    client, db, payload, tmp_path, monkeypatch
):
    import json
    from app.services import scryfall_sync
    from sqlalchemy import text

    did = client.post("/api/decks", json=payload).json()["id"]
    db.execute(
        text(
            "CREATE VIRTUAL TABLE cards_fts USING fts5(oracle_id UNINDEXED,name,type_line,oracle_text)"
        )
    )
    db.commit()
    path = tmp_path / "cards.json"
    path.write_text(
        json.dumps(
            [
                {
                    "oracle_id": "Plains",
                    "id": "Plains",
                    "name": "Plains",
                    "type_line": "Basic Land — Plains",
                    "set": "tst",
                    "legalities": {"modern": "legal"},
                    "games": ["paper"],
                }
            ]
        )
    )
    monkeypatch.setattr(scryfall_sync, "SessionLocal", lambda: db)
    assert scryfall_sync._ingest_bulk_file_sync(path) == 1
    assert db.get(Deck, did) is not None
    assert db.get(Card, "Island").legality_modern == "not_legal"
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert db.execute(text("PRAGMA foreign_key_check")).all() == []


def test_reflection_cannot_copy_legendary_but_may_copy_nonlegendary(db):
    from app.services.guide_quality import validate_guide

    fable = Card(
        oracle_id="fable",
        name="Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
        type_line="Enchantment // Creature",
        scryfall_id="f",
        set_code="tst",
    )
    sheoldred = Card(
        oracle_id="sheoldred",
        name="Sheoldred, the Apocalypse",
        type_line="Legendary Creature - Phyrexian Praetor",
        scryfall_id="s",
        set_code="tst",
    )
    entries = [(fable, "main", 4), (sheoldred, "main", 4)]
    guide = {
        "card_roles": [
            {
                "card_name": fable.name,
                "quantity": 4,
                "explanation": "Una volta trasformata, copiare Sheoldred o Kroxa chiude la partita.",
            }
        ]
    }
    assert any("non può bersagliare" in e for e in validate_guide(guide, entries))
    guide["card_roles"][0]["explanation"] = (
        "Non può copiare Sheoldred, che è leggendaria."
    )
    assert not validate_guide(guide, entries)


def test_reflection_guard_does_not_confuse_context_with_copy_target():
    from app.services.guide_quality import reflection_copy_errors

    fable = Card(
        oracle_id="fable",
        name="Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
        type_line="Enchantment // Creature",
        scryfall_id="f",
        set_code="tst",
    )
    kroxa = Card(
        oracle_id="k",
        name="Kroxa, Titan of Death's Hunger",
        type_line="Legendary Creature - Elder Giant",
        scryfall_id="k",
        set_code="tst",
    )
    entries = [(fable, "main", 4), (kroxa, "main", 4)]
    guide = {
        "card_roles": [
            {
                "card_name": fable.name,
                "explanation": "Filtre pour Kroxa, puis peut copier Harvester.",
            }
        ]
    }
    assert not reflection_copy_errors(guide, entries)


def test_pdf_embeds_hand_and_card_images(guide_data):
    from io import BytesIO
    from PIL import Image
    from pypdf import PdfReader

    buf = BytesIO()
    Image.new("RGB", (63, 88), "red").save(buf, format="PNG")
    img = buf.getvalue()
    guide_data["card_roles"] = [
        {
            "card_name": "Plains",
            "quantity": 60,
            "role_category": "Manabase",
            "explanation": "Source de mana.",
        }
    ]
    pdf = render_guide_pdf(
        guide_data,
        "Guida con immagini",
        "modern",
        [{"quantity": 60, "board": "main", "card_name": "Plains"}],
        {"plains": img},
    )
    reader = PdfReader(BytesIO(pdf))
    assert any(page.get("/Resources", {}).get("/XObject") for page in reader.pages)


def test_oracle_audit_blocks_unresolved_contradictions(
    client, db, payload, guide_data, monkeypatch
):
    from app.skills.schemas import (
        RulesAuditOutput,
        RulesAuditIssue,
        GuideRevisionOutput,
    )

    did = client.post("/api/decks", json=payload).json()["id"]
    previous_guide = {"executive_summary": "Versione precedente da conservare"}
    db.get(Deck, did).guide_json = previous_guide
    db.commit()

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            if kwargs["response_model"] is GuideRevisionOutput:
                return GuideRevisionOutput(patches=[])
            if kwargs["response_model"] is RulesAuditOutput:
                return RulesAuditOutput(
                    issues=[
                        RulesAuditIssue(
                            explanation="Contradiction", oracle_quote="Basic Land"
                        )
                    ]
                )
            return AIDeckGuideOutput(**guide_data)

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    with pytest.raises(ValueError, match="Revisione Oracle"):
        runner.run_deck_guide_skill(
            db, AIDeckGuideRequest(deck_id=did, format_id="modern")
        )
    assert db.query(GuideVersion).count() == 0
    assert db.get(Deck, did).guide_json == previous_guide


def test_guide_repairs_coverage_then_oracle_before_saving(
    client, db, payload, guide_data, monkeypatch
):
    from copy import deepcopy
    from app.models import MetaSnapshot, MetaArchetype, AIRun
    from app.skills.schemas import (
        RulesAuditOutput,
        RulesAuditIssue,
        GuideRevisionOutput,
        GuideTextPatch,
    )

    did = client.post("/api/decks", json=payload).json()["id"]
    snapshot = MetaSnapshot(format_id="modern", source="fixture")
    db.add(snapshot)
    db.flush()
    for name, share in [("Aggro", 30), ("Control", 20)]:
        db.add(
            MetaArchetype(
                snapshot_id=snapshot.id,
                format_id="modern",
                name=name,
                slug=name.lower(),
                meta_share_pct=share,
            )
        )
    db.commit()
    draft = deepcopy(guide_data)
    draft["executive_summary"] = "Plains è un istantaneo."
    corrected = "Plains è una terra base."
    calls = []

    class Provider:
        provider_name = "fake"

        def generate_structured(self, **kwargs):
            kind = kwargs["response_model"]
            calls.append(kind)
            if kind is AIDeckGuideOutput:
                result = deepcopy(draft)
                if calls.count(AIDeckGuideOutput) > 1:
                    assert "Manca il matchup obbligatorio" in kwargs["user_prompt"]
                    for name, wr in [("Aggro", 60), ("Control", 40)]:
                        result["sideboard_guide"].append(
                            dict(
                                opponent_archetype=name,
                                tier=1,
                                expected_winrate_pct=wr,
                                matchup_difficulty="Equilibrato",
                                gameplan_pre_side="Piano pre",
                                gameplan_post_side="Piano post",
                                on_the_play_notes="Play",
                                on_the_draw_notes="Draw",
                                cards_in=[],
                                cards_out=[],
                                estimate_rationale="Clock e risposte da verificare nei test",
                            )
                        )
                return AIDeckGuideOutput(**result)
            if kind is RulesAuditOutput:
                assert (
                    db.query(GuideVersion).count() == 0
                )  # No draft has been published.
                if corrected not in kwargs["user_prompt"]:
                    return RulesAuditOutput(
                        issues=[
                            RulesAuditIssue(
                                explanation="Plains non è un istantaneo",
                                oracle_quote="Basic Land",
                            )
                        ]
                    )
                return RulesAuditOutput(issues=[])
            assert kind is GuideRevisionOutput
            return GuideRevisionOutput(
                patches=[
                    GuideTextPatch(
                        path="/executive_summary",
                        original_text=draft["executive_summary"],
                        replacement_text=corrected,
                    )
                ]
            )

    monkeypatch.setattr(runner, "get_active_ai_provider", lambda _: Provider())
    result = runner.run_deck_guide_skill(
        db, AIDeckGuideRequest(deck_id=did, format_id="modern")
    )
    guide = result["guide"]
    assert guide["executive_summary"] == corrected
    assert guide["meta_estimate"]["weighted_winrate_pct"] == 52
    assert guide["meta_estimate"]["coverage_pct"] == 50
    assert guide["meta_estimate"]["status"] == "available"
    assert guide["quality_review"]["revision_count"] == 2
    assert db.query(GuideVersion).count() == 1
    assert db.get(Deck, did).guide_json == guide
    assert db.query(AIRun).one().validation_attempts == 3
    assert calls == [
        AIDeckGuideOutput,
        AIDeckGuideOutput,
        RulesAuditOutput,
        GuideRevisionOutput,
        RulesAuditOutput,
    ]


def test_text_revision_is_atomic_and_cannot_change_cards(guide_data):
    from app.services.guide_quality import apply_guide_text_patches
    from app.skills.schemas import GuideTextPatch

    original = guide_data["executive_summary"]
    patch = GuideTextPatch(
        path="/executive_summary", original_text=original, replacement_text="Correzione"
    )
    wrong = GuideTextPatch(
        path="/mulligan_examples/0/hand_cards/0",
        original_text="Plains",
        replacement_text="Island",
    )
    with pytest.raises(ValueError):
        apply_guide_text_patches(guide_data, [patch, wrong])
    assert guide_data["executive_summary"] == original
    patch.original_text = "Testo non presente"
    with pytest.raises(ValueError):
        apply_guide_text_patches(guide_data, [patch])


def test_unavailable_estimate_explains_the_actual_cause():
    empty = weighted_meta_estimate({"sideboard_guide": []}, [])
    assert empty["status"] == "no_meta" and "Nessuno snapshot" in empty["reason"]
    unmatched = weighted_meta_estimate(
        {"sideboard_guide": []}, [SimpleNamespace(name="Aggro", meta_share_pct=30)]
    )
    assert (
        unmatched["status"] == "no_matchups"
        and unmatched["weighted_winrate_pct"] is None
    )
