'use client';

import { useEffect, useState } from 'react';
import type { HealthResponse } from '@/lib/types';

const POLL_MS = 20_000;

export function OllamaStatus() {
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch('/api/health', { cache: 'no-store' });
        const data = (await res.json()) as HealthResponse;
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth({ ok: false, model: '?', baseUrl: '?', message: 'Server unreachable.' });
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const color = health === null ? 'bg-zinc-500' : health.ok ? 'bg-emerald-500' : 'bg-red-500';
  const providerPrefix = health?.provider === 'evren' ? 'EVREN: ' : '';
  const offlineLabel = health?.provider === 'evren' ? 'EVREN offline' : 'Ollama offline';
  const label = health === null ? 'Checking...' : health.ok ? `${providerPrefix}${health.model}` : offlineLabel;

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-zinc-800 px-3 py-1 text-xs text-zinc-400"
      title={health?.message ?? health?.baseUrl ?? ''}
    >
      <span className={`h-2 w-2 rounded-full ${color} ${health?.ok ? '' : 'animate-pulse'}`} />
      <span className="max-w-[14rem] truncate">{label}</span>
    </div>
  );
}
