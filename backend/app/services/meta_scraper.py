import asyncio
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from curl_cffi import requests as creq
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import (
    Card,
    MetaArchetype,
    MetaCardStat,
    MetaMatchup,
    MetaSnapshot,
    SyncLog,
    utcnow,
)
from app.services.deck_validator import (
    export_decklist_formats,
    get_color_combination_label,
    parse_decklist_text,
    resolve_card_by_name,
)
from app.services.scryfall_sync import sort_colors_wubrg


class MetaSyncState:
    def __init__(self) -> None:
        self.status: str = "idle"
        self.message: str = "Pronto"


meta_state = MetaSyncState()

MTGTOP8_FORMAT_CODES = {
    "standard": "ST",
    "pioneer": "PI",
    "modern": "MO",
}

MTGDECKS_FORMAT_PATHS = {
    "standard": "Standard",
    "pioneer": "Pioneer",
    "modern": "Modern",
}

# Mapping semantico tra i nomi degli archetipi MTGDecks e le categorie/alias su MTGTop8
# NOTA: le keyword specifiche (es. greasefang, golgari midrange, green devotion) vengono PRIMA dei colori generici!
ARCHETYPE_KEYWORDS_TO_MTGTOP8: List[Tuple[List[str], List[str]]] = [
    (["greasefang"], ["greasefang parhelion"]),
    (
        ["golgari midrange", "the rock"],
        ["the rock", "golgari control", "golgari aggro"],
    ),
    (["green devotion"], ["devotion to green", "green ramp"]),
    (["mono green", "landfall"], ["mono green", "devotion to green", "green ramp"]),
    (["cauldron"], ["ur aggro", "izzet", "creativity"]),
    (
        ["prowess", "spellementals"],
        ["ur aggro", "izzet prowess", "arclight phoenix", "izzet"],
    ),
    (["elementals"], ["izzet control", "ur aggro", "arclight phoenix"]),
    (
        ["uldaros", "excruciator"],
        ["dimir control", "reanimator", "other - combo", "dimir aggro"],
    ),
    (["ninjas", "frog", "bounce"], ["dimir aggro", "dimir control"]),
    (
        ["eldrazi", "bloodchief", "broodscale", "tron"],
        ["broodscale bloodchief", "eldrazi ramp", "eldrazi aggro", "urzatron"],
    ),
    (["devoted druid", "creature", "company"], ["creatures toolbox", "selesnya aggro"]),
    (
        ["amulet", "titan", "scapeshift", "lumra"],
        ["amulet titan", "lotus field", "valakut"],
    ),
    (["storm", "ruby"], ["ruby storm", "ur storm"]),
    (
        ["affinity", "artifacts"],
        ["affinity", "hardened scales", "jeskai control", "jeskai aggro"],
    ),
    (
        ["esper", "blink", "reanimator"],
        ["blink", "instant reanimator", "reanimator", "esper control"],
    ),
    (["red deck wins", "mono red", "burn"], ["red deck wins", "ur aggro"]),
    (["orzhov", "lifegain"], ["orzhov aggro", "weenie white", "blink"]),
    (["azorius", "uw"], ["uw control", "azorius", "blink"]),
    (["4 color", "5 color", "domain"], ["4/5c", "domain", "omniscience"]),
    (
        ["boros", "energy", "dragons", "equipments", "wildfire"],
        ["boros aggro", "boros control", "boros ponza", "red deck wins"],
    ),
    (["dimir"], ["dimir aggro", "dimir control", "reanimator"]),
    (["izzet"], ["ur aggro", "arclight phoenix", "izzet control", "creativity"]),
    (["golgari"], ["the rock", "golgari control", "golgari aggro", "jund"]),
    (["rakdos", "moonshadow"], ["rakdos aggro", "rakdos sacrifice", "hollow one"]),
    (["jund"], ["jund"]),
    (["jeskai"], ["jeskai control", "jeskai aggro", "affinity"]),
]


