"""Durable guide work, real phase reporting and resumable unpublished drafts."""

import hashlib
import json
import logging
import threading
import time

from pydantic import ValidationError
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone

from app.database import SessionLocal
from app.models import AIRun, Deck, DeckCard, GuideJob, GuideVersion, utcnow
from app.skills.schemas import AIDeckGuideRequest
from app.services.ai_provider import (
    get_skill_model_and_config,
    is_transient_provider_error as _is_provider_failure,
)
from app.services.guide_pipeline import GUIDE_BUDGET_SECONDS, REVIEW_NOT_CONCLUDED

# Once the review has closed, only local work is left: it must not time out a verified guide.
_AFTER_REVIEW_PHASES = ("weighted_estimate", "ready_to_save", "save")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="guide")
_lock = threading.Lock()
_workers = set()


def public_job(job):
    def stamp(value):
        return (
            value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        ).isoformat()

    return {
        "id": job.id,
        "deck_id": job.deck_id,
        "format_id": job.format_id,
        "deck_name": job.request_json.get("deck_name"),
        "model_id": job.request_json.get("model_id"),
        "status": job.status,
        "phase": job.phase,
        "has_draft": bool(job.draft_json),
        "error": job.error,
        "created_at": stamp(job.created_at),
        "updated_at": stamp(job.updated_at),
        "budget_seconds": GUIDE_BUDGET_SECONDS,
        "result": job.result_json if job.status == "completed" else None,
    }


def recover_interrupted_jobs(db):
    for job in db.query(GuideJob).filter(GuideJob.status.in_(["running", "queued"])):
        job.status, job.error = (
            "failed",
            "Il backend è stato riavviato. Puoi riprendere la bozza conservata.",
        )
        job.finished_at = utcnow()
    db.commit()


def legacy_drafts(db, fmt):
    results = []
    for run in (
        db.query(AIRun)
        .filter_by(skill_name="deck_guide", format_id=fmt)
        .order_by(AIRun.id.desc())
        .limit(20)
    ):
        data = run.output_json or {}
        deck = db.get(Deck, run.deck_id) if run.deck_id else None
        start = run.created_at - timedelta(milliseconds=run.duration_ms)
        if (
            data.get("status") == "failed"
            and data.get("draft")
            and deck
            and deck.updated_at <= start
        ):
            if (
                db.query(GuideVersion)
                .filter(
                    GuideVersion.deck_id == deck.id,
                    GuideVersion.created_at >= run.created_at,
                )
                .first()
            ):
                continue
            results.append(
                {"run_id": run.id, "deck_id": deck.id, "deck_name": deck.name}
            )
    return results


def create_job(db, req, resume_id=None, legacy_run_id=None, draft=None):
    if req.deck_id:
        deck = db.get(Deck, req.deck_id)
        if not deck or deck.format_id != req.format_id:
            raise ValueError("Seleziona un mazzo del formato corrente.")
    req = req.model_copy(
        update={
            "model_id": get_skill_model_and_config(db, "deck_guide", req.model_id)[
                "model_id"
            ]
        }
    )
    signature = None
    if resume_id:
        source = db.get(GuideJob, resume_id)
        if (
            not source
            or source.status not in ("failed", "cancelled")
            or not source.draft_json
        ):
            raise ValueError("La bozza non è disponibile per la ripresa.")
        if source.request_json != req.model_dump():
            raise ValueError(
                "Riprendi con la stessa lista e lo stesso modello, oppure avvia una nuova guida."
            )
        draft, signature = source.draft_json, source.signature
    if legacy_run_id:
        allowed = next(
            (
                r
                for r in legacy_drafts(db, req.format_id)
                if r["run_id"] == legacy_run_id and r["deck_id"] == req.deck_id
            ),
            None,
        )
        run = db.get(AIRun, legacy_run_id)
        if not allowed or run.model_id != req.model_id:
            raise ValueError(
                "Questa bozza non corrisponde più alla lista o al modello selezionato."
            )
        draft = run.output_json["draft"]
    with _lock:
        existing = (
            db.query(GuideJob).filter(GuideJob.status.in_(["queued", "running"])).all()
        )
        for job in existing:
            if job.request_json == req.model_dump():
                return public_job(job)
        if len(_workers) >= 2:
            raise ValueError(
                "Sono già in corso due analisi. Attendi il completamento o l’annullamento."
            )
        job = GuideJob(
            format_id=req.format_id,
            deck_id=req.deck_id,
            request_json=req.model_dump(),
            draft_json=draft,
            signature=signature,
        )
        db.add(job)
        db.commit()
        result = public_job(job)
        _workers.add(job.id)
        _executor.submit(_work, job.id)
        return result


