import json
import os
from pathlib import Path
from typing import Any, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR.mkdir(parents=True, exist_ok=True)


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
