export interface HealthStatus {
  status: string
  chat_model: string
  embed_model: string
  grok_ok: boolean
  grok_detail: string
}

export interface IndexSummary {
  path: string
  commit_sha: string
  files: number
  symbols: number
  imports: number
  chunks: number
  entry_points: number
  embed_status: string
  database: string
}

export interface Citation {
  path: string
  start_line: number
  end_line: number
  snippet: string
  reason: string
}

export interface CitationCheck {
  citation: Citation
  supported: boolean
  failures: string[]
  actual_text: string | null
}

export interface AskResult {
  run_id: string
  question: string
  answer: {
    answer: string
    citations: Citation[]
    unknowns: string[]
  }
  grounding: {
    supported: number
    cited: number
    support_rate: number
    checks: CitationCheck[]
  }
  commit_sha: string
}

export interface ChangePlan {
  goal: string
  steps: string[]
  files: string[]
  risks: string[]
  test_command: string
  diff: string
}

export interface PlanResult {
  run_id: string
  request: string
  plan: ChangePlan
  commit_sha: string
}

export interface VerifyResult {
  run_id: string
  verification: {
    passed: boolean
    patch_applied: boolean
    exit_code: number | null
    changed_files: string[]
    planned_files: string[]
    failures: string[]
    stdout: string
    stderr: string
  }
  commit_sha: string
}
