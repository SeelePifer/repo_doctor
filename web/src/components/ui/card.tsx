import type { HTMLAttributes, ReactNode } from 'react'

export function Card({ className = '', ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={`rounded-xl border border-zinc-200 bg-white shadow-sm ${className}`}
      {...props}
    />
  )
}

export function CardHeader({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`border-b border-zinc-100 px-5 py-4 ${className}`} {...props} />
}

export function CardTitle({ children }: { children: ReactNode }) {
  return <h2 className='text-base font-semibold text-zinc-900'>{children}</h2>
}

export function CardContent({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`px-5 py-4 ${className}`} {...props} />
}
