from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import AppSetting
from app.schemas import SettingsOut, SettingsUpdateIn

router = APIRouter(prefix="/api/settings", tags=["Settings"])


def get_app_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value_json if row and row.value_json is not None else default


def set_app_setting(db: Session, key: str, value: Any) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value_json = value
    else:
        db.add(AppSetting(key=key, value_json=value))
    db.commit()


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:4]}••••••••{key[-4:]}"


@router.get("", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_db)):
    models_cfg: Dict[str, Any] = settings.load_ai_models_config()
    models_list = [m for m in models_cfg.get("models", []) if m.get("enabled", True)]

    default_simple = (
        models_cfg.get("tiers", {})
        .get("simple", {})
        .get("defaultModelId", "gemini-3.5-flash-lite")
    )
    default_complex = (
        models_cfg.get("tiers", {})
        .get("complex", {})
        .get("defaultModelId", "gemini-3.8-flash")
    )

    saved_api_key = get_app_setting(db, "gemini_api_key", "") or settings.gemini_api_key
    saved_complex_model = get_app_setting(
        db, "selected_complex_model_id", default_complex
    )
    saved_provider = get_app_setting(db, "ai_provider", settings.ai_provider)
    saved_gcp_project = get_app_setting(
        db, "gcp_project", settings.google_cloud_project
    )
    saved_gcp_location = get_app_setting(
        db, "gcp_location", settings.google_cloud_location
    )

    # Verifica che il modello selezionato esista ancora nel file di config (es. dopo passaggio da Argon a Carbon)
    valid_model_ids = {m["id"] for m in models_list if m.get("tier") == "complex"}
    if saved_complex_model not in valid_model_ids:
        saved_complex_model = default_complex

    return SettingsOut(
        ai_provider=saved_provider,
        has_gemini_api_key=bool(saved_api_key),
        masked_gemini_api_key=mask_api_key(saved_api_key),
        selected_complex_model_id=saved_complex_model,
        simple_model_id=default_simple,
        available_models=models_list,
        tiers_info=models_cfg.get("tiers", {}),
        skills_config=models_cfg.get("skills", {}),
        gcp_project=saved_gcp_project,
        gcp_location=saved_gcp_location,
    )


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdateIn, db: Session = Depends(get_db)):
    models_cfg = settings.load_ai_models_config()
    models_list = [m for m in models_cfg.get("models", []) if m.get("enabled", True)]
    valid_model_ids = {m["id"] for m in models_list if m.get("tier") == "complex"}

    if payload.gemini_api_key is not None:
        clean_key = payload.gemini_api_key.strip()
        set_app_setting(db, "gemini_api_key", clean_key)

    if payload.selected_complex_model_id is not None:
        if payload.selected_complex_model_id not in valid_model_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Modello '{payload.selected_complex_model_id}' non presente tra i modelli abilitati in config/ai-models.json",
            )
        set_app_setting(
            db, "selected_complex_model_id", payload.selected_complex_model_id
        )

    if payload.ai_provider is not None:
        if payload.ai_provider not in ("gemini-api-key", "vertex-ai"):
            raise HTTPException(
                status_code=400,
                detail="Provider AI non valido ('gemini-api-key' o 'vertex-ai')",
            )
        set_app_setting(db, "ai_provider", payload.ai_provider)

    if payload.gcp_project is not None:
        set_app_setting(db, "gcp_project", payload.gcp_project.strip())

    if payload.gcp_location is not None:
        set_app_setting(db, "gcp_location", payload.gcp_location.strip())

    return read_settings(db)
