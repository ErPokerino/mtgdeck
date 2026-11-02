import copy
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar
from google import genai
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.config import settings
from app.routers.settings import get_app_setting

T = TypeVar("T", bound=BaseModel)


def dereference_json_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Risolve i riferimenti $ref / $defs generati da Pydantic v2 in un JSON Schema piatto
    perfettamente compatibile con response_format di Gemini API.
    """
    defs = schema.get("$defs") or schema.get("definitions") or {}

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = node["$ref"]
                ref_name = ref_path.split("/")[-1]
                if ref_name in defs:
                    return _resolve(copy.deepcopy(defs[ref_name]))
            cleaned: Dict[str, Any] = {}
            for k, v in node.items():
                if k in ("$defs", "definitions", "title", "default"):
                    continue
                cleaned[k] = _resolve(v)
            return cleaned
        elif isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return _resolve(copy.deepcopy(schema))


class AIProvider(ABC):
    """Interfaccia astratta del Provider AI (Fase 1: Gemini API Key Locale -> Fase 2: GCP Vertex AI Model Garden)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    def get_client(self) -> genai.Client:
        pass

    def resolve_provider_model_id(self, logical_model_id: str) -> str:
        cfg = settings.load_ai_models_config()
        for m in cfg.get("models", []):
            if m.get("id") == logical_model_id:
                pmap = m.get("providerModelMap") or {}
                return pmap.get(self.provider_name, logical_model_id)
        return logical_model_id

    def generate_structured(
        self,
        model_id: str,
        system_instruction: str,
        user_prompt: str,
        response_model: Type[T],
    ) -> T:
        client = self.get_client()
        resolved_model = self.resolve_provider_model_id(model_id)
        clean_schema = dereference_json_schema(response_model.model_json_schema())

        interaction = client.interactions.create(
            model=resolved_model,
            system_instruction=system_instruction,
            input=user_prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": clean_schema,
            },
        )
        raw_text = interaction.output_text
        if not raw_text:
            raise RuntimeError(
                f"Il modello {resolved_model} ha restituito un output vuoto."
            )
        return response_model.model_validate_json(raw_text)


class GeminiDeveloperProvider(AIProvider):
    """Fase 1: Provider per sviluppo locale tramite Gemini API Key salvata nei Settings."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "gemini-api-key"

    def get_client(self) -> genai.Client:
        if not self._api_key:
            raise ValueError(
                "Gemini API Key mancante. Inseriscila nelle Impostazioni (icona ingranaggio in alto a destra)."
            )
        return genai.Client(api_key=self._api_key)


class VertexAIProvider(AIProvider):
    """Fase 2: Provider per deploy su GCP con Vertex AI / Model Garden via ADC."""

    def __init__(self, project: str, location: str) -> None:
        self._project = project
        self._location = location

    @property
    def provider_name(self) -> str:
        return "vertex-ai"

    def get_client(self) -> genai.Client:
        if not self._project:
            raise ValueError(
                "GCP Project ID non configurato per il provider Vertex AI."
            )
        return genai.Client(
            vertexai=True,
            project=self._project,
            location=self._location or "us-central1",
        )


def get_active_ai_provider(db: Session) -> AIProvider:
    """Istanzia il provider AI attivo in base alla configurazione corrente (Fase 1 vs Fase 2)."""
    provider_type = get_app_setting(db, "ai_provider", settings.ai_provider)
    if provider_type == "vertex-ai":
        project = get_app_setting(db, "gcp_project", settings.google_cloud_project)
        location = get_app_setting(db, "gcp_location", settings.google_cloud_location)
        return VertexAIProvider(project=project, location=location)

    api_key = get_app_setting(db, "gemini_api_key", "") or settings.gemini_api_key
    return GeminiDeveloperProvider(api_key=api_key)


def get_skill_model_and_config(
    db: Session, skill_name: str, override_model_id: Optional[str] = None
) -> Dict[str, Any]:
    """Determina il modello da usare per una specifica Skill AI leggendo config/ai-models.json."""
    cfg = settings.load_ai_models_config()
    skill_cfg = cfg.get("skills", {}).get(
        skill_name,
        {"tier": "complex", "promptVersion": "v1", "maxValidationRetries": 2},
    )
    tier = skill_cfg.get("tier", "complex")

    if override_model_id:
        model_id = override_model_id
    elif tier == "simple":
        model_id = (
            cfg.get("tiers", {})
            .get("simple", {})
            .get("defaultModelId", "gemini-3.5-flash-lite")
        )
    else:
        default_complex = (
            cfg.get("tiers", {})
            .get("complex", {})
            .get("defaultModelId", "gemini-3.8-flash")
        )
        model_id = get_app_setting(db, "selected_complex_model_id", default_complex)

    allowed = {
        m["id"]
        for m in cfg.get("models", [])
        if m.get("enabled", True) and m.get("tier") == tier
    }
    if model_id not in allowed:
        raise ValueError("Modello non disponibile per questo tipo di attività.")

    return {
        "model_id": model_id,
        "tier": tier,
        "prompt_version": skill_cfg.get("promptVersion", "v1"),
        "max_retries": int(skill_cfg.get("maxValidationRetries", 2)),
    }
