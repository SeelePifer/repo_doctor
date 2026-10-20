from contextlib import asynccontextmanager
from pathlib import Path

import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from repodoctor.config import api_token, chat_model, embed_model, token_required
from repodoctor.grok_model import probe_grok
from repodoctor.errors import ModelError, RepoDoctorError, SandboxError
from repodoctor.indexer import index_repo
from repodoctor.models import AskResult, HealthStatus, IndexSummary, PlanResult, RepoStatus, VerifyResult
from repodoctor.service import ask_question, plan_change, status_for, verify_change


class PathBody(BaseModel):
    path: str


class AskBody(BaseModel):
    path: str
    question: str


class PlanBody(BaseModel):
    path: str
    request: str


class VerifyBody(BaseModel):
    path: str
    run_id: str | None = None
    timeout_seconds: int = Field(default=180, ge=1, le=900)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="RepoDoctor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if not token_required():
        return await call_next(request)
    expected = api_token()
    provided = _presented_token(request)
    if not expected or not secrets.compare_digest(provided, expected):
        return JSONResponse(status_code=401, content={"detail": "Missing or invalid API token."})
    return await call_next(request)


def _presented_token(request: Request) -> str:
    header = request.headers.get("x-repodoctor-token", "")
    if header:
        return header
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


@app.exception_handler(RepoDoctorError)
def handle_repo_error(_request, exc: RepoDoctorError) -> JSONResponse:
    status_code = 503 if isinstance(exc, (ModelError, SandboxError)) else 400
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    ok, detail = probe_grok()
    return HealthStatus(
        status="ok",
        chat_model=chat_model(),
        embed_model=embed_model(),
        grok_ok=ok,
        grok_detail=detail,
    )


@app.get("/repos/status", response_model=RepoStatus)
def repo_status(path: str) -> RepoStatus:
    return status_for(Path(path))


@app.post("/repos/index", response_model=IndexSummary)
def index_repository(body: PathBody) -> IndexSummary:
    return index_repo(Path(body.path), embed=True)


@app.post("/repos/ask", response_model=AskResult)
def ask_repository(body: AskBody) -> AskResult:
    return ask_question(Path(body.path), body.question)


@app.post("/repos/plan", response_model=PlanResult)
def plan_repository(body: PlanBody) -> PlanResult:
    return plan_change(Path(body.path), body.request)


@app.post("/repos/verify", response_model=VerifyResult)
def verify_repository(body: VerifyBody) -> VerifyResult:
    return verify_change(Path(body.path), run_id=body.run_id, timeout_seconds=body.timeout_seconds)
