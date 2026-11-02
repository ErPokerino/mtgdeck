import asyncio
import gzip
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import orjson
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.config import DATA_DIR, settings
from app.database import SessionLocal, engine, init_fts5_index, is_sqlite
from app.models import Card, Format, SetModel, SyncLog, utcnow

WUBRG_ORDER = {"W": 0, "U": 1, "B": 2, "R": 3, "G": 4}

BASIC_LAND_NAMES = {
    "plains",
    "island",
    "swamp",
    "mountain",
    "forest",
    "wastes",
    "snow-covered plains",
    "snow-covered island",
    "snow-covered swamp",
    "snow-covered mountain",
    "snow-covered forest",
    "snow-covered wastes",
}


class ScryfallSyncState:
    def __init__(self) -> None:
        self.status: str = "idle"  # "idle" | "running" | "completed" | "failed"
        self.progress_pct: float = 0.0
        self.message: str = "Pronto per la sincronizzazione"
        self.last_sync: Optional[datetime] = None


scryfall_state = ScryfallSyncState()


def normalize_card_name(name: str) -> str:
    """Normalizza il nome della carta rimuovendo accenti e spazi superflui per lookup rapidi."""
    nfkd = unicodedata.normalize("NFKD", name or "")
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", ascii_str.strip().lower())


def sort_colors_wubrg(colors: List[str]) -> List[str]:
    return sorted(set(colors or []), key=lambda c: WUBRG_ORDER.get(c, 99))


