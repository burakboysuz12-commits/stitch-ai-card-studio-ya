import { errorResponse, logError } from '@/lib/http';
import { listConversations } from '@/lib/persistence';
import { getOrCreateUserId } from '@/lib/user';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(): Promise<Response> {
  try {
    const userId = await getOrCreateUserId();
    const conversations = await listConversations(userId);
    return Response.json({ conversations });
  } catch (error) {
    logError('conversations.list', error);
    return errorResponse(500, 'INTERNAL_ERROR', 'Could not load conversations from Supabase.');
  }
}
