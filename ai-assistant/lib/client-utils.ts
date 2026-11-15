import type { ApiErrorBody } from '@/lib/types';

/** Extracts a readable message from API JSON errors or stream error strings. */
export function readErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  if (!raw) return 'Something went wrong.';
  try {
    const parsed = JSON.parse(raw) as Partial<ApiErrorBody>;
    if (typeof parsed.error === 'string') return parsed.error;
  } catch {
    // not JSON - use as-is
  }
  return raw;
}

export async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, { cache: 'no-store', ...init });
  if (!res.ok) {
    throw new Error(await res.text().catch(() => `HTTP ${res.status}`));
  }
  return (await res.json()) as T;
}
