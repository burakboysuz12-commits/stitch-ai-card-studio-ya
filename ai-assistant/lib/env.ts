import 'server-only';

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export type AiProviderName = 'evren' | 'ollama';

function resolveAiProvider(): AiProviderName {
  const raw = (process.env.AI_PROVIDER ?? '').trim().toLowerCase();
  if (raw === 'evren' || raw === 'ollama') return raw;
  return (process.env.EVREN_API_KEY ?? '').trim() ? 'evren' : 'ollama';
}

/** Centralised, typed server configuration. Getters defer validation until use. */
export const env = {
  get supabaseUrl(): string {
    return required('SUPABASE_URL');
  },
  get supabaseServiceKey(): string {
    return required('SUPABASE_SERVICE_ROLE_KEY');
  },
  storageBucket: process.env.SUPABASE_STORAGE_BUCKET ?? 'documents',
  get aiProvider(): AiProviderName {
    return resolveAiProvider();
  },
  evrenBaseUrl: (process.env.EVREN_BASE_URL ?? 'https://evren-llmapi.ssyz.org.tr/v1').replace(/\/+$/, ''),
  get evrenApiKey(): string {
    return (process.env.EVREN_API_KEY ?? '').trim();
  },
  evrenModel: (process.env.EVREN_MODEL ?? 'auto').trim() || 'auto',
  ollamaBaseUrl: (process.env.OLLAMA_BASE_URL ?? 'http://localhost:11434').replace(/\/+$/, ''),
  ollamaModel: process.env.OLLAMA_MODEL ?? 'qwen2.5:7b',
  hasExplicitOllamaModel: Boolean(process.env.OLLAMA_MODEL),
  /** Max number of messages sent to the model per request (VRAM protection). */
  contextWindowMessages: 10,
  /** Max autonomous tool-call / response steps per user turn. */
  maxAgentSteps: 5,
} as const;
