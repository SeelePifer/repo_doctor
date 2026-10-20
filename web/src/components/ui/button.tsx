import type { ButtonHTMLAttributes } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'secondary'
}

export function Button({ variant = 'default', className = '', ...props }: ButtonProps) {
  const styles =
    variant === 'secondary'
      ? 'border border-zinc-300 bg-white text-zinc-900 hover:bg-zinc-50'
      : 'bg-zinc-900 text-white hover:bg-zinc-700'
  return (
    <button
      className={`inline-flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  )
}
