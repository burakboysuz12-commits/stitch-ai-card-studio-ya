import type { InferUITools, UIDataTypes, UIMessage } from 'ai';
import type { AgentToolSet } from '@/lib/tools';

/** Shared (client + server) types. Only type-imports from server modules. */
export type AgentTools = InferUITools<AgentToolSet>;
export type AgentUIMessage = UIMessage<unknown, UIDataTypes, AgentTools>;

export interface ConversationSummary {
  id: string;
  title: string;
  createdAt: string;
}

export type ApiErrorCode =
  | 'OLLAMA_UNREACHABLE'
  | 'EVREN_UNREACHABLE'
  | 'EVREN_AUTH_ERROR'
  | 'EVREN_TERMS_REQUIRED'
  | 'MODEL_NOT_FOUND'
  | 'BAD_REQUEST'
  | 'NOT_FOUND'
  | 'INTERNAL_ERROR';

export interface ApiErrorBody {
  error: string;
  code: ApiErrorCode;
}

export interface HealthResponse {
  ok: boolean;
  provider?: 'evren' | 'ollama';
  model: string;
  baseUrl: string;
  message?: string;
}
