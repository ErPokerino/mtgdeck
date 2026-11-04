"""Helpers shared by the AI skills."""

import re
from pathlib import Path
from typing import Tuple

from app.models import MetaArchetype

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def archetype_summary(a: MetaArchetype) -> str:
    """Only observed facts: no winrate when the source does not publish one."""
    parts = [
        a.color_name or "colori n/d",
        (a.category or "").upper(),
        f"Tier {a.tier}",
        f"Quota {a.meta_share_pct}%",
    ]
    if a.winrate_pct is not None:
        parts.append(f"WR {a.winrate_pct}%")
    if a.decklists_count:
        parts.append(f"{a.decklists_count} liste analizzate")
    return f"{a.name} ({', '.join(parts)})"


def load_skill_prompt(skill_name: str, version: str = "v1") -> Tuple[str, str]:
    """Carica il file di prompt versionato e restituisce (versione_completa, testo_prompt)."""
    path = PROMPTS_DIR / f"{skill_name}.{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file non trovato: {path}")
    raw = path.read_text(encoding="utf-8")
    ver_match = re.search(r"version:\s*([^\n]+)", raw)
    full_ver = ver_match.group(1).strip() if ver_match else version
    body = re.sub(r"^---\n.*?\n---\n", "", raw, flags=re.DOTALL).strip()
    return full_ver, body