def infer_archetype_category(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("control", "uw ", "azorius control", "4 color control")):
        return "control"
    if any(
        k in n
        for k in (
            "combo",
            "storm",
            "greasefang",
            "reanimator",
            "bloodchief",
            "cauldron",
            "titan",
            "scapeshift",
            "lotus",
            "druid",
            "excruciator",
        )
    ):
        return "combo"
    if any(
        k in n
        for k in (
            "ninjas",
            "bounce",
            "blink",
            "frog",
            "spirits",
            "tempo",
            "spellementals",
        )
    ):
        return "tempo"
    if any(
        k in n
        for k in (
            "midrange",
            "golgari",
            "jund",
            "uldaros",
            "elementals",
            "dragons",
            "devotion",
            "tron",
        )
    ):
        return "midrange"
    return "aggro"


def _scrape_mtgdecks_live_sync(format_id: str) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Esegue lo scraping live della tabella metagame da https://mtgdecks.net/{Format}
    usando curl_cffi (impersonate='chrome') per superare il filtro Cloudflare.
    Restituisce (total_decks, lista_archetipi_live).
    """
    path = MTGDECKS_FORMAT_PATHS[format_id]
    url = f"https://mtgdecks.net/{path}"
    resp = creq.get(url, impersonate="chrome", timeout=25)
    if resp.status_code != 200 or len(resp.text) < 20000:
        raise RuntimeError(f"MTGDecks ha restituito status {resp.status_code} su {url}")

    soup = BeautifulSoup(resp.text, "lxml")
    page_text = soup.get_text(" ", strip=True)
    m_tot = re.search(r"(\d+)\s+DECKS\s+SELECTED", page_text, re.I)
    total_decks = int(m_tot.group(1)) if m_tot else 0

    # Rows missing share or winrate are skipped, never filled with plausible defaults:
    # a layout change must surface as a failed sync, not as invented metagame numbers.
    archetypes: List[Dict[str, Any]] = []
    for tr in soup.select("table tr")[1:]:
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 8:
            continue
        name = tds[1].strip()
        if not name or name.lower() in ("rogue", "other"):
            continue

        a_tag = tr.select_one("a[href]")
        href = (
            a_tag["href"]
            if a_tag and a_tag.get("href")
            else f"https://mtgdecks.net/{path}"
        )
        if href.startswith("/"):
            href = f"https://mtgdecks.net{href}"
        slug = href.rstrip("/").split("/")[-1].lower() or re.sub(
            r"[^a-z0-9]+", "-", name.lower()
        ).strip("-")

        # Meta share (es. '10% 9.64%' -> 9.64)
        share_matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", tds[2])
        # Winrate (es. '53%' -> 53.0)
        wr_matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", tds[5])
        if not share_matches or not wr_matches:
            continue
        meta_share_pct = float(share_matches[-1])
        winrate_pct = float(wr_matches[0])
        if not (0 < meta_share_pct <= 100 and 0 <= winrate_pct <= 100):
            continue

        # Tier ('A' -> 1, 'B' -> 2, 'C' -> 3)
        tier_str = tds[4].strip().upper()
        tier = 1 if tier_str == "A" else (2 if tier_str == "B" else 3)

        # Decks count (es. '189' -> 189)
        cnt_matches = re.findall(r"\d+", tds[7].replace(",", ""))
        decks_count = int(cnt_matches[0]) if cnt_matches else 0

        # Colori dalle icone mana (<span class="ms ms-cost ms-b ms-shadow">)
        raw_cols: List[str] = []
        for span in tr.select("span[class*='ms-'], i[class*='ms-']"):
            for cls in span.get("class") or []:
                if cls in ("ms-w", "ms-u", "ms-b", "ms-r", "ms-g"):
                    raw_cols.append(cls[-1].upper())
        colors = sort_colors_wubrg(raw_cols)
        _, color_name = get_color_combination_label(colors)

        archetypes.append(
            {
                "name": name,
                "slug": slug,
                "category": infer_archetype_category(name),
                "tier": tier,
                "colors": colors,
                "color_name": color_name,
                "meta_share_pct": meta_share_pct,
                "winrate_pct": winrate_pct,
                "matches_count": decks_count,
                "source_url": href,
                "key_cards": [],
                "sample_decklists": [],
            }
        )
        if len(archetypes) >= 12:
            break

    share_sum = sum(a["meta_share_pct"] for a in archetypes)
    if len(archetypes) < 5 or not 15 <= share_sum <= 101:
        raise RuntimeError(
            f"Tabella metagame di MTGDecks non riconosciuta ({len(archetypes)} archetipi, "
            f"quote {share_sum:.1f}%): il layout del sito potrebbe essere cambiato."
        )
    return total_decks, archetypes


def _scrape_mtgtop8_live_sync(
    db: Session,
    format_id: str,
    live_archetypes: List[Dict[str, Any]],
) -> List[Tuple[str, float, float, float, float, float, List[Dict[str, Any]]]]:
    """
    Scarica da MTGTop8:
    1) Archetipi e decklist reali (/mtgo?d=...) per popolare sample_decklists e key_cards degli archetipi MTGDecks.
    2) Le carte più giocate del formato (/topcards Maindeck + Sideboard + Lands).
    """
    f_code = MTGTOP8_FORMAT_CODES[format_id]
    fmt_url = f"https://www.mtgtop8.com/format?f={f_code}"
    resp = creq.get(fmt_url, impersonate="chrome", timeout=20)
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # Trova il meta_id corrente dal link topcards
    meta_id = {"ST": "50", "PI": "194", "MO": "54"}.get(f_code, "50")
    tc_links = [a.get("href", "") for a in soup.select("a[href*='topcards']")]
    if tc_links:
        m_meta = re.search(r"meta=(\d+)", tc_links[0])
        if m_meta:
            meta_id = m_meta.group(1)

    # Mappa archetipi MTGTop8: nome_lower -> href
    top8_arch_links: List[Tuple[str, str]] = []
    for a_tag in soup.select("a[href*='archetype?a=']"):
        aname = a_tag.get_text(" ", strip=True)
        ahref = a_tag.get("href", "")
        if aname and ahref:
            top8_arch_links.append((aname.lower(), ahref))

    # Cache per evitare di riscaricare la stessa pagina archetipo di MTGTop8
    # (dtitle, did, pilot, event_name)
    arch_decks_cache: Dict[str, List[Tuple[str, str, str, str]]] = {}

    def _get_top8_decks_for_href(ahref: str) -> List[Tuple[str, str, str, str]]:
        if ahref in arch_decks_cache:
            return arch_decks_cache[ahref]
        url_a = f"https://www.mtgtop8.com/{ahref.lstrip('/')}"
        try:
            ra = creq.get(url_a, impersonate="chrome", timeout=15)
            sa = BeautifulSoup(ra.text, "lxml")
            found_decks: List[Tuple[str, str, str, str]] = []
            for tr in sa.select("tr.hover_tr"):
                tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                da = tr.select_one("a[href*='event?e=']")
                if not da or len(tds) < 4:
                    continue
                dhref = da.get("href", "")
                dtitle = da.get_text(" ", strip=True)
                m_d = re.search(r"d=(\d+)", dhref)
                if m_d and dtitle:
                    pilot = (
                        tds[2] if len(tds) > 2 and tds[2] else f"Player #{m_d.group(1)}"
                    )
                    ev_name = (
                        tds[3]
                        if len(tds) > 3 and tds[3]
                        else f"MTGTop8 {format_id.capitalize()}"
                    )
                    rank = tds[5] if len(tds) > 5 and tds[5] else ""
                    ev_full = f"{ev_name} (#{rank})" if rank else ev_name
                    found_decks.append((dtitle, m_d.group(1), pilot, ev_full))
            arch_decks_cache[ahref] = found_decks
            return found_decks
        except Exception:
            arch_decks_cache[ahref] = []
            return []

    used_deck_ids = set()
    sample_copies: Dict[str, Dict[str, int]] = {}

    for arch in live_archetypes:
        aname_low = arch["name"].lower()
        matched_hrefs: List[str] = []

        # 1. Match semantico prioritario tramite tabella di corrispondenza (keyword specifiche prima!)
        for kw_list, target_list in ARCHETYPE_KEYWORDS_TO_MTGTOP8:
            if any(kw in aname_low for kw in kw_list):
                for target in target_list:
                    for t8_name, t8_href in top8_arch_links:
                        if target in t8_name and t8_href not in matched_hrefs:
                            matched_hrefs.append(t8_href)

        # 2. Match diretto su parole del nome
        for t8_name, t8_href in top8_arch_links:
            if (
                aname_low in t8_name or t8_name in aname_low
            ) and t8_href not in matched_hrefs:
                matched_hrefs.append(t8_href)

        # 3. Fallback sul primo token del nome (es. "Dimir", "Izzet", "Golgari", "Boros")
        first_word = aname_low.split()[0] if aname_low.split() else ""
        if first_word:
            for t8_name, t8_href in top8_arch_links:
                if first_word in t8_name and t8_href not in matched_hrefs:
                    matched_hrefs.append(t8_href)

        # Valuta i candidati e scegli la decklist più fedele a nome/carte chiave/colori dell'archetipo
        best_candidate = None
        best_score = -999

        for mh in matched_hrefs[:3]:
            deck_candidates = _get_top8_decks_for_href(mh)
            for dtitle, did, pilot, ev_full in deck_candidates[:7]:
                if did in used_deck_ids:
                    continue
                try:
                    rd = creq.get(
                        f"https://www.mtgtop8.com/mtgo?d={did}",
                        impersonate="chrome",
                        timeout=12,
                    )
                    if rd.status_code != 200 or len(rd.content) < 100:
                        continue
                    try:
                        raw_deck_str = rd.content.decode("utf-8")
                    except UnicodeDecodeError:
                        raw_deck_str = rd.content.decode("latin-1", errors="replace")

                    entries, unresolved = parse_decklist_text(db, raw_deck_str)
                    legal_entries = [
                        (c, b, q)
                        for c, b, q in entries
                        if getattr(c, f"legality_{format_id}", "not_legal") == "legal"
                    ]
                    main_cnt = sum(q for _, b, q in legal_entries if b == "main")
                    # A reference list must be complete: dropping unknown or no-longer-legal
                    # cards silently produced 56-card "tournament" lists.
                    if unresolved or len(legal_entries) != len(entries) or main_cnt < 60:
                        continue

                    card_names_low = {
                        c.name.lower() for c, b, _ in legal_entries if b == "main"
                    }
                    dtitle_low = dtitle.lower()
                    cand_score = 0

                    # Regole di coerenza archetipo -> carte firma
                    if "greasefang" in aname_low:
                        if any("greasefang" in cn for cn in card_names_low):
                            cand_score += 100
                        else:
                            continue
                    if "cauldron" in aname_low:
                        if any("soul cauldron" in cn for cn in card_names_low):
                            cand_score += 100
                    if "prowess" in aname_low:
                        if any("soul cauldron" in cn for cn in card_names_low):
                            cand_score -= 50
                        if any(
                            k in cn
                            for cn in card_names_low
                            for k in (
                                "swiftspear",
                                "soul-scar",
                                "slickshot",
                                "cori-steel",
                            )
                        ):
                            cand_score += 80
                    if "green devotion" in aname_low:
                        if "simic" in dtitle_low:
                            cand_score -= 60
                        if "devotion to green" in dtitle_low or any(
                            "nykthos" in cn for cn in card_names_low
                        ):
                            cand_score += 90
                    if "golgari midrange" in aname_low:
                        if "the rock" in dtitle_low or any(
                            k in cn
                            for cn in card_names_low
                            for k in ("thoughtseize", "sheoldred", "unholy annex")
                        ):
                            cand_score += 90

                    # Controllo affinità colori
                    deck_cols = set()
                    for c_obj, b_board, _ in legal_entries:
                        if b_board == "main":
                            deck_cols.update(c_obj.colors or [])
                    target_arch_cols = set(arch.get("colors") or [])
                    if target_arch_cols and deck_cols == target_arch_cols:
                        cand_score += 40
                    elif target_arch_cols and target_arch_cols.issubset(deck_cols):
                        cand_score += 15

                    if cand_score > best_score:
                        best_score = cand_score
                        best_candidate = (dtitle, did, pilot, ev_full, legal_entries)
                        if cand_score >= 80:
                            break
                except Exception:
                    continue
            if best_candidate and best_score >= 80:
                break

        if best_candidate:
            dtitle, did, pilot, ev_full, legal_entries = best_candidate
            used_deck_ids.add(did)
            copies = sample_copies.setdefault(arch["name"], {})
            for c_obj, _, qty in legal_entries:
                copies[c_obj.oracle_id] = copies.get(c_obj.oracle_id, 0) + qty
            _, mtgo_text = export_decklist_formats(legal_entries)
            clean_text = "Deck\n" + mtgo_text
            arch["sample_decklists"].append(
                {
                    "name": f"{arch['name']} ({dtitle})",
                    "pilot": pilot,
                    "event": ev_full,
                    "decklist_text": clean_text,
                }
            )

            nonlands = [
                (c, q)
                for c, b, q in legal_entries
                if b == "main" and "land" not in (c.type_line or "").lower()
            ]
            nonlands.sort(
                key=lambda x: (
                    x[1],
                    1 if x[0].rarity in ("mythic", "rare") else 0,
                    x[0].cmc,
                ),
                reverse=True,
            )
            arch["key_cards"] = [c.name for c, _ in nonlands[:5]]

    # Scarica TUTTE le pagine di Top Cards da MTGTop8 (Maindeck con Terre + Sideboard con Terre)
    md_cards: Dict[str, Tuple[float, float]] = {}
    sb_cards: Dict[str, Tuple[float, float]] = {}
    all_cards: Dict[str, Tuple[float, float]] = {}

    def _parse_topcards_rows(html_text: str) -> Dict[str, Tuple[float, float]]:
        out: Dict[str, Tuple[float, float]] = {}
        s_tc = BeautifulSoup(html_text, "lxml")
        for tr in s_tc.select("tr.hover_tr, tr.chosen_tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) >= 3:
                cname = tds[0].strip()
                m_pct = re.search(r"(\d+(?:\.\d+)?)", tds[1])
                m_avg = re.search(r"(\d+(?:\.\d+)?)", tds[2])
                if cname and m_pct and m_avg:
                    out[cname] = (float(m_pct.group(1)), float(m_avg.group(1)))
        return out

    def _fetch_all_topcards_pages(board_mode: str) -> Dict[str, Tuple[float, float]]:
        collected: Dict[str, Tuple[float, float]] = {}
        for page_num in range(1, 25):
            try:
                r_tc = creq.post(
                    "https://www.mtgtop8.com/topcards",
                    data={
                        "data": "1",
                        "format": f_code,
                        f"metagame_sel[{f_code}]": meta_id,
                        "maindeck": board_mode,
                        "lands": "1",
                        "current_page": str(page_num),
                    },
                    impersonate="chrome",
                    timeout=15,
                )
                if r_tc.status_code != 200:
                    break
                page_rows = _parse_topcards_rows(r_tc.text)
                if not page_rows:
                    break
                new_cnt = 0
                for k, v in page_rows.items():
                    if k not in collected:
                        collected[k] = v
                        new_cnt += 1
                if new_cnt == 0:
                    break
            except Exception:
                break
        return collected

    try:
        md_cards = _fetch_all_topcards_pages("MD")
        sb_cards = _fetch_all_topcards_pages("SB")

        r_all = creq.get(
            f"https://www.mtgtop8.com/topcards?f={f_code}&meta={meta_id}",
            impersonate="chrome",
            timeout=15,
        )
        if r_all.status_code == 200:
            all_cards = _parse_topcards_rows(r_all.text)
    except Exception:
        pass

    # Costruisci la lista combinata di TUTTE le carte più giocate del formato
    combined_names: List[str] = []
    for src_dict in (md_cards, sb_cards, all_cards):
        for k in src_dict.keys():
            if k not in combined_names:
                combined_names.append(k)

    # Pre-indicizza le carte legali nel formato per risoluzione ultra-rapida
    leg_col = getattr(Card, f"legality_{format_id}")
    legal_cards_db = db.query(Card).filter(leg_col == "legal").all()
    fast_card_map: Dict[str, Card] = {}
    for c_item in legal_cards_db:
        fast_card_map[c_item.name.lower()] = c_item
        if "//" in c_item.name:
            front_part = c_item.name.split("//")[0].strip().lower()
            if front_part not in fast_card_map:
                fast_card_map[front_part] = c_item

    top_cards_result: List[
        Tuple[str, float, float, float, float, float, List[Dict[str, Any]]]
    ] = []
    seen_oracle_ids = set()
    for cname in combined_names:
        c_key = cname.strip().lower()
        if "/" in c_key and "//" not in c_key:
            c_key_front = c_key.split("/")[0].strip()
        else:
            c_key_front = c_key.split("//")[0].strip()

        card_obj = (
            fast_card_map.get(c_key)
            or fast_card_map.get(c_key_front)
            or resolve_card_by_name(db, cname)
        )
        if not card_obj:
            continue
        if getattr(card_obj, f"legality_{format_id}", "not_legal") != "legal":
            continue
        if card_obj.oracle_id in seen_oracle_ids:
            continue
        seen_oracle_ids.add(card_obj.oracle_id)

        md_pct, md_avg = md_cards.get(cname, (0.0, 0.0))
        sb_pct, sb_avg = sb_cards.get(cname, (0.0, 0.0))
        # MTGTop8's combined page is the only observed overall figure; otherwise the larger
        # board share is a lower bound. No synthetic blend of the two.
        overall_pct = round(all_cards.get(cname, (max(md_pct, sb_pct), 0.0))[0], 1)
        if not md_pct and cname in all_cards:
            md_pct, md_avg = all_cards[cname]

        # Only archetypes whose reference list actually contains the card, with the copies observed.
        playing_archs: List[Dict[str, Any]] = []
        for arch in live_archetypes:
            copies = sample_copies.get(arch["name"], {}).get(card_obj.oracle_id)
            if copies:
                playing_archs.append({"archetype": arch["name"], "sample_copies": copies})

        top_cards_result.append(
            (
                card_obj.name,
                overall_pct,
                md_pct,
                md_avg,
                sb_pct,
                sb_avg,
                playing_archs[:4],
            )
        )

    top_cards_result.sort(key=lambda x: x[1], reverse=True)
    return top_cards_result


def _generate_matchups_from_live_archetypes(
    archetypes: List[Dict[str, Any]],
) -> List[Tuple[str, str, float, int]]:
    """
    Calcola la matrice di matchup tra i top archetipi basandosi sui winrate reali di MTGDecks,
    sul numero di mazzi registrati e sulle dinamiche strutturali tra categorie (aggro/midrange/control/combo/tempo).
    """
    cat_advantage = {
        ("aggro", "control"): 3.2,
        ("aggro", "combo"): 3.8,
        ("aggro", "tempo"): -1.8,
        ("aggro", "midrange"): -2.5,
        ("midrange", "aggro"): 2.5,
        ("midrange", "tempo"): 1.5,
        ("midrange", "control"): -2.8,
        ("midrange", "combo"): -3.5,
        ("control", "midrange"): 2.8,
        ("control", "combo"): 2.2,
        ("control", "aggro"): -3.2,
        ("control", "tempo"): -2.4,
        ("combo", "midrange"): 3.5,
        ("combo", "aggro"): -3.8,
        ("combo", "control"): -2.2,
        ("combo", "tempo"): -3.0,
        ("tempo", "control"): 2.4,
        ("tempo", "combo"): 3.0,
        ("tempo", "aggro"): 1.8,
        ("tempo", "midrange"): -1.5,
    }
    matchups: List[Tuple[str, str, float, int]] = []
    top_n = archetypes[:8]
    for i in range(len(top_n)):
        for j in range(i + 1, len(top_n)):
            a = top_n[i]
            b = top_n[j]
            wr_diff = (a["winrate_pct"] - b["winrate_pct"]) * 0.85
            cat_shift = cat_advantage.get((a["category"], b["category"]), 0.0)
            est_wr = round(max(36.0, min(64.0, 50.0 + wr_diff + cat_shift)), 1)
            est_matches = 0  # Heuristic estimate: no observed head-to-head sample.
            matchups.append((a["name"], b["name"], est_wr, est_matches))
    return matchups


def _run_meta_sync_blocking(format_id: str) -> Dict[str, Any]:
    """Esegue la sincronizzazione live completa (MTGDecks + MTGTop8) in modo sincrono per un formato."""
    fmt = format_id.lower()
    if fmt not in MTGDECKS_FORMAT_PATHS:
        raise ValueError(f"Formato non valido: {format_id}")

    meta_state.status = "running"
    meta_state.message = (
        f"Scraping live {fmt.capitalize()} da MTGDecks.net e MTGTop8.com..."
    )

    db: Session = SessionLocal()
    sync_log = SyncLog(source="mtgdecks+mtgtop8", format_id=fmt, status="running")
    db.add(sync_log)
    db.commit()

    try:
        total_decks, live_archetypes = _scrape_mtgdecks_live_sync(fmt)
        top_cards = _scrape_mtgtop8_live_sync(db, fmt, live_archetypes)
        # Archetypes without a complete reference list keep no key cards rather than
        # borrowing popular cards of matching colours.
        matchups = _generate_matchups_from_live_archetypes(live_archetypes)

        snap = MetaSnapshot(
            format_id=fmt,
            source="MTGDecks.net + MTGTop8.com (Live Synced)",
            fetched_at=utcnow(),
            total_decks_analyzed=total_decks,
            notes=f"Live scraped {len(live_archetypes)} archetypes from MTGDecks and {len(top_cards)} top cards from MTGTop8",
        )
        db.add(snap)
        db.flush()

        for arch in live_archetypes:
            db.add(
                MetaArchetype(
                    snapshot_id=snap.id,
                    format_id=fmt,
                    name=arch["name"],
                    slug=arch["slug"],
                    category=arch["category"],
                    tier=arch["tier"],
                    colors=arch["colors"],
                    color_name=arch["color_name"],
                    meta_share_pct=arch["meta_share_pct"],
                    winrate_pct=arch["winrate_pct"],
                    matches_count=arch["matches_count"],
                    key_cards=arch["key_cards"],
                    sample_decklists=arch["sample_decklists"],
                    source_url=arch["source_url"],
                )
            )

        arch_names = [a["name"] for a in live_archetypes[:8]]
        for name_a in arch_names:
            db.add(
                MetaMatchup(
                    snapshot_id=snap.id,
                    format_id=fmt,
                    archetype_a_name=name_a,
                    archetype_b_name=name_a,
                    winrate_a_pct=50.0,
                    matches_count=0,
                )
            )

        for arch_a, arch_b, wr_a, matches in matchups:
            db.add(
                MetaMatchup(
                    snapshot_id=snap.id,
                    format_id=fmt,
                    archetype_a_name=arch_a,
                    archetype_b_name=arch_b,
                    winrate_a_pct=wr_a,
                    matches_count=matches,
                )
            )
            db.add(
                MetaMatchup(
                    snapshot_id=snap.id,
                    format_id=fmt,
                    archetype_a_name=arch_b,
                    archetype_b_name=arch_a,
                    winrate_a_pct=round(100.0 - wr_a, 1),
                    matches_count=matches,
                )
            )

        for (
            cname,
            overall_pct,
            main_pct,
            main_avg,
            side_pct,
            side_avg,
            top_archs,
        ) in top_cards:
            card_obj: Optional[Card] = resolve_card_by_name(db, cname)
            db.add(
                MetaCardStat(
                    snapshot_id=snap.id,
                    format_id=fmt,
                    card_name=card_obj.name if card_obj else cname,
                    oracle_id=card_obj.oracle_id if card_obj else None,
                    overall_presence_pct=overall_pct,
                    main_presence_pct=main_pct,
                    main_avg_copies=main_avg,
                    side_presence_pct=side_pct,
                    side_avg_copies=side_avg,
                    top_archetypes=top_archs,
                )
            )

        sync_log.status = "completed"
        sync_log.records_processed = len(live_archetypes) + len(top_cards)
        sync_log.completed_at = utcnow()
        db.commit()

        meta_state.status = "completed"
        meta_state.message = (
            f"Meta {fmt.capitalize()} sincronizzato live da MTGDecks & MTGTop8"
        )
        return {
            "status": "completed",
            "format_id": fmt,
            "archetypes_count": len(live_archetypes),
            "top_cards_count": len(top_cards),
        }
    except Exception as exc:
        sync_log.status = "failed"
        sync_log.message = str(exc)
        sync_log.completed_at = utcnow()
        db.commit()
        meta_state.status = "failed"
        meta_state.message = f"Errore sync Meta: {exc}"
        raise
    finally:
        db.close()


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
    for fmt in ("standard", "pioneer", "modern"):
        try:
            await run_meta_sync_for_format(fmt)
        except Exception:
            # Already recorded in SyncLog; one failing format must not block the others.
            logging.getLogger("uvicorn.error").exception("Meta sync %s failed", fmt)
