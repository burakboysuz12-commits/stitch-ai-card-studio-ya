'use client';

import { isToolUIPart } from 'ai';
import { Fragment } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ToolCard } from '@/components/ToolCard';
import type { AgentUIMessage } from '@/lib/types';

interface MessageBubbleProps {
  message: AgentUIMessage;
  isStreaming: boolean;
}

export function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  if (message.role === 'user') {
    const text = message.parts.map((p) => (p.type === 'text' ? p.text : '')).join('');
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-emerald-600 px-4 py-2.5 text-sm text-white shadow-sm leading-relaxed">
          {text}
        </div>
      </div>
    );
  }

  const hasVisibleContent = message.parts.some(
    (p) => (p.type === 'text' && p.text.trim()) || isToolUIPart(p),
  );
  if (!hasVisibleContent && !isStreaming) return null;

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-zinc-800 text-sm text-emerald-400 font-semibold shadow-sm">
        ✦
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-3 text-sm leading-relaxed text-zinc-200">
        {message.parts.map((part, index) => {
          if (part.type === 'text') {
            if (!part.text.trim()) return null;
            return (
              <div
                key={index}
                className="prose prose-invert prose-zinc max-w-none text-sm leading-relaxed break-words"
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="mb-2.5 last:mb-0">{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold text-zinc-100">{children}</strong>,
                    ul: ({ children }) => <ul className="my-2 list-disc pl-5 space-y-1">{children}</ul>,
                    ol: ({ children }) => <ol className="my-2 list-decimal pl-5 space-y-1">{children}</ol>,
                    li: ({ children }) => <li className="text-zinc-200">{children}</li>,
                    code: ({ children, className }) => (
                      <code
                        className={
                          className
                            ? 'block rounded-lg bg-zinc-900 border border-zinc-800 p-3 font-mono text-xs text-zinc-200 overflow-x-auto my-2'
                            : 'rounded bg-zinc-800/80 px-1.5 py-0.5 font-mono text-xs text-emerald-300'
                        }
                      >
                        {children}
                      </code>
                    ),
                    a: ({ href, children }) => (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-emerald-400 underline underline-offset-2 hover:text-emerald-300 break-all"
                      >
                        {children}
                      </a>
                    ),
                    blockquote: ({ children }) => (
                      <blockquote className="border-l-2 border-emerald-500/50 pl-3 italic text-zinc-400 my-2">
                        {children}
                      </blockquote>
                    ),
                  }}
                >
                  {part.text}
                </ReactMarkdown>
                {isStreaming && index === message.parts.length - 1 && (
                  <span className="ml-1 inline-block h-3.5 w-1.5 animate-pulse bg-emerald-400 align-baseline" />
                )}
              </div>
            );
          }

          if (part.type === 'reasoning' && part.text.trim()) {
            return (
              <details
                key={index}
                className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-xs text-zinc-400"
              >
                <summary className="cursor-pointer select-none font-medium text-zinc-300">
                  Düşünce Süreci (Reasoning)
                </summary>
                <p className="mt-2 whitespace-pre-wrap leading-relaxed text-zinc-400">{part.text}</p>
              </details>
            );
          }

          if (isToolUIPart(part)) {
            return <ToolCard key={part.toolCallId} part={part} />;
          }

          return <Fragment key={index} />;
        })}
      </div>
    </div>
  );
}
