import 'server-only';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { Database } from '@/lib/database.types';
import { env } from '@/lib/env';

let adminClient: SupabaseClient<Database> | null = null;

/**
 * Server-only Supabase client using the service-role key.
 * Never import this from a Client Component.
 */
export function getSupabaseAdmin(): SupabaseClient<Database> {
  if (!adminClient) {
    adminClient = createClient<Database>(env.supabaseUrl, env.supabaseServiceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
  }
  return adminClient;
}
