import { errorResponse, logError, UUID_RE } from '@/lib/http';
import { conversationBelongsTo, deleteConversation, loadAllMessages } from '@/lib/persistence';
import { getOrCreateUserId } from '@/lib/user';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function GET(_req: Request, { params }: RouteContext): Promise<Response> {
  const { id } = await params;
  if (!UUID_RE.test(id)) return errorResponse(400, 'BAD_REQUEST', 'Invalid conversation id.');
  try {
    const userId = await getOrCreateUserId();
    if (!(await conversationBelongsTo(id, userId))) {
      return errorResponse(404, 'NOT_FOUND', 'Conversation not found.');
    }
    const messages = await loadAllMessages(id);
    return Response.json({ messages });
  } catch (error) {
    logError('conversations.get', error);
    return errorResponse(500, 'INTERNAL_ERROR', 'Could not load messages from Supabase.');
  }
}

export async function DELETE(_req: Request, { params }: RouteContext): Promise<Response> {
  const { id } = await params;
  if (!UUID_RE.test(id)) return errorResponse(400, 'BAD_REQUEST', 'Invalid conversation id.');
  try {
    const userId = await getOrCreateUserId();
    const deleted = await deleteConversation(id, userId);
    if (!deleted) return errorResponse(404, 'NOT_FOUND', 'Conversation not found.');
    return new Response(null, { status: 204 });
  } catch (error) {
    logError('conversations.delete', error);
    return errorResponse(500, 'INTERNAL_ERROR', 'Could not delete conversation.');
  }
}
