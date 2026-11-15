import 'server-only';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createOllama } from 'ollama-ai-provider-v2';
import { env } from '@/lib/env';
import type { ApiErrorCode } from '@/lib/types';

/** Ollama provider pointed at the local instance (default http://localhost:11434). */
export const ollama = createOllama({ baseURL: `${env.ollamaBaseUrl}/api` });

export type OllamaHealth =
  | { ok: true; model: string; baseUrl: string }
  | { ok: false; code: ApiErrorCode; message: string; model: string; baseUrl: string };

const HEALTH_TIMEOUT_MS = 3000;

/** Matches "llama3.1" against "llama3.1:latest" etc. */
function modelMatches(installed: string, wanted: string): boolean {
  return installed === wanted || (!wanted.includes(':') && installed.startsWith(`${wanted}:`));
}

/** Attempts to auto-start Ollama on Windows if not currently listening. */
async function tryAutoStartOllama(): Promise<void> {
  const localAppData = process.env.LOCALAPPDATA ?? 'C:\\Users\\burakb\\AppData\\Local';
  const ollamaExe = `${localAppData}\\Programs\\Ollama\\ollama.exe`;
  if (!existsSync(ollamaExe)) return;
  try {
    const child = spawn(ollamaExe, ['serve'], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
    child.unref();
    await new Promise((resolve) => setTimeout(resolve, 2500));
  } catch {
    // ignore spawn errors
  }
}

/**
 * Fast pre-flight check so we can fail with a clear 503 instead of a hanging
 * stream when Ollama isn't running or the model isn't pulled.
 */
export async function checkOllama(): Promise<OllamaHealth> {
  const base = { model: env.ollamaModel, baseUrl: env.ollamaBaseUrl };
  let res: Response | null = null;
  try {
    res = await fetch(`${env.ollamaBaseUrl}/api/tags`, {
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      cache: 'no-store',
    });
  } catch {
    await tryAutoStartOllama();
  }

  try {
    if (!res) {
      res = await fetch(`${env.ollamaBaseUrl}/api/tags`, {
        signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
        cache: 'no-store',
      });
    }
    if (!res.ok) {
      return {
        ...base,
        ok: false,
        code: 'OLLAMA_UNREACHABLE',
        message: `Ollama responded with HTTP ${res.status} at ${env.ollamaBaseUrl}.`,
      };
    }
    const data = (await res.json()) as { models?: Array<{ name?: string }> };
    const names = (data.models ?? []).map((m) => m.name ?? '').filter(Boolean);
    const matched = names.find((n) => modelMatches(n, env.ollamaModel));
    if (matched) {
      return { ...base, model: matched, ok: true };
    }
    if (!env.hasExplicitOllamaModel && names.length > 0) {
      const preferred =
        names.find((n) => n.startsWith('qwen2.5')) ??
        names.find((n) => n.startsWith('llama3.2')) ??
        names[0]!;
      return { ...base, model: preferred, ok: true };
    }
    return {
      ...base,
      ok: false,
      code: 'MODEL_NOT_FOUND',
      message: `Model "${env.ollamaModel}" is not installed in Ollama. Run: ollama pull ${env.ollamaModel}`,
    };
  } catch (error) {
    const timedOut = error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
    return {
      ...base,
      ok: false,
      code: 'OLLAMA_UNREACHABLE',
      message: timedOut
        ? `Ollama at ${env.ollamaBaseUrl} did not respond within ${HEALTH_TIMEOUT_MS / 1000}s.`
        : `Cannot reach Ollama at ${env.ollamaBaseUrl}. Make sure Ollama is running ("ollama serve").`,
    };
  }
}

/** Flattens nested error causes (AI SDK wraps fetch errors several levels deep). */
function collectErrorText(error: unknown, depth = 0): string[] {
  if (depth > 5 || error == null) return [];
  if (typeof error === 'string') return [error];
  if (typeof error !== 'object') return [String(error)];

  const record = error as Record<string, unknown>;
  const parts: string[] = [];
  for (const key of ['message', 'code', 'responseBody'] as const) {
    const value = record[key];
    if (typeof value === 'string') parts.push(value);
  }
  parts.push(...collectErrorText(record.cause, depth + 1));
  parts.push(...collectErrorText(record.lastError, depth + 1));
  if (Array.isArray(record.errors)) {
    for (const inner of record.errors) parts.push(...collectErrorText(inner, depth + 1));
  }
  return parts;
}

/** Converts any streaming/runtime error into a user-friendly message. */
export function describeOllamaError(error: unknown): string {
  const raw = collectErrorText(error);
  const text = raw.join(' | ').toLowerCase();

  if (/econnrefused|econnreset|enotfound|fetch failed|und_err_connect|connect timeout|socket hang up/.test(text)) {
    return `Lost connection to Ollama at ${env.ollamaBaseUrl}. Make sure Ollama is running and try again.`;
  }
  if (text.includes('does not support tools')) {
    return `The model "${env.ollamaModel}" does not support tool calling in Ollama. Use a tool-capable model (e.g. llama3.1, llama3.2, qwen2.5, phi4-mini) via OLLAMA_MODEL.`;
  }
  if (text.includes('model') && text.includes('not found')) {
    return `Model "${env.ollamaModel}" was not found. Run: ollama pull ${env.ollamaModel}`;
  }
  if (/out of memory|cuda error|insufficient memory|vram/.test(text)) {
    return 'Ollama ran out of memory. Try a smaller model or close other GPU-heavy applications.';
  }
  const first = raw[0]?.slice(0, 300);
  return first ? `The assistant failed to respond: ${first}` : 'The assistant failed to respond.';
}
