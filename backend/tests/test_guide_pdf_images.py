from io import BytesIO
from types import SimpleNamespace

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream
from app.services import guide_images
from app.services.guide_pdf import render_guide_pdf


def png(color):
    buffer = BytesIO()
    Image.new("RGB", (244, 340), color).save(buffer, format="PNG")
    return buffer.getvalue()


def drawings(reader, page):
    return sum(
        op == b"Do" for _, op in ContentStream(page.get_contents(), reader).operations
    )


def test_every_hand_role_and_deck_entry_is_illustrated(guide_data):
    names = ["Plains", "Island", "Mountain", "Forest"]
    images = {
        name.lower(): png(color)
        for name, color in zip(names, ("red", "green", "blue", "yellow"))
    }
    guide_data["mulligan_examples"] = [
        dict(
            hand_cards=[name] * 7,
            context="Game 1",
            verdict="KEEP",
            analysis="Piano operativo",
        )
        for name in names
    ]
    guide_data["card_roles"] = [
        dict(
            card_name=name,
            quantity=15,
            role_category="Manabase",
            explanation="Decisione di sequenziamento",
        )
        for name in names
    ]
    deck = [dict(card_name=name, quantity=15, board="main") for name in names]
    reader = PdfReader(
        BytesIO(
            render_guide_pdf(guide_data, "Illustrated primer", "modern", deck, images)
        )
    )
    texts = [p.extract_text() for p in reader.pages]
    for i in range(1, 5):
        page = next(p for p, text in zip(reader.pages, texts) if f"Mano {i} /" in text)
        assert drawings(reader, page) >= 7
    gallery = next(
        p for p, text in zip(reader.pages, texts) if "Mainboard / vista carte" in text
    )
    assert drawings(reader, gallery) == 4
    roles = next(
        p for p, text in zip(reader.pages, texts) if "Copie, ruolo e decisioni" in text
    )
    start = (
        reader.pages.index(roles)
        if hasattr(reader.pages, "index")
        else next(i for i, t in enumerate(texts) if "Copie, ruolo e decisioni" in t)
    )
    end = next(
        i for i in range(start + 1, len(texts)) if "Sinergie e linee" in texts[i]
    )
    assert sum(drawings(reader, p) for p in list(reader.pages)[start:end]) == 4


def test_dfc_roles_include_both_faces_and_missing_images_keep_card_names(guide_data):
    name = "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"
    guide_data["card_roles"] = [
        dict(
            card_name=name,
            quantity=4,
            role_category="Engine",
            explanation="Fronte e abilità del retro",
        )
    ]
    reader = PdfReader(
        BytesIO(
            render_guide_pdf(
                guide_data,
                "DFC primer",
                "pioneer",
                [],
                {
                    "fable of the mirror-breaker": png("red"),
                    "fable of the mirror-breaker::back": png("blue"),
                },
            )
        )
    )
    page = next(
        p for p in reader.pages if "Fronte e abilità del retro" in p.extract_text()
    )
    assert drawings(reader, page) == 2
    assert "FRONTE" in page.extract_text() and "RETRO" in page.extract_text()
    empty = PdfReader(
        BytesIO(render_guide_pdf(guide_data, "Offline primer", "pioneer", []))
    )
    assert any(
        "Immagine non disponibile" in p.extract_text() and "Fable" in p.extract_text()
        for p in empty.pages
    )


def test_loader_downloads_all_cards_normal_resolution_and_real_backs(monkeypatch):
    urls = []

    def fetch(url):
        urls.append(url)
        return png("red")

    monkeypatch.setattr(guide_images, "fetch_card_image", fetch)
    cards = [
        SimpleNamespace(
            name=f"Card {i}",
            layout="normal",
            image_uris={"small": f"small-{i}", "normal": f"normal-{i}"},
            card_faces=[],
        )
        for i in range(12)
    ]
    cards.append(
        SimpleNamespace(
            name="Fable // Reflection",
            layout="transform",
            image_uris={},
            card_faces=[
                dict(image_uris={"normal": "front"}),
                dict(image_uris={"normal": "back"}),
            ],
        )
    )
    images = guide_images.load_guide_images(cards)
    assert len(images) == 14
    assert "fable::back" in images and "card 11" in images
    assert set(urls) == {f"normal-{i}" for i in range(12)} | {"front", "back"}


def test_only_successful_images_are_cached_and_invalid_hosts_are_rejected(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(guide_images, "CACHE_DIR", tmp_path)
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            calls.append(url)
            return SimpleNamespace(
                status_code=503 if len(calls) == 1 else 200,
                content=b"unavailable" if len(calls) == 1 else png("red"),
                headers={"content-type": "image/png"},
            )

    monkeypatch.setattr(guide_images.httpx, "Client", Client)
    url = "https://cards.scryfall.io/normal/front/card.jpg"
    assert guide_images.fetch_card_image("http://127.0.0.1/private") is None
    assert guide_images.fetch_card_image(url) is None
    assert guide_images.fetch_card_image(url)
    assert guide_images.fetch_card_image(url)
    assert len(calls) == 2


def test_very_long_role_explanations_paginate_without_clipping(guide_data):
    guide_data["card_roles"] = [
        dict(
            card_name="Plains",
            quantity=60,
            role_category="Manabase",
            explanation="Decisione corretta e contestualizzata. " * 200,
        )
    ]
    reader = PdfReader(
        BytesIO(
            render_guide_pdf(
                guide_data, "Long primer", "modern", [], {"plains": png("red")}
            )
        )
    )
    assert len(reader.pages) >= 6
    assert (
        sum(p.extract_text().count("Decisione corretta") for p in reader.pages) == 200
    )