def _work(job_id):
    from app.skills.runner import run_deck_guide_skill

    started = time.monotonic()
    try:
        with SessionLocal() as db:
            job = db.get(GuideJob, job_id)
            if job.status == "cancelled":
                return
            req = AIDeckGuideRequest.model_validate(job.request_json)
            draft, signature = job.draft_json, job.signature
            job.status = "running"
            db.commit()

        def progress(trace):
            with SessionLocal() as status_db:
                current = status_db.get(GuideJob, job_id)
                cancelled = current.status == "cancelled"
                if not cancelled:
                    current.phase = trace["phase"]
                if trace.get("draft"):
                    current.draft_json = trace["draft"]
                current.signature = trace.get("signature", current.signature)
                current.updated_at = utcnow()
                status_db.commit()
                if cancelled:
                    raise ValueError("Generazione annullata.")
                if (
                    trace["phase"] not in _AFTER_REVIEW_PHASES
                    and time.monotonic() - started >= GUIDE_BUDGET_SECONDS
                ):
                    raise TimeoutError("Tempo massimo della guida raggiunto")
                if trace["phase"] == "ready_to_save" and req.deck_id:
                    deck = status_db.get(Deck, req.deck_id)
                    cards = (
                        status_db.query(DeckCard).filter_by(deck_id=req.deck_id).all()
                    )
                    actual = hashlib.sha256(
                        json.dumps(
                            [
                                deck.format_id if deck else None,
                                trace["model_id"],
                                sorted(
                                    (c.oracle_id, c.board, c.quantity) for c in cards
                                ),
                            ]
                        ).encode()
                    ).hexdigest()
                    if actual != trace["signature"]:
                        raise ValueError(
                            "La lista è cambiata durante l’analisi. La bozza è conservata; genera una guida sulla nuova lista."
                        )

        with SessionLocal() as db:
            result = run_deck_guide_skill(
                db,
                req,
                progress=progress,
                resume_draft=draft,
                expected_signature=signature,
                job_id=job_id,
            )
        with SessionLocal() as db:
            job = db.get(GuideJob, job_id)
            job.status, job.phase, job.result_json = "completed", "completed", result
            job.finished_at = utcnow()
            db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            job = db.get(GuideJob, job_id)
            if job.status != "cancelled":
                job.status = "failed"
                if isinstance(exc, ValidationError):
                    job.error = "Il provider ha restituito una risposta incompleta. La bozza già ricevuta resta disponibile per un nuovo tentativo di revisione."
                elif isinstance(exc, ValueError) and str(exc).startswith(
                    REVIEW_NOT_CONCLUDED
                ):
                    detail = str(exc).removeprefix(REVIEW_NOT_CONCLUDED).strip()
                    job.error = (
                        f"La revisione non si è conclusa ({detail}): la guida non è stata "
                        "pubblicata. Riprendi la revisione della bozza senza rigenerare il testo."
                    )
                elif isinstance(exc, ValueError) and str(exc).startswith(
                    (
                        "La lista",
                        "Il mazzo",
                        "Sincronizza",
                        "Legalità",
                        "Correggi",
                        "Generazione annullata",
                    )
                ):
                    job.error = str(exc)
                elif _is_provider_failure(exc):
                    job.error = "Il provider non ha completato la risposta nel tempo disponibile. Puoi riprovare dalla bozza, se già ricevuta."
                else:
                    logging.getLogger("uvicorn.error").exception(
                        "guide job %s failed with an internal error", job_id
                    )
                    job.error = f"Errore interno ({type(exc).__name__}): la bozza già ricevuta resta disponibile. Dettagli nei log del backend."
                job.finished_at = utcnow()
                db.commit()
    finally:
        with _lock:
            _workers.discard(job_id)
