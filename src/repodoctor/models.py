from pydantic import BaseModel, Field


class Span(BaseModel):
    path: str
    start_line: int
    end_line: int
    text: str


class SearchHit(BaseModel):
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    text: str
    score: float


class ToolResult(BaseModel):
    tool: str
    summary: str
    spans: list[Span] = Field(default_factory=list)


class ToolEvent(BaseModel):
    seq: int
    tool: str
    args: dict
    result: ToolResult


class Citation(BaseModel):
    path: str
    start_line: int
    end_line: int
    snippet: str
    reason: str


class Answer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class CitationCheck(BaseModel):
    citation: Citation
    supported: bool
    failures: list[str] = Field(default_factory=list)
    actual_text: str | None = None


class GroundingReport(BaseModel):
    supported: int
    cited: int
    support_rate: float
    checks: list[CitationCheck] = Field(default_factory=list)


class ChangePlan(BaseModel):
    goal: str
    steps: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    test_command: str
    diff: str


class Verification(BaseModel):
    passed: bool
    patch_applied: bool
    exit_code: int | None = None
    changed_files: list[str] = Field(default_factory=list)
    planned_files: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


class IndexSummary(BaseModel):
    path: str
    commit_sha: str
    files: int
    symbols: int
    imports: int
    chunks: int
    entry_points: int
    embed_status: str
    database: str


class RepoStatus(BaseModel):
    indexed: bool
    path: str
    commit_sha: str
    summary: IndexSummary | None = None


class AskResult(BaseModel):
    run_id: str
    question: str
    answer: Answer
    grounding: GroundingReport
    commit_sha: str


class PlanResult(BaseModel):
    run_id: str
    request: str
    plan: ChangePlan
    commit_sha: str


class VerifyResult(BaseModel):
    run_id: str
    verification: Verification
    commit_sha: str


class HealthStatus(BaseModel):
    status: str
    chat_model: str
    embed_model: str
    grok_ok: bool
    grok_detail: str


class EvalFixtureResult(BaseModel):
    name: str
    citation_support_rate: float
    expected_path_cited: bool
    sandbox_passed: bool
    failures: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    citation_support_rate: float
    sandbox_pass_rate: float
    fixtures: list[EvalFixtureResult]
