"""Loopback application. Human UI routes are separate from agent tools."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.datastructures import UploadFile

from shiftproof import __version__
from shiftproof.config import MODEL_LOCK, ROOT, runtime_status
from shiftproof.ingest import ingest_bundle
from shiftproof.models import InputError
from shiftproof.store import Session, StoreError
from shiftproof.worker import Job

ORIGINS = frozenset({"http://127.0.0.1:8000", "http://localhost:8000"})
HOSTS = frozenset({"127.0.0.1:8000", "localhost:8000"})
SLOTS = ("case.json", "volunteers.csv", "shifts.csv", "coverage.csv", "availability.csv")
MAX_BODY = 1_100_000


class BodyTooLarge(Exception):
    pass


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        count = 0

        async def limited():
            nonlocal count
            message = await receive()
            count += len(message.get("body", b""))
            if count > MAX_BODY:
                raise BodyTooLarge()
            return message

        await self.app(scope, limited, send)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseBody(Body):
    case_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class DemoBody(Body):
    variant: Literal["baseline", "cancellation", "infeasible", "injected_note"] = "baseline"


class RunBody(Body):
    request: str = Field(min_length=1, max_length=2000)


class ApplyBody(CaseBody):
    proposal_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    approval_token: str = Field(min_length=16, max_length=256)
    confirm: StrictBool


class ApproveBody(CaseBody):
    result_id: str = Field(min_length=1, max_length=80)
    candidate_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    approval_token: str = Field(min_length=16, max_length=256)


class ExportBody(CaseBody):
    approval_id: str = Field(min_length=1, max_length=80)
    candidate_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def load_demo(variant: str):
    base = ROOT / "fixtures" / "baseline"
    overlay = ROOT / "fixtures" / variant
    files = {slot: (overlay / slot if (overlay / slot).is_file() else base / slot).read_bytes()
             for slot in SLOTS}
    return ingest_bundle(files)


def create_app(*, job_factory=Job, runtime_probe=runtime_status) -> FastAPI:
    sessions: dict[str, Session] = {}
    jobs: dict[str, Job] = {}
    registry_lock = threading.RLock()

    def collect(session: Session) -> None:
        job = jobs.get(session.session_id)
        if not job:
            return
        with session.lock:
            try:
                for message in job.poll():
                    if session.active_run_id != job.run_id:
                        continue
                    if message.get("kind") == "event":
                        event = message.get("event", {})
                        if isinstance(event, dict):
                            event = {key: value for key, value in event.items()
                                     if key in {"type", "tool", "arguments", "status", "result_id", "duration", "detail"}}
                            session.trace.append({"seq": len(session.trace) + 1, **event})
                            session.trace[:] = session.trace[-200:]
                    elif message.get("kind") == "complete":
                        session.finish_run(job.run_id, job.case_hash, message["payload"], job.baseline)
                if job.done:
                    jobs.pop(session.session_id, None)
                    if hasattr(job, "close"):
                        job.close()
            except (ValueError, KeyError, OSError):
                job.cancel()
                jobs.pop(session.session_id, None)
                session.cancel_run()
                session.status = "ERROR"
                session.last_error = "The local worker returned an invalid response."

    @asynccontextmanager
    async def lifespan(app):
        async def reap():
            while True:
                with registry_lock:
                    for session in list(sessions.values()):
                        collect(session)
                await asyncio.sleep(0.2)

        task = asyncio.create_task(reap())
        yield
        task.cancel()
        for job in list(jobs.values()):
            job.cancel()
            if hasattr(job, "close"):
                job.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(BodyLimit)
    app.state.sessions = sessions
    app.state.jobs = jobs

    @app.exception_handler(BodyTooLarge)
    async def body_error(request, exc):
        return JSONResponse({"error": "Input exceeds the upload limit."}, status_code=413)

    @app.exception_handler(StoreError)
    async def store_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=409)

    @app.exception_handler(InputError)
    async def input_error(request, exc):
        return JSONResponse({"error": str(exc), "detail": [v.model_dump() for v in exc.issues]}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"error": "Invalid request fields.",
                             "detail": [{"location": list(e["loc"]), "message": e["msg"]}
                                        for e in exc.errors()]}, status_code=422)

    def require_session(request: Request) -> Session:
        session = sessions.get(request.cookies.get("shiftproof_session", ""))
        if session is None:
            raise StoreError("The local session is unavailable. Reload the page.")
        return session

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.headers.get("host") not in HOSTS:
            return JSONResponse({"error": "Local host required."}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("origin") not in ORIGINS:
                return JSONResponse({"error": "A same-origin local request is required."}, status_code=403)
            session = sessions.get(request.cookies.get("shiftproof_session", ""))
            token = request.headers.get("x-csrf-token", "")
            if not session or not token or not secrets.compare_digest(session.csrf, token):
                return JSONResponse({"error": "Local session verification failed."}, status_code=403)
            try:
                if int(request.headers.get("content-length", "0")) > MAX_BODY:
                    return JSONResponse({"error": "Input exceeds the upload limit."}, status_code=413)
            except ValueError:
                return JSONResponse({"error": "Invalid request size."}, status_code=400)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'",
        })
        return response

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "src" / "shiftproof" / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=ROOT / "src" / "shiftproof" / "static"), name="static")

    @app.get("/api/state")
    async def state(request: Request):
        with registry_lock:
            session = sessions.get(request.cookies.get("shiftproof_session", ""))
            if session is None:
                if len(sessions) >= 32:
                    return JSONResponse({"error": "Local session limit reached. Restart the app."}, status_code=503)
                session = Session()
                sessions[session.session_id] = session
            collect(session)
            view = session.public_state(runtime_probe())
            view["source_kind"] = getattr(session, "source_kind", "none")
            response = JSONResponse(view)
            response.set_cookie("shiftproof_session", session.session_id, httponly=True, samesite="strict")
            return response

    def stop(session: Session) -> None:
        job = jobs.pop(session.session_id, None)
        if job:
            job.cancel()
            if hasattr(job, "close"):
                job.close()
        session.cancel_run()

    @app.post("/api/demo")
    async def demo(request: Request, body: DemoBody):
        case = load_demo(body.variant)
        session = require_session(request)
        with registry_lock:
            stop(session)
            view = session.load_case(case)
            session.source_kind = "synthetic"
            return view

    @app.post("/api/import")
    async def import_case(request: Request):
        form = await request.form(max_files=5, max_fields=0, max_part_size=262144)
        if len(form.multi_items()) != 5 or set(form.keys()) != set(SLOTS):
            raise InputError("Upload exactly the five documented file slots.")
        files = {}
        for slot in SLOTS:
            file = form[slot]
            if not isinstance(file, UploadFile):
                raise InputError("Each input slot must contain a file.")
            value = await file.read(262145)
            if len(value) > 262144:
                raise InputError("Each input file must be at most 256 KiB.")
            files[slot] = value
        case = ingest_bundle(files)
        session = require_session(request)
        with registry_lock:
            stop(session)
            view = session.load_case(case)
            session.source_kind = "uploaded"
            return view

    @app.post("/api/confirm")
    async def confirm(request: Request, body: CaseBody):
        return require_session(request).confirm(body.case_hash)

    @app.post("/api/run")
    async def run(request: Request, body: RunBody):
        session = require_session(request)
        if not body.request.strip() or "\x00" in body.request:
            raise InputError("Enter a scheduling request.")
        with registry_lock, session.lock:
            if not session.case or not session.confirmed:
                raise StoreError("Review and confirm the inputs first.")
            if any(not job.done for job in jobs.values()):
                raise StoreError("A local model run is already active.")
            readiness = runtime_probe()
            if not readiness.get("ready"):
                raise StoreError("The local runtime is not ready. Start scripts/run_local.py.")
            job = job_factory(session.case, session.baseline, body.request, session.worker_context())
            if not session.begin_run(job.run_id):
                job.cancel()
                raise StoreError("A run cannot start in the current state.")
            jobs[session.session_id] = job
            session.trace = []
            session.last_error = None
            return {"run_id": job.run_id, "status": "PLANNING"}

    @app.post("/api/cancel")
    async def cancel(request: Request, body: Body):
        session = require_session(request)
        with registry_lock:
            stop(session)
        return {"status": "CANCELLED"}

    @app.post("/api/proposals/{proposal_id}/apply")
    async def apply(request: Request, proposal_id: str, body: ApplyBody):
        return require_session(request).apply_proposal(proposal_id, body.case_hash,
            body.proposal_hash, body.approval_token, body.confirm)

    @app.post("/api/approve")
    async def approve(request: Request, body: ApproveBody):
        return require_session(request).approve_schedule(body.result_id, body.case_hash,
            body.candidate_hash, body.approval_token)

    @app.post("/api/export")
    async def export(request: Request, body: ExportBody):
        lock = json.loads(MODEL_LOCK.read_text())
        runtime = {"code_version": __version__, "runtime_version": "Strands 1.54.0 / Ollama local",
                   "model_tag": lock["model_id"], "model_digest": lock["digest"]}
        return require_session(request).export_schedule(body.approval_id, body.case_hash,
                                                        body.candidate_hash, runtime)

    @app.post("/api/diagnosis-export")
    async def diagnosis_export(request: Request, body: CaseBody):
        return require_session(request).export_diagnosis(body.case_hash)

    @app.get("/api/artifacts/{artifact_id}")
    async def artifact(request: Request, artifact_id: str):
        name, data = require_session(request).get_artifact(artifact_id)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    return app


app = create_app()
