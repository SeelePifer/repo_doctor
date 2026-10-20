import type { AskResult, HealthStatus, IndexSummary, PlanResult, VerifyResult } from './types'

const apiBase = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init)
  const payload: unknown = await response.json()
  if (!response.ok) {
    const detail =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : 'Request failed'
    throw new Error(detail)
  }
  return payload as T
}

function headers(): Record<string, string> {
  const token = import.meta.env.VITE_API_TOKEN ?? ''
  if (!token) return { 'Content-Type': 'application/json' }
  return { 'Content-Type': 'application/json', 'X-RepoDoctor-Token': token }
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body),
  })
}

export function fetchHealth(): Promise<HealthStatus> {
  return request<HealthStatus>('/health', { headers: headers() })
}

export function indexRepo(path: string): Promise<IndexSummary> {
  return post<IndexSummary>('/repos/index', { path })
}

export function askRepo(path: string, question: string): Promise<AskResult> {
  return post<AskResult>('/repos/ask', { path, question })
}

export function planRepo(path: string, changeRequest: string): Promise<PlanResult> {
  return post<PlanResult>('/repos/plan', { path, request: changeRequest })
}

export function verifyRepo(path: string, runId: string): Promise<VerifyResult> {
  return post<VerifyResult>('/repos/verify', { path, run_id: runId })
}
