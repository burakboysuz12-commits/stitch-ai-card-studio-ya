import { checkProviderHealth } from '@/lib/provider';
import type { HealthResponse } from '@/lib/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(): Promise<Response> {
  const health = await checkProviderHealth();
  const body: HealthResponse = health.ok
    ? { ok: true, provider: health.provider, model: health.model, baseUrl: health.baseUrl }
    : {
        ok: false,
        provider: health.provider,
        model: health.model,
        baseUrl: health.baseUrl,
        message: health.message,
      };
  return Response.json(body, { status: health.ok ? 200 : 503 });
}