def parse_numeric_stat(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def detect_max_copies(
    name: str, type_line: str, oracle_text: str
) -> tuple[Optional[int], bool]:
    norm_name = normalize_card_name(name)
    tl_lower = (type_line or "").lower()
    ot_lower = (oracle_text or "").lower()

    is_basic = "basic land" in tl_lower or norm_name in BASIC_LAND_NAMES
    if is_basic:
        return None, True
    if "a deck can have any number of cards named" in ot_lower:
        return None, False
    if "a deck can have up to seven cards named" in ot_lower:
        return 7, False
    if "a deck can have up to nine cards named" in ot_lower:
        return 9, False
    return 4, False


def ensure_default_formats(db: Session) -> None:
    formats_data = [
        {
            "id": "standard",
            "name": "Standard",
            "description": "Formato rotativo competitivo costruito con i set principali degli ultimi 3 anni (60 carte Mainboard, 15 Sideboard).",
        },
        {
            "id": "pioneer",
            "name": "Pioneer",
            "description": "Formato eterno non-rotativo a partire da Return to Ravnica in avanti, senza fetchland classiche.",
        },
        {
            "id": "modern",
            "name": "Modern",
            "description": "Formato competitivo ad alta potenza dall'Ottava Edizione / Mirrodin più i set Modern Horizons.",
        },
    ]
    for fmt in formats_data:
        existing = db.query(Format).filter(Format.id == fmt["id"]).first()
        if not existing:
            db.add(Format(**fmt))
    db.commit()


def extract_card_record(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Trasforma un oggetto carta raw di Scryfall nel dizionario pronto per l'inserimento SQL."""
    oracle_id = raw.get("oracle_id")
    name = raw.get("name")
    if not oracle_id or not name:
        return None

    # Scarta token puri, carte art_series, planar, vanguard o scheme non giocabili in costruito
    layout = raw.get("layout", "normal")
    if layout in {
        "art_series",
        "token",
        "double_faced_token",
        "emblem",
        "planar",
        "scheme",
        "vanguard",
    }:
        return None

    card_faces_raw = raw.get("card_faces") or []
    card_faces: List[Dict[str, Any]] = []
    for face in card_faces_raw:
        card_faces.append(
            {
                "name": face.get("name", ""),
                "mana_cost": face.get("mana_cost", ""),
                "type_line": face.get("type_line", ""),
                "oracle_text": face.get("oracle_text", ""),
                "power": face.get("power"),
                "toughness": face.get("toughness"),
                "loyalty": face.get("loyalty"),
                "defense": face.get("defense"),
                "colors": face.get("colors") or [],
                "image_uris": face.get("image_uris") or {},
            }
        )

    # Gestione carte DFC (Transform / Modal DFC) dove image_uris o mana_cost sono sulla prima faccia
    image_uris = raw.get("image_uris") or {}
    if not image_uris and card_faces and card_faces[0].get("image_uris"):
        image_uris = {
            **card_faces[0]["image_uris"],
            "back_face": card_faces[1].get("image_uris", {})
            if len(card_faces) > 1
            else {},
        }

    mana_cost = raw.get("mana_cost")
    if not mana_cost and card_faces:
        face_costs = [f.get("mana_cost") for f in card_faces if f.get("mana_cost")]
        mana_cost = " // ".join(face_costs) if face_costs else ""

    oracle_text = raw.get("oracle_text")
    if not oracle_text and card_faces:
        face_texts = [f.get("oracle_text") for f in card_faces if f.get("oracle_text")]
        oracle_text = "\n//\n".join(face_texts)
    oracle_text = oracle_text or ""

    type_line = raw.get("type_line") or ""
    if not type_line and card_faces:
        face_types = [f.get("type_line") for f in card_faces if f.get("type_line")]
        type_line = " // ".join(face_types)

    colors = raw.get("colors")
    if colors is None and card_faces:
        merged_colors: List[str] = []
        for f in card_faces:
            merged_colors.extend(f.get("colors") or [])
        colors = sort_colors_wubrg(merged_colors)
    else:
        colors = sort_colors_wubrg(colors or [])

    color_identity = sort_colors_wubrg(raw.get("color_identity") or [])

    power = raw.get("power")
    toughness = raw.get("toughness")
    loyalty = raw.get("loyalty")
    defense = raw.get("defense")
    if card_faces:
        if power is None:
            power = card_faces[0].get("power")
        if toughness is None:
            toughness = card_faces[0].get("toughness")
        if loyalty is None:
            loyalty = card_faces[0].get("loyalty")
        if defense is None:
            defense = card_faces[0].get("defense")

    legalities = raw.get("legalities") or {}
    leg_standard = legalities.get("standard", "not_legal")
    leg_pioneer = legalities.get("pioneer", "not_legal")
    leg_modern = legalities.get("modern", "not_legal")

    max_copies, is_basic_land = detect_max_copies(name, type_line, oracle_text)
    now_iso = datetime.now(timezone.utc)

    return {
        "oracle_id": oracle_id,
        "scryfall_id": raw.get("id", oracle_id),
        "name": name,
        "normalized_name": normalize_card_name(name),
        "layout": layout,
        "mana_cost": mana_cost or "",
        "cmc": float(raw.get("cmc") or 0.0),
        "colors": colors,
        "color_key": "".join(colors),
        "color_identity": color_identity,
        "color_identity_key": "".join(color_identity),
        "type_line": type_line,
        "oracle_text": oracle_text,
        "power": power,
        "power_num": parse_numeric_stat(power),
        "toughness": toughness,
        "toughness_num": parse_numeric_stat(toughness),
        "loyalty": loyalty,
        "defense": defense,
        "rarity": raw.get("rarity", "common"),
        "set_code": (raw.get("set") or "").lower(),
        "set_name": raw.get("set_name") or "",
        "collector_number": str(raw.get("collector_number") or ""),
        "released_at": raw.get("released_at") or "",
        "arena_id": raw.get("arena_id"),
        "mtgo_id": raw.get("mtgo_id"),
        "image_uris": image_uris,
        "card_faces": card_faces,
        "keywords": raw.get("keywords") or [],
        "produced_mana": raw.get("produced_mana") or [],
        "prices": raw.get("prices") or {},
        "max_copies": max_copies,
        "is_basic_land": is_basic_land,
        "legality_standard": leg_standard,
        "legality_pioneer": leg_pioneer,
        "legality_modern": leg_modern,
        "legalities_json": legalities,
        "updated_at": now_iso,
    }


async def run_scryfall_sync(force_download: bool = False) -> Dict[str, Any]:
    """
    Sincronizza l'intero catalogo Scryfall (Sets + Oracle Cards + FTS5 + Legalità Formati).
    Rispetta i rate limit Scryfall (User-Agent e >=110ms delay tra chiamate API).
    """
    if scryfall_state.status == "running":
        return {"status": "already_running", "message": scryfall_state.message}

    scryfall_state.status = "running"
    scryfall_state.progress_pct = 2.0
    scryfall_state.message = "Connessione a Scryfall API..."

    db = SessionLocal()
    sync_log = SyncLog(
        source="scryfall", status="running", message="Avvio sync Scryfall completo"
    )
    db.add(sync_log)
    db.commit()
    db.refresh(sync_log)

    headers = {
        "User-Agent": settings.scryfall_user_agent,
        "Accept": "application/json",
    }

    try:
        ensure_default_formats(db)
        init_fts5_index()

        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(120.0, connect=30.0),
            follow_redirects=True,
        ) as client:
            # 1. Scarica tutti i Set da Scryfall
            scryfall_state.progress_pct = 5.0
            scryfall_state.message = (
                "Scaricamento elenco Set ufficiali da Scryfall (/sets)..."
            )
            sets_resp = await client.get("https://api.scryfall.com/sets")
            sets_resp.raise_for_status()
            sets_payload = sets_resp.json().get("data", [])

            await asyncio.sleep(settings.scryfall_rate_limit_ms / 1000.0)

            existing_sets = {s.code: s for s in db.query(SetModel).all()}
            for s_raw in sets_payload:
                code = (s_raw.get("code") or "").lower()
                if not code:
                    continue
                if code in existing_sets:
                    s_obj = existing_sets[code]
                    s_obj.name = s_raw.get("name", code)
                    s_obj.set_type = s_raw.get("set_type", "expansion")
                    s_obj.released_at = s_raw.get("released_at")
                    s_obj.card_count = s_raw.get("card_count", 0)
                    s_obj.digital = bool(s_raw.get("digital", False))
                    s_obj.icon_svg_uri = s_raw.get("icon_svg_uri")
                else:
                    db.add(
                        SetModel(
                            code=code,
                            name=s_raw.get("name", code),
                            set_type=s_raw.get("set_type", "expansion"),
                            released_at=s_raw.get("released_at"),
                            card_count=s_raw.get("card_count", 0),
                            digital=bool(s_raw.get("digital", False)),
                            icon_svg_uri=s_raw.get("icon_svg_uri"),
                        )
                    )
            db.commit()

            # 2. Ottieni metadati Bulk Data (/bulk-data -> type == "oracle_cards")
            scryfall_state.progress_pct = 10.0
            scryfall_state.message = (
                "Verifica metadati Scryfall Bulk Data (/bulk-data)..."
            )
            bulk_resp = await client.get("https://api.scryfall.com/bulk-data")
            bulk_resp.raise_for_status()
            bulk_payload = bulk_resp.json()
            bulk_items = bulk_payload.get("data", [])
            bulk_info = next(
                (item for item in bulk_items if item.get("type") == "oracle_cards"),
                bulk_items[0] if bulk_items else bulk_payload,
            )
            download_uri = bulk_info.get("jsonl_download_uri") or bulk_info.get(
                "download_uri"
            )
            if not download_uri:
                raise RuntimeError(
                    f"Nessun URI di download trovato in Scryfall bulk_data: {list(bulk_info.keys())}"
                )
            expected_size = int(
                bulk_info.get("compressed_size") or bulk_info.get("size") or 25_000_000
            )

            ext = ".jsonl.gz" if download_uri.endswith(".jsonl.gz") else ".json"
            bulk_file_path: Path = DATA_DIR / f"scryfall_oracle_cards{ext}"
            need_download = force_download or not bulk_file_path.exists()
            if bulk_file_path.exists() and not force_download:
                # Se il file ha meno di 20 ore ed è >10MB, usiamo la cache su disco
                age_hours = (time.time() - bulk_file_path.stat().st_mtime) / 3600.0
                if age_hours < 20 and bulk_file_path.stat().st_size > 10_000_000:
                    need_download = False
                else:
                    need_download = True

            if need_download:
                scryfall_state.progress_pct = 12.0
                scryfall_state.message = (
                    "Download catalogo completo Scryfall (oracle-cards)..."
                )
                downloaded_bytes = 0
                tmp_path = DATA_DIR / f"scryfall_oracle_cards{ext}.part"
                async with client.stream("GET", download_uri) as stream_resp:
                    stream_resp.raise_for_status()
                    with open(tmp_path, "wb") as f_out:
                        async for chunk in stream_resp.aiter_bytes(
                            chunk_size=1024 * 256
                        ):
                            f_out.write(chunk)
                            downloaded_bytes += len(chunk)
                            dl_ratio = min(
                                1.0, downloaded_bytes / max(1, expected_size)
                            )
                            scryfall_state.progress_pct = round(
                                12.0 + dl_ratio * 48.0, 1
                            )
                            mb_done = downloaded_bytes / (1024 * 1024)
                            mb_tot = expected_size / (1024 * 1024)
                            scryfall_state.message = f"Scaricamento Scryfall Bulk Data: {mb_done:.1f} / {mb_tot:.1f} MB..."
                if bulk_file_path.exists():
                    bulk_file_path.unlink()
                tmp_path.rename(bulk_file_path)

        # 3. Parsing veloce con orjson e popolamento DB + FTS5 in un thread dedicato per non bloccare l'event loop
        scryfall_state.progress_pct = 62.0
        scryfall_state.message = "Lettura e parsing JSON completo Scryfall in corso..."

        total_inserted = await asyncio.to_thread(_ingest_bulk_file_sync, bulk_file_path)

        now_dt = utcnow()
        sync_log.status = "completed"
        sync_log.records_processed = total_inserted
        sync_log.message = (
            f"Sincronizzate {total_inserted} carte e aggiornato indice FTS5."
        )
        sync_log.completed_at = now_dt
        db.commit()

        scryfall_state.status = "completed"
        scryfall_state.progress_pct = 100.0
        scryfall_state.last_sync = now_dt
        scryfall_state.message = (
            f"Catalogo Scryfall aggiornato ({total_inserted:,} carte indicizzate)"
        )

        return {
            "status": "completed",
            "cards_processed": total_inserted,
            "completed_at": now_dt.isoformat(),
        }

    except Exception as exc:
        sync_log.status = "failed"
        sync_log.message = str(exc)
        sync_log.completed_at = utcnow()
        db.commit()

        scryfall_state.status = "failed"
        scryfall_state.message = f"Errore sync Scryfall: {exc}"
        raise
    finally:
        db.close()


def _ingest_bulk_file_sync(bulk_file_path: Path) -> int:
    """Esegue il bulk upsert su SQLite e ricostruisce l'indice FTS5 e le legalità dei Set."""
    records: List[Dict[str, Any]] = []
    set_counts: Dict[str, Dict[str, int]] = {}

    def _track_set_legality(rec: Dict[str, Any]) -> None:
        scode = rec["set_code"]
        bucket = set_counts.setdefault(
            scode, {"total": 0, "std": 0, "pio": 0, "mod": 0}
        )
        bucket["total"] += 1
        if rec["legality_standard"] in ("legal", "Banned", "banned"):
            bucket["std"] += 1
        if rec["legality_pioneer"] in ("legal", "Banned", "banned"):
            bucket["pio"] += 1
        if rec["legality_modern"] in ("legal", "Banned", "banned"):
            bucket["mod"] += 1

    if bulk_file_path.name.endswith(".jsonl.gz"):
        with open(bulk_file_path, "rb") as f_probe:
            magic = f_probe.read(2)
        is_gzipped = magic == b"\x1f\x8b"
        opener = gzip.open if is_gzipped else open

        idx = 0
        with opener(bulk_file_path, "rb") as f_in:
            for line in f_in:
                line = line.strip()
                if not line:
                    continue
                raw = orjson.loads(line)
                rec = extract_card_record(raw)
                if rec is not None:
                    records.append(rec)
                    _track_set_legality(rec)
                idx += 1
                if idx % 5000 == 0:
                    scryfall_state.progress_pct = round(
                        min(80.0, 64.0 + (idx / 36000.0) * 16.0), 1
                    )
                    scryfall_state.message = (
                        f"Elaborazione carte Scryfall: {idx:,} lette..."
                    )
    else:
        with open(bulk_file_path, "rb") as f:
            raw_cards: List[Dict[str, Any]] = orjson.loads(f.read())

        total_raw = len(raw_cards)
        for idx, raw in enumerate(raw_cards):
            rec = extract_card_record(raw)
            if rec is not None:
                records.append(rec)
                _track_set_legality(rec)
            if idx % 5000 == 0 and total_raw > 0:
                scryfall_state.progress_pct = round(64.0 + (idx / total_raw) * 16.0, 1)
                scryfall_state.message = (
                    f"Elaborazione carte Scryfall: {idx:,} / {total_raw:,}..."
                )

    scryfall_state.progress_pct = 82.0
    scryfall_state.message = (
        f"Salvataggio di {len(records):,} carte nel database locale..."
    )

    db = SessionLocal()
    try:
        # Upsert preserves deck foreign keys and keeps constraints enabled on every connection.
        # Absent identities remain available to historic lists but lose format legality.
        if not records:
            raise ValueError("Catalogo Scryfall vuoto: sincronizzazione annullata")
        db.query(Card).update(
            {
                Card.legality_standard: "not_legal",
                Card.legality_pioneer: "not_legal",
                Card.legality_modern: "not_legal",
            }
        )
        if is_sqlite:
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        batch_size = 200
        for i in range(0, len(records), batch_size):
            chunk = records[i : i + batch_size]
            stmt = insert(Card).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["oracle_id"],
                set_={
                    k: getattr(stmt.excluded, k) for k in chunk[0] if k != "oracle_id"
                },
            )
            db.execute(stmt)
            scryfall_state.progress_pct = round(
                82.0 + (i / max(1, len(records))) * 12.0, 1
            )

        # Aggiorna i flag di legalità sui Set principali (expansion, core, draft_innovation)
        all_sets = db.query(SetModel).all()
        for s in all_sets:
            counts = set_counts.get(s.code, {"total": 0, "std": 0, "pio": 0, "mod": 0})
            tot = max(1, counts["total"])
            if not s.digital and counts["total"] >= 15:
                s.is_standard_legal = (
                    s.set_type in {"expansion", "core"} and (counts["std"] / tot) >= 0.5
                )
                s.is_pioneer_legal = (
                    s.set_type in {"expansion", "core"} and (counts["pio"] / tot) >= 0.5
                )
                s.is_modern_legal = (
                    s.set_type in {"expansion", "core", "draft_innovation"}
                    and (counts["mod"] / tot) >= 0.5
                )
            else:
                s.is_standard_legal = False
                s.is_pioneer_legal = False
                s.is_modern_legal = False

        if is_sqlite:
            scryfall_state.progress_pct = 95.0
            scryfall_state.message = "Ricostruzione indice Full-Text Search (FTS5)..."
            db.execute(text("DELETE FROM cards_fts"))
            db.execute(
                text(
                    """
                    INSERT INTO cards_fts (oracle_id, name, type_line, oracle_text)
                    SELECT oracle_id, name, type_line, COALESCE(oracle_text, '')
                    FROM cards
                    """
                )
            )
        db.commit()

        return len(records)
    finally:
        db.close()
