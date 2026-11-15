import 'server-only';
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import type { LanguageModel } from 'ai';
import { env, type AiProviderName } from '@/lib/env';
import { checkOllama, describeOllamaError, ollama } from '@/lib/ollama';
import type { ApiErrorCode } from '@/lib/types';

export type ProviderHealth =
  | { ok: true; provider: AiProviderName; model: string; baseUrl: string }
  | { ok: false; provider: AiProviderName; code: ApiErrorCode; message: string; model: string; baseUrl: string };

const HEALTH_TIMEOUT_MS = 5000;

function evrenHeaders(apiKey: string): Record<string, string> {
  return {
    Authorization: `Bearer ${apiKey}`,
    'X-API-Key': apiKey,
  };
}

/** Creates an OpenAI-compatible AI SDK provider bound to EVREN LLM API. */
export function getEvrenProvider() {
  return createOpenAICompatible({
    name: 'evren',
    baseURL: env.evrenBaseUrl,
    apiKey: env.evrenApiKey,
    headers: env.evrenApiKey ? { 'X-API-Key': env.evrenApiKey } : undefined,
  });
}

/** Returns the active LanguageModel instance for EVREN AI or local Ollama. */
export function getLanguageModel(modelId: string): LanguageModel {
  if (env.aiProvider === 'evren') {
    return getEvrenProvider()(modelId);
  }
  return ollama(modelId);
}

async function checkEvren(): Promise<ProviderHealth> {
  const base = {
    provider: 'evren' as const,
    model: env.evrenModel,
    baseUrl: env.evrenBaseUrl,
  };

  if (!env.evrenApiKey) {
    return {
      ...base,
      ok: false,
      code: 'EVREN_AUTH_ERROR',
      message: 'EVREN_API_KEY is not set. Add your evren_llm_... key to .env.local.',
    };
  }

  try {
    const res = await fetch(`${env.evrenBaseUrl}/models`, {
      headers: evrenHeaders(env.evrenApiKey),
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      cache: 'no-store',
    });

    if (res.status === 401 || res.status === 403) {
      return {
        ...base,
        ok: false,
        code: 'EVREN_AUTH_ERROR',
        message: 'EVREN API key is invalid or unauthorized. Check EVREN_API_KEY in .env.local.',
      };
    }

    if (!res.ok) {
      return {
        ...base,
        ok: false,
        code: 'EVREN_UNREACHABLE',
        message: `EVREN API responded with HTTP ${res.status} at ${env.evrenBaseUrl}.`,
      };
    }

    const data = (await res.json()) as { data?: Array<{ id?: string }> };
    const modelIds = (data.data ?? []).map((m) => m.id ?? '').filter(Boolean);

    try {
      const termsRes = await fetch(`${env.evrenBaseUrl}/terms/status`, {
        headers: evrenHeaders(env.evrenApiKey),
        signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
        cache: 'no-store',
      });
      if (termsRes.ok) {
        const terms = (await termsRes.json()) as { accepted?: boolean };
        if (terms.accepted === false) {
          return {
            ...base,
            ok: false,
            code: 'EVREN_TERMS_REQUIRED',
            message: 'EVREN API terms of service must be accepted first via POST /v1/terms/accept.',
          };
        }
      }
    } catch {
      // Ignore optional terms preflight error and let chat handle it if needed
    }

    if (env.evrenModel !== 'auto' && modelIds.length > 0 && !modelIds.includes(env.evrenModel)) {
      return {
        ...base,
        ok: false,
        code: 'MODEL_NOT_FOUND',
        message: `EVREN model "${env.evrenModel}" was not found. Available: ${modelIds.slice(0, 8).join(', ')}`,
      };
    }

    return { ...base, ok: true };
  } catch (error) {
    const timedOut = error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
    return {
      ...base,
      ok: false,
      code: 'EVREN_UNREACHABLE',
      message: timedOut
        ? `EVREN API at ${env.evrenBaseUrl} did not respond within ${HEALTH_TIMEOUT_MS / 1000}s.`
        : `Cannot reach EVREN API at ${env.evrenBaseUrl}.`,
    };
  }
}

/** Checks readiness of whichever AI provider (EVREN or Ollama) is active. */
export async function checkProviderHealth(): Promise<ProviderHealth> {
  if (env.aiProvider === 'evren') {
    return checkEvren();
  }
  const ollamaHealth = await checkOllama();
  return { ...ollamaHealth, provider: 'ollama' };
}

/** Translates provider runtime errors into readable user-facing messages. */
export function describeProviderError(error: unknown): string {
  if (env.aiProvider !== 'evren') {
    return describeOllamaError(error);
  }
  const msg = error instanceof Error ? error.message : String(error ?? '');
  const lower = msg.toLowerCase();
  if (lower.includes('terms_not_accepted')) {
    return 'EVREN kullanım şartları onaylanmamış. Lütfen önce /v1/terms/accept ile şartları onaylayın.';
  }
  if (lower.includes('401') || lower.includes('unauthorized')) {
    return 'EVREN API anahtarı geçersiz veya eksik. .env.local içindeki EVREN_API_KEY değerini kontrol edin.';
  }
  if (lower.includes('429') || lower.includes('rate limit')) {
    return 'EVREN API istek/token limitine ulaşıldı. Biraz bekleyip tekrar deneyin.';
  }
  return msg ? `EVREN AI yanıt veremedi: ${msg.slice(0, 300)}` : 'EVREN AI yanıt veremedi.';
}
