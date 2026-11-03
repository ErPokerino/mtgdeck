"""Official card artwork for the entire primer, cached only after successful validation."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from urllib.parse import urlparse

import httpx
from PIL import Image
from app.config import DATA_DIR, settings

CACHE_DIR = DATA_DIR / "cache" / "pdf-card-images"
DOUBLE_FACED_LAYOUTS = {
    "transform",
    "modal_dfc",
    "double_faced_token",
    "reversible_card",
}


def image_key(name):
    return str(name).split(" // ")[0].strip().casefold()


def valid_image(raw):
    try:
        with Image.open(BytesIO(raw)) as picture:
            if picture.width * picture.height > 4_000_000:
                return False
            picture.verify()
        return True
    except (OSError, ValueError):
        return False


def fetch_card_image(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cards.scryfall.io":
        return None
    cache = CACHE_DIR / (sha256(url.encode()).hexdigest() + ".img")
    try:
        raw = cache.read_bytes()
        if valid_image(raw):
            return raw
    except OSError:
        pass
    try:
        with httpx.Client(
            timeout=6,
            follow_redirects=False,
            headers={"User-Agent": settings.scryfall_user_agent, "Accept": "image/*"},
        ) as client:
            response = client.get(url)
        raw = response.content
        if (
            response.status_code != 200
            or not response.headers.get("content-type", "").startswith("image/")
            or len(raw) > 2_000_000
            or not valid_image(raw)
        ):
            return None
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(raw)
        except OSError:
            pass  # Artwork can still be embedded when the disk cache is unavailable.
        return raw
    except (httpx.HTTPError, OSError, ValueError):
        return None


def preferred_url(uris):
    return (
        uris.get("normal") or uris.get("large") or uris.get("png") or uris.get("small")
    )


def load_guide_images(cards):
    urls = {}
    for card in cards:
        key = image_key(card.name)
        faces = card.card_faces or []
        front = preferred_url(card.image_uris or {})
        if not front and faces:
            front = preferred_url(faces[0].get("image_uris") or {})
        if front:
            urls[key] = front
        if card.layout in DOUBLE_FACED_LAYOUTS and len(faces) > 1:
            back = preferred_url(faces[1].get("image_uris") or {})
            if back:
                urls[key + "::back"] = back
    # Download each distinct URL once, regardless of its appearances in list, hands and roles.
    unique = list(dict.fromkeys(urls.values()))
    with ThreadPoolExecutor(max_workers=6) as pool:
        downloaded = dict(zip(unique, pool.map(fetch_card_image, unique)))
    return {key: downloaded[url] for key, url in urls.items() if downloaded[url]}
