import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "$0";
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
