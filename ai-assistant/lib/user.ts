import 'server-only';
import { randomUUID } from 'node:crypto';
import { cookies } from 'next/headers';

const COOKIE_NAME = 'agent_uid';
const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Returns a stable anonymous user id stored in an httpOnly cookie.
 * Swap this for `supabase.auth.getUser()` if you add Supabase Auth.
 * Must only be called from Route Handlers / Server Actions (it may set a cookie).
 */
export async function getOrCreateUserId(): Promise<string> {
  const store = await cookies();
  const existing = store.get(COOKIE_NAME)?.value;
  if (existing && UUID_RE.test(existing)) return existing;

  const id = randomUUID();
  store.set(COOKIE_NAME, id, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: ONE_YEAR_SECONDS,
  });
  return id;
}
