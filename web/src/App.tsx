import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { askRepo, fetchHealth, indexRepo, planRepo, verifyRepo } from './api'
import { Badge } from './components/ui/badge'
import { Button } from './components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './components/ui/card'
import { Input } from './components/ui/input'
import { Textarea } from './components/ui/textarea'
import type { AskResult, IndexSummary, PlanResult, VerifyResult } from './types'

export function App() {
  const [repoPath, setRepoPath] = useState('')
  const [question, setQuestion] = useState('')
  const [changeRequest, setChangeRequest] = useState('')
  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth })
  const index = useMutation({ mutationFn: () => indexRepo(repoPath.trim()) })
  const ask = useMutation({ mutationFn: () => askRepo(repoPath.trim(), question.trim()) })
  const plan = useMutation({ mutationFn: () => planRepo(repoPath.trim(), changeRequest.trim()) })
  const verify = useMutation({
    mutationFn: () => verifyRepo(repoPath.trim(), plan.data?.run_id ?? ''),
  })

  return (
    <main className='mx-auto min-h-screen max-w-5xl px-4 py-8 text-zinc-900'>
      <header className='mb-8 flex flex-wrap items-end justify-between gap-3'>
        <div>
          <p className='text-sm font-medium text-zinc-500'>RepoDoctor</p>
          <h1 className='text-3xl font-semibold tracking-tight'>Answers that have to cite the code</h1>
          <p className='mt-2 max-w-2xl text-sm text-zinc-600'>
            Index a git repository, ask a question, and check every citation against the real lines.
            A change plan is scored only after Docker runs its tests.
          </p>
        </div>
        <HealthBadge ok={health.data?.grok_ok} detail={health.data?.grok_detail} loading={health.isLoading} />
      </header>

      <div className='space-y-6'>
        <Card>
          <CardHeader>
            <CardTitle>Repository</CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            <label className='block text-sm font-medium' htmlFor='repo-path'>
              Path on this machine
            </label>
            <div className='flex flex-col gap-2 sm:flex-row'>
              <Input
                id='repo-path'
                value={repoPath}
                onChange={(event) => setRepoPath(event.target.value)}
                placeholder='C:\path\to\repo'
              />
              <Button onClick={() => index.mutate()} disabled={!repoPath.trim() || index.isPending}>
                {index.isPending ? 'Indexing…' : 'Index'}
              </Button>
            </div>
            {index.error ? <ErrorText message={index.error.message} /> : null}
            {index.data ? <IndexStatus summary={index.data} /> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Question</CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            <Textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              placeholder='Where is the multiply function defined, and what does it return?'
            />
            <Button
              onClick={() => ask.mutate()}
              disabled={!repoPath.trim() || !question.trim() || ask.isPending}
            >
              {ask.isPending ? 'Reading the repository…' : 'Ask'}
            </Button>
            {ask.error ? <ErrorText message={ask.error.message} /> : null}
            {ask.data ? <AnswerPanel result={ask.data} /> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Change plan</CardTitle>
          </CardHeader>
          <CardContent className='space-y-3'>
            <Textarea
              value={changeRequest}
              onChange={(event) => setChangeRequest(event.target.value)}
              rows={3}
              placeholder='Fix multiply so the existing tests pass.'
            />
            <div className='flex flex-wrap gap-2'>
              <Button
                onClick={() => plan.mutate()}
                disabled={!repoPath.trim() || !changeRequest.trim() || plan.isPending}
              >
                {plan.isPending ? 'Planning…' : 'Plan'}
              </Button>
              <Button
                variant='secondary'
                onClick={() => verify.mutate()}
                disabled={!plan.data || verify.isPending}
              >
                {verify.isPending ? 'Running sandbox…' : 'Verify in sandbox'}
              </Button>
            </div>
            {plan.error ? <ErrorText message={plan.error.message} /> : null}
            {verify.error ? <ErrorText message={verify.error.message} /> : null}
            {plan.data ? <PlanPanel result={plan.data} /> : null}
            {verify.data ? <VerifyPanel result={verify.data} /> : null}
          </CardContent>
        </Card>
      </div>
    </main>
  )
}

function HealthBadge({
  ok,
  detail,
  loading,
}: {
  ok: boolean | undefined
  detail: string | undefined
  loading: boolean
}) {
  if (loading) {
    return <Badge>Checking Grok…</Badge>
  }
  if (ok === undefined) {
    return <Badge tone='bad'>API is not running</Badge>
  }
  return <Badge tone={ok ? 'good' : 'bad'}>{detail || 'Grok status unknown'}</Badge>
}

function IndexStatus({ summary }: { summary: IndexSummary }) {
  return (
    <p className='text-sm text-zinc-600'>
      {summary.files} files, {summary.symbols} symbols, {summary.imports} imports, {summary.chunks}{' '}
      chunks, {summary.entry_points} entry points. Embeddings: {summary.embed_status}. Commit{' '}
      {summary.commit_sha.slice(0, 12)}.
    </p>
  )
}

function AnswerPanel({ result }: { result: AskResult }) {
  const grounding = result.grounding
  return (
    <div className='space-y-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <Badge tone={grounding.cited > 0 && grounding.supported === grounding.cited ? 'good' : 'bad'}>
          {grounding.supported}/{grounding.cited} citations supported
        </Badge>
      </div>
      <p className='whitespace-pre-wrap text-sm leading-6'>{result.answer.answer}</p>
      <div className='space-y-3'>
        {grounding.checks.map((check) => (
          <article
            key={`${check.citation.path}:${check.citation.start_line}:${check.citation.snippet}`}
            className={`rounded-lg border px-3 py-3 ${check.supported ? 'border-emerald-200' : 'border-rose-200'}`}
          >
            <div className='mb-2 flex flex-wrap items-center gap-2'>
              <code className='text-sm font-medium'>
                {check.citation.path}:{check.citation.start_line}-{check.citation.end_line}
              </code>
              <Badge tone={check.supported ? 'good' : 'bad'}>{check.supported ? 'Supported' : 'Failed'}</Badge>
              {check.failures.map((failure) => (
                <Badge key={failure} tone='bad'>
                  {failure}
                </Badge>
              ))}
            </div>
            <p className='text-sm text-zinc-600'>{check.citation.reason}</p>
            {check.actual_text ? (
              <pre className='mt-2 overflow-auto rounded-md bg-zinc-950 p-3 text-xs text-zinc-100'>
                {check.actual_text}
              </pre>
            ) : null}
          </article>
        ))}
      </div>
      {result.answer.unknowns.length > 0 ? (
        <div>
          <h3 className='text-sm font-medium'>Unknowns</h3>
          <ul className='mt-1 list-disc pl-5 text-sm text-zinc-600'>
            {result.answer.unknowns.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function PlanPanel({ result }: { result: PlanResult }) {
  const plan = result.plan
  return (
    <div className='space-y-3 text-sm'>
      <p className='font-medium'>{plan.goal}</p>
      <ul className='list-disc pl-5 text-zinc-700'>
        {plan.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ul>
      <p>Test command: <code>{plan.test_command}</code></p>
      <p>Files: {plan.files.join(', ') || 'none listed'}</p>
      {plan.risks.length > 0 ? (
        <ul className='list-disc pl-5 text-zinc-700'>
          {plan.risks.map((risk) => (
            <li key={risk}>{risk}</li>
          ))}
        </ul>
      ) : null}
      <pre className='overflow-auto rounded-md bg-zinc-950 p-3 text-xs text-zinc-100'>{plan.diff || 'No diff yet.'}</pre>
    </div>
  )
}

function VerifyPanel({ result }: { result: VerifyResult }) {
  const verification = result.verification
  return (
    <div className='space-y-2 text-sm'>
      <Badge tone={verification.passed ? 'good' : 'bad'}>
        {verification.passed ? 'Tests passed' : 'Tests failed'}
      </Badge>
      <p>Exit code: {verification.exit_code ?? 'none'}</p>
      <p>Changed files: {verification.changed_files.join(', ') || 'none'}</p>
      {verification.failures.length > 0 ? <p>Failures: {verification.failures.join(', ')}</p> : null}
      {verification.stdout ? (
        <pre className='overflow-auto rounded-md bg-zinc-950 p-3 text-xs text-zinc-100'>{verification.stdout}</pre>
      ) : null}
      {verification.stderr ? (
        <pre className='overflow-auto rounded-md bg-rose-950 p-3 text-xs text-rose-100'>{verification.stderr}</pre>
      ) : null}
    </div>
  )
}

function ErrorText({ message }: { message: string }) {
  return <p className='text-sm text-rose-700'>{message}</p>
}
