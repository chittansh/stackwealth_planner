import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatINR(n: number, opts: { compact?: boolean } = {}): string {
  if (!Number.isFinite(n)) return '—';
  if (opts.compact) {
    // Indian short forms: K, L, Cr
    const abs = Math.abs(n);
    if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
    if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
    if (abs >= 1e3) return `₹${(n / 1e3).toFixed(1)} K`;
    return `₹${n.toFixed(0)}`;
  }
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);
}

export function yearsFromNow(years: number): number {
  return new Date().getFullYear() + years;
}
