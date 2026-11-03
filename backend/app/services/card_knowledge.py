"""Scryfall rulings and functional Tagger tags, keyed by Oracle identity.

Both come from Scryfall bulk files: they give the AI official rulings instead of
hand-written rule patches, and let the app count interaction (removal, counters,
draw...) deterministically.
"""

import gzip
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set

import orjson
from sqlalchemy.orm import Session

from app.models import CardRuling, CardTag

# Tagger slugs worth tracking for deckbuilding; descendants are folded into each one.
FUNCTIONAL_TAGS = [
    "removal",
    "removal-creature",
    "removal-artifact",
    "removal-enchantment",
    "removal-planeswalker",
    "removal-exile",
    "sweeper",
    "burn",
    "counterspell",
    "draw",
    "card-advantage",
    "cantrip",
    "discard",
    "hate-graveyard",
    "ramp",
    "mana-dork",
    "tutor",
    "lifegain",
    "recursion",
    "reanimate",
    "protection",
    "bounce",
    "sacrifice-outlet",
    "combat-trick",
    "graveyard-fuel",
    "mill",
]


def _jsonl(path: Path) -> Iterable[dict]:
    with gzip.open(path, "rb") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield orjson.loads(line)


def ingest_rulings(db: Session, path: Path) -> int:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for item in _jsonl(path):
        if item.get("oracle_id") and item.get("comment"):
            grouped[item["oracle_id"]].append(
                {
                    "published_at": item.get("published_at"),
                    "source": item.get("source"),
                    "comment": item["comment"],
                }
            )
    rows = [
        {"oracle_id": oid, "rulings": sorted(r, key=lambda x: x["published_at"] or "")}
        for oid, r in grouped.items()
    ]
    db.query(CardRuling).delete()
    for i in range(0, len(rows), 2000):
        db.bulk_insert_mappings(CardRuling, rows[i : i + 2000])
    db.commit()
    return len(rows)


def expand_tags(tags: List[dict], wanted: Iterable[str]) -> Dict[str, Set[str]]:
    """slug -> oracle ids tagged with it or with any descendant tag."""
    by_id = {t["id"]: t for t in tags}
    children: Dict[str, List[str]] = defaultdict(list)
    for t in tags:
        for parent in t.get("parent_ids") or []:
            children[parent].append(t["id"])
    by_slug = {t["slug"]: t for t in tags}

    def collect(tag_id: str, seen: Set[str]) -> Set[str]:
        if tag_id in seen or tag_id not in by_id:
            return set()
        seen.add(tag_id)
        found = {x["oracle_id"] for x in by_id[tag_id].get("taggings") or []}
        for child in children[tag_id]:
            found |= collect(child, seen)
        return found

    return {
        slug: collect(by_slug[slug]["id"], set()) for slug in wanted if slug in by_slug
    }


def ingest_tags(db: Session, path: Path) -> int:
    expanded = expand_tags(list(_jsonl(path)), FUNCTIONAL_TAGS)
    rows = [{"oracle_id": oid, "tag": slug} for slug, oids in expanded.items() for oid in oids]
    db.query(CardTag).delete()
    for i in range(0, len(rows), 5000):
        db.bulk_insert_mappings(CardTag, rows[i : i + 5000])
    db.commit()
    return len(rows)


def tags_for(db: Session, oracle_ids: Iterable[str]) -> Dict[str, List[str]]:
    ids = list(set(oracle_ids))
    result: Dict[str, List[str]] = defaultdict(list)
    if ids:
        for oid, tag in db.query(CardTag.oracle_id, CardTag.tag).filter(
            CardTag.oracle_id.in_(ids)
        ):
            result[oid].append(tag)
    return {oid: sorted(t) for oid, t in result.items()}


def rulings_for(db: Session, oracle_ids: Iterable[str]) -> Dict[str, List[dict]]:
    ids = list(set(oracle_ids))
    if not ids:
        return {}
    return {
        r.oracle_id: r.rulings or []
        for r in db.query(CardRuling).filter(CardRuling.oracle_id.in_(ids))
    }
