import type { HTMLAttributes } from 'react'

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: 'neutral' | 'good' | 'bad'
}

export function Badge({ tone = 'neutral', className = '', ...props }: BadgeProps) {
  const styles = {
    neutral: 'bg-zinc-100 text-zinc-700',
    good: 'bg-emerald-100 text-emerald-800',
    bad: 'bg-rose-100 text-rose-800',
  }[tone]
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles} ${className}`}
      {...props}
    />
  )
}
