import json
from pathlib import Path
from typing import Any, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def code_stamp() -> int:
    """Newest change to the code a server runs: lets the launcher spot a stale server."""
    newest = 0.0
    for root in (ROOT_DIR / "backend", CONFIG_DIR):
        for path in root.rglob("*"):
            if path.suffix in (".py", ".md", ".json") and not {"tests", "__pycache__"} & set(path.parts):
                newest = max(newest, path.stat().st_mtime)
    return int(newest)


class Settings(BaseSettings):
    """Configurazione applicazione (Fase 1 Locale -> Fase 2 GCP Vertex AI)."""

    app_name: str = "MTG Pro AI Workbench API"
    environment: str = "local"  # "local" (Fase 1) | "gcp" (Fase 2)

    # Database: SQLite locale in Fase 1, Cloud SQL PostgreSQL via env in Fase 2
    database_url: str = f"sqlite:///{(DATA_DIR / 'mtgdeck.db').as_posix()}"

    # AI Provider: "gemini-api-key" (Fase 1) | "vertex-ai" (Fase 2)
    ai_provider: str = "gemini-api-key"
    gemini_api_key: str = ""

    # Fase 2: GCP / Vertex AI Model Garden
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    vertex_model_garden_endpoints: str = "{}"  # JSON map opzionale model_id -> endpoint

    # File configurazione modelli AI (non hardcoded)
    ai_models_config_path: str = str(CONFIG_DIR / "ai-models.json")

    # Scryfall rate limit & User-Agent richiesto dalle policy ufficiali Scryfall
    scryfall_user_agent: str = (
        "MTGProAIWorkbench/1.0 (https://github.com/ErPokerino/mtgdeck)"
    )
    scryfall_rate_limit_ms: int = 110

    # Origini browser ammesse oltre a quella che serve l'app (separate da virgola)
    cors_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,"
        "http://127.0.0.1:8090,http://localhost:8090"
    )

    # Metagame da MTGTop8: richieste HTTP normali, identificate e distanziate
    meta_user_agent: str = "AetherdeckWorkbench/1.0 (personal deck analysis)"
    meta_request_delay_ms: int = 700
    meta_lists_per_archetype: int = 15
    meta_min_lists_per_archetype: int = 3
    meta_max_archetypes: int = 25
    meta_coverage_target_pct: float = 90.0
    meta_keep_snapshots: int = 4
    meta_decklist_cache_days: int = 180

    # Sync scheduling
    enable_scheduler: bool = True
    scryfall_sync_interval_hours: int = 24
    meta_sync_interval_hours: int = 12

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def load_ai_models_config(self) -> Dict[str, Any]:
        """Legge dinamicamente il file config/ai-models.json ad ogni richiesta."""
        path = Path(self.ai_models_config_path)
        if not path.exists():
            raise FileNotFoundError(
                f"File configurazione modelli AI non trovato: {path}"
            )
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


settings = Settings()
