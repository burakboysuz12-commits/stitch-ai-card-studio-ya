import 'server-only';
import type { ApiErrorBody, ApiErrorCode } from '@/lib/types';

export function errorResponse(status: number, code: ApiErrorCode, message: string): Response {
  const body: ApiErrorBody = { error: message, code };
  return Response.json(body, { status });
}

export function logError(scope: string, error: unknown): void {
  console.error(`[${scope}]`, error instanceof Error ? error.stack ?? error.message : error);
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
