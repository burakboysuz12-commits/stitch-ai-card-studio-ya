import { randomUUID } from 'node:crypto';
import { convertToModelMessages, stepCountIs, streamText } from 'ai';
import { z } from 'zod';
import { env } from '@/lib/env';
import { errorResponse, logError } from '@/lib/http';
import { checkProviderHealth, describeProviderError, getLanguageModel } from '@/lib/provider';
import {
  ensureConversation,
  getMessageText,
  saveAssistantMessage,
  saveUserMessage,
} from '@/lib/persistence';
import { SYSTEM_PROMPT } from '@/lib/prompt';
import { createAgentTools } from '@/lib/tools';
import type { AgentUIMessage } from '@/lib/types';
import { getOrCreateUserId } from '@/lib/user';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 120;

const uuidSchema = z.string().regex(
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  'Invalid UUID',
);

/**
 * Validates the full messages array received from useChat.
 * Allows preserving complete conversational memory and context thread.
 */
const chatRequestSchema = z.object({
  conversationId: uuidSchema.optional(),
  messages: z
    .array(
      z.object({
        id: z.string(),
        role: z.enum(['user', 'assistant', 'system', 'tool']),
        parts: z.array(z.any()),
      }),
    )
    .min(1, 'Messages array cannot be empty.'),
});

export async function POST(req: Request): Promise<Response> {
  // 1. Parse and validate incoming payload
  let json: unknown;
  try {
    json = await req.json();
  } catch {
    return errorResponse(400, 'BAD_REQUEST', 'Request body must be valid JSON.');
  }

  const parsed = chatRequestSchema.safeParse(json);
  if (!parsed.success) {
    return errorResponse(
      400,
      'BAD_REQUEST',
      `Invalid request: ${parsed.error.issues[0]?.message ?? 'Validation error'}`,
    );
  }

  const incomingMessages = parsed.data.messages as AgentUIMessage[];
  const lastUserMessage = [...incomingMessages].reverse().find((m) => m.role === 'user');
  if (!lastUserMessage) {
    return errorResponse(400, 'BAD_REQUEST', 'At least one user message is required.');
  }

  const conversationId = parsed.data.conversationId || randomUUID();
  const userText = getMessageText(lastUserMessage);

  // 2. Health check active AI provider (EVREN AI or local Ollama)
  const health = await checkProviderHealth();
  if (!health.ok) {
    return errorResponse(503, health.code, health.message);
  }

  try {
    // 3. Persist conversation and last user message in Supabase
    const userId = await getOrCreateUserId();
    await ensureConversation(conversationId, userId, userText || 'New Conversation');
    await saveUserMessage(conversationId, lastUserMessage);

    // 4. Memory & Context: Pass the entire conversation history to the model
    // (Preserves multi-turn context thread, emotional continuity, and previous references)
    const tools = createAgentTools({ conversationId });
    const modelMessages = await convertToModelMessages(incomingMessages, {
      tools,
      ignoreIncompleteToolCalls: true,
    });

    // 5. Stream response with system persona, full messages, and autonomous tools
    const result = streamText({
      model: getLanguageModel(health.model),
      system: SYSTEM_PROMPT,
      messages: modelMessages,
      tools,
      toolChoice: 'auto',
      stopWhen: stepCountIs(env.maxAgentSteps),
      temperature: 0.7, // Balances warm, creative dialogue with logical tool calling
      maxRetries: 1,
      abortSignal: req.signal,
      onError: ({ error }) => logError('chat.streamText', error),
    });

    return result.toUIMessageStreamResponse<AgentUIMessage>({
      originalMessages: incomingMessages,
      generateMessageId: () => randomUUID(),
      onFinish: async ({ responseMessage }) => {
        try {
          await saveAssistantMessage(conversationId, responseMessage);
        } catch (error) {
          logError('chat.persistAssistant', error);
        }
      },
      onError: (error) => describeProviderError(error),
    });
  } catch (error) {
    logError('chat', error);
    return errorResponse(
      500,
      'INTERNAL_ERROR',
      error instanceof Error ? error.message : 'Unexpected server error.',
    );
  }
}
