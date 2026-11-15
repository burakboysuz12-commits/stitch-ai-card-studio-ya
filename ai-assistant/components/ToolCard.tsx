'use client';

import type { ToolUIPart } from 'ai';
import type { AgentTools } from '@/lib/types';

type AgentToolPart = ToolUIPart<AgentTools>;

const TOOL_META: Record<AgentToolPart['type'], { icon: string; label: string; running: string }> = {
  'tool-calculator': { icon: '🧮', label: 'Calculator', running: 'Calculating...' },
  'tool-getSystemTime': { icon: '🕒', label: 'System time', running: 'Reading the system clock...' },
  'tool-generateDocument': { icon: '📄', label: 'PDF document', running: 'Generating PDF & uploading to storage...' },
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Spinner() {
  return <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-amber-400/30 border-t-amber-400" />;
}

/** Short description of what the tool was asked to do (visible while running). */
function InputSummary({ part }: { part: AgentToolPart }) {
  if (part.state === 'input-streaming' || part.input === undefined) return null;
  switch (part.type) {
    case 'tool-calculator':
      return <code className="font-mono text-xs text-zinc-400">{part.input.expression}</code>;
    case 'tool-getSystemTime':
      return part.input.timeZone ? <span className="text-xs text-zinc-400">{part.input.timeZone}</span> : null;
    case 'tool-generateDocument':
      return part.input.title ? <span className="text-xs text-zinc-400">“{part.input.title}”</span> : null;
  }
}

function Output({ part }: { part: AgentToolPart }) {
  if (part.state !== 'output-available') return null;
  switch (part.type) {
    case 'tool-calculator':
      return (
        <p className="font-mono text-sm">
          <span className="text-zinc-400">{part.output.expression} =</span>{' '}
          <span className="font-semibold text-emerald-300">{part.output.formatted}</span>
        </p>
      );
    case 'tool-getSystemTime':
      return (
        <p className="text-sm">
          <span className="font-semibold text-emerald-300">{part.output.time}</span>
          <span className="text-zinc-400"> · {part.output.date}</span>
        </p>
      );
    case 'tool-generateDocument':
      return (
        <a
          href={part.output.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 rounded-lg border border-zinc-700 bg-zinc-800/60 px-3 py-2 hover:border-emerald-600 hover:bg-zinc-800"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-red-500/15 text-[10px] font-bold text-red-300">
            PDF
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-zinc-100">{part.output.fileName}</span>
            <span className="block text-xs text-zinc-400">
              {formatBytes(part.output.sizeBytes)} · link expires {new Date(part.output.expiresAt).toLocaleDateString()}
            </span>
          </span>
          <span className="text-xs font-medium text-emerald-400">Download ↓</span>
        </a>
      );
  }
}

export function ToolCard({ part }: { part: AgentToolPart }) {
  const meta = TOOL_META[part.type];
  const running = part.state === 'input-streaming' || part.state === 'input-available';
  const failed = part.state === 'output-error';

  const border = running ? 'border-amber-500/40' : failed ? 'border-red-800/70' : 'border-zinc-800';
  const statusText = running ? meta.running : failed ? 'Failed' : 'Done';
  const statusColor = running ? 'text-amber-400' : failed ? 'text-red-400' : 'text-emerald-400';

  return (
    <div className={`rounded-xl border ${border} bg-zinc-900/70 p-3 transition-colors`}>
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true">{meta.icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wide text-zinc-300">{meta.label}</span>
        <InputSummary part={part} />
        <span className={`ml-auto flex items-center gap-1.5 text-xs ${statusColor}`}>
          {running && <Spinner />}
          {statusText}
        </span>
      </div>
      {(part.state === 'output-available' || failed) && (
        <div className="mt-2">
          {failed ? <p className="text-xs text-red-300">{part.errorText}</p> : <Output part={part} />}
        </div>
      )}
    </div>
  );
}
