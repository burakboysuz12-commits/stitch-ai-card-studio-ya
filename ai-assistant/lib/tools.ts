import 'server-only';
import { tool, type ToolSet } from 'ai';
import { z } from 'zod';
import { evaluateExpression } from '@/lib/calculator';
import { env } from '@/lib/env';
import { createPdfFromText } from '@/lib/pdf';
import { getSupabaseAdmin } from '@/lib/supabase/server';

const SIGNED_URL_TTL_SECONDS = 60 * 60 * 24 * 7; // 7 days

function slugify(value: string): string {
  const slug = value
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/ı/g, 'i')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
  return slug || 'document';
}

interface ToolContext {
  conversationId: string;
}

/** Tool factory: tools get per-request context (e.g. conversation for storage paths). */
export function createAgentTools({ conversationId }: ToolContext) {
  return {
    calculator: tool({
      description:
        'Evaluate a mathematical expression precisely. Use for ANY arithmetic, percentages, powers, roots, ' +
        'trigonometry or unit-free math instead of computing mentally.',
      inputSchema: z.object({
        expression: z
          .string()
          .min(1)
          .max(500)
          .describe(
            'A single math expression, e.g. "(1250 * 0.18) + 42" or "sqrt(2) ^ 3". Operators: + - * / ^ % ! ( ). ' +
              'Functions: sqrt, cbrt, abs, sin, cos, tan, asin, acos, atan, exp, ln, log, log2, floor, ceil, round, min, max, pow. ' +
              'Constants: pi, e. No thousands separators, units, or "=" sign.',
          ),
      }),
      execute: async ({ expression }) => evaluateExpression(expression),
    }),

    getSystemTime: tool({
      description:
        'Get the current server date and time. Use whenever the user asks about the current time, date, day, ' +
        'year, or anything relative to "now" (e.g. "how many days until Friday").',
      inputSchema: z.object({
        timeZone: z
          .string()
          .optional()
          .describe('Optional IANA time zone, e.g. "Europe/Istanbul" or "America/New_York". Omit for server time.'),
      }),
      execute: async ({ timeZone }) => {
        const now = new Date();
        const serverTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        let zone = serverTimeZone;
        if (timeZone) {
          try {
            new Intl.DateTimeFormat('en-US', { timeZone });
            zone = timeZone;
          } catch {
            // Invalid zone requested: fall back to server time zone.
          }
        }
        const format = (options: Intl.DateTimeFormatOptions): string =>
          new Intl.DateTimeFormat('en-US', { timeZone: zone, ...options }).format(now);

        return {
          iso: now.toISOString(),
          unixMs: now.getTime(),
          timeZone: zone,
          date: format({ dateStyle: 'full' }),
          time: format({ timeStyle: 'long' }),
          invalidTimeZoneRequested: timeZone !== undefined && zone !== timeZone ? timeZone : null,
        };
      },
    }),

    generateDocument: tool({
      description:
        'Create a downloadable PDF document from text and return its download URL. Use when the user asks to ' +
        'create, export, save, write or download a PDF, document, report, letter or file.',
      inputSchema: z.object({
        title: z.string().max(150).optional().describe('Short document title.'),
        content: z
          .string()
          .min(1)
          .max(50_000)
          .describe('The complete document body as plain text. "# " headings and "- " bullets are supported.'),
      }),
      execute: async ({ title, content }) => {
        const bytes = await createPdfFromText({ title, content });
        const slug = slugify(title ?? content.slice(0, 40));
        const fileName = `${slug}.pdf`;
        const path = `${conversationId}/${Date.now()}-${fileName}`;

        const supabase = getSupabaseAdmin();
        const bucket = supabase.storage.from(env.storageBucket);

        const { error: uploadError } = await bucket.upload(path, Buffer.from(bytes), {
          contentType: 'application/pdf',
          upsert: false,
        });
        if (uploadError) throw new Error(`Upload to Supabase Storage failed: ${uploadError.message}`);

        const { data, error: signError } = await bucket.createSignedUrl(path, SIGNED_URL_TTL_SECONDS, {
          download: fileName,
        });
        if (signError || !data) {
          throw new Error(`Could not create download URL: ${signError?.message ?? 'unknown error'}`);
        }

        return {
          fileName,
          url: data.signedUrl,
          sizeBytes: bytes.byteLength,
          expiresAt: new Date(Date.now() + SIGNED_URL_TTL_SECONDS * 1000).toISOString(),
        };
      },
    }),
  } satisfies ToolSet;
}

export type AgentToolSet = ReturnType<typeof createAgentTools>;
