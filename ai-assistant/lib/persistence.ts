import 'server-only';
import { isToolUIPart, type TextUIPart, type ToolUIPart } from 'ai';
import type { Json, MessageInsert, MessageRow } from '@/lib/database.types';
import { env } from '@/lib/env';
import { getSupabaseAdmin } from '@/lib/supabase/server';
import type { AgentTools, AgentUIMessage, ConversationSummary } from '@/lib/types';

type AgentPart = AgentUIMessage['parts'][number];
type AgentToolPart = ToolUIPart<AgentTools>;

function fail(context: string, error: { message: string }): never {
  throw new Error(`Supabase ${context}: ${error.message}`);
}

export function makeTitle(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (!clean) return 'New conversation';
  return clean.length > 60 ? `${clean.slice(0, 57)}...` : clean;
}

export function getMessageText(message: AgentUIMessage): string {
  return message.parts
    .filter((p): p is TextUIPart => p.type === 'text')
    .map((p) => p.text)
    .join('')
    .trim();
}

// ---------------------------------------------------------------------------
// Mapping between AI SDK UIMessages and DB rows
// ---------------------------------------------------------------------------

export function uiMessageToInsert(message: AgentUIMessage, conversationId: string): MessageInsert {
  const toolParts = message.parts.filter(
    (p): p is AgentToolPart =>
      isToolUIPart(p) && (p.state === 'output-available' || p.state === 'output-error'),
  );
  return {
    id: message.id,
    conversation_id: conversationId,
    role: message.role,
    content: getMessageText(message),
    tool_calls: toolParts.length > 0 ? (toolParts as unknown as Json) : null,
  };
}

/**
 * Rebuilds a UIMessage. `step-start` markers make convertToModelMessages emit:
 *   assistant(tool-calls) -> tool(results) -> assistant(final text)
 * which is the correct multi-step shape for the model.
 */
export function rowToUIMessage(row: MessageRow): AgentUIMessage {
  const toolParts = Array.isArray(row.tool_calls) ? (row.tool_calls as unknown as AgentToolPart[]) : [];
  const parts: AgentPart[] = [];

  if (toolParts.length > 0) {
    parts.push({ type: 'step-start' }, ...toolParts);
    if (row.content) parts.push({ type: 'step-start' });
  }
  if (row.content) parts.push({ type: 'text', text: row.content });

  return {
    id: row.id,
    role: row.role === 'tool' ? 'assistant' : row.role,
    parts,
  };
}

// ---------------------------------------------------------------------------
// Conversations
// ---------------------------------------------------------------------------

export async function listConversations(userId: string): Promise<ConversationSummary[]> {
  const { data, error } = await getSupabaseAdmin()
    .from('conversations')
    .select('id, title, created_at')
    .eq('user_id', userId)
    .order('created_at', { ascending: false })
    .limit(100);
  if (error) fail('listConversations', error);
  return data.map((c) => ({ id: c.id, title: c.title, createdAt: c.created_at }));
}

export async function conversationBelongsTo(conversationId: string, userId: string): Promise<boolean> {
  const { data, error } = await getSupabaseAdmin()
    .from('conversations')
    .select('id')
    .eq('id', conversationId)
    .eq('user_id', userId)
    .maybeSingle();
  if (error) fail('conversationBelongsTo', error);
  return data !== null;
}

/** Creates the conversation on first message. Returns false if it belongs to another user. */
export async function ensureConversation(
  conversationId: string,
  userId: string,
  firstMessageText: string,
): Promise<boolean> {
  const db = getSupabaseAdmin();
  const { data, error } = await db.from('conversations').select('user_id').eq('id', conversationId).maybeSingle();
  if (error) fail('ensureConversation.select', error);
  if (data) return data.user_id === userId;

  const { error: insertError } = await db
    .from('conversations')
    .insert({ id: conversationId, user_id: userId, title: makeTitle(firstMessageText) });
  if (insertError) fail('ensureConversation.insert', insertError);
  return true;
}

export async function deleteConversation(conversationId: string, userId: string): Promise<boolean> {
  const db = getSupabaseAdmin();
  const { data, error } = await db
    .from('conversations')
    .delete()
    .eq('id', conversationId)
    .eq('user_id', userId)
    .select('id');
  if (error) fail('deleteConversation', error);
  if (data.length === 0) return false;

  // Best-effort cleanup of generated PDFs for this conversation.
  const bucket = db.storage.from(env.storageBucket);
  const { data: files } = await bucket.list(conversationId, { limit: 1000 });
  if (files && files.length > 0) {
    await bucket.remove(files.map((f) => `${conversationId}/${f.name}`));
  }
  return true;
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

export async function loadAllMessages(conversationId: string): Promise<AgentUIMessage[]> {
  const { data, error } = await getSupabaseAdmin()
    .from('messages')
    .select('*')
    .eq('conversation_id', conversationId)
    .order('created_at', { ascending: true });
  if (error) fail('loadAllMessages', error);
  return data.map(rowToUIMessage);
}

/** Loads only the last `limit` messages (context window for the local model). */
export async function loadRecentMessages(conversationId: string, limit: number): Promise<AgentUIMessage[]> {
  const { data, error } = await getSupabaseAdmin()
    .from('messages')
    .select('*')
    .eq('conversation_id', conversationId)
    .order('created_at', { ascending: false })
    .limit(limit);
  if (error) fail('loadRecentMessages', error);
  return data.reverse().map(rowToUIMessage);
}

/**
 * Persists the user message (idempotent) and removes anything after it.
 * This makes "regenerate" / "retry after error" consistent with the DB.
 */
export async function saveUserMessage(conversationId: string, message: AgentUIMessage): Promise<void> {
  const db = getSupabaseAdmin();
  const { error } = await db
    .from('messages')
    .upsert(uiMessageToInsert(message, conversationId), { onConflict: 'id', ignoreDuplicates: true });
  if (error) fail('saveUserMessage.upsert', error);

  const { data: saved, error: readError } = await db
    .from('messages')
    .select('conversation_id, created_at')
    .eq('id', message.id)
    .single();
  if (readError) fail('saveUserMessage.read', readError);
  if (saved.conversation_id !== conversationId) {
    throw new Error('Message id already belongs to a different conversation.');
  }

  const { error: deleteError } = await db
    .from('messages')
    .delete()
    .eq('conversation_id', conversationId)
    .gt('created_at', saved.created_at);
  if (deleteError) fail('saveUserMessage.truncate', deleteError);
}

export async function saveAssistantMessage(conversationId: string, message: AgentUIMessage): Promise<void> {
  const row = uiMessageToInsert(message, conversationId);
  if (!row.content && row.tool_calls === null) return; // nothing worth persisting
  const { error } = await getSupabaseAdmin().from('messages').upsert(row, { onConflict: 'id' });
  if (error) fail('saveAssistantMessage', error);
}
