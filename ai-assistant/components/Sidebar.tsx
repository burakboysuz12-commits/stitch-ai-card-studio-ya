'use client';

import type { ConversationSummary } from '@/lib/types';

interface SidebarProps {
  conversations: ConversationSummary[];
  activeId: string | null;
  loadingId: string | null;
  error: string | null;
  open: boolean;
  onClose: () => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay
    ? date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function Sidebar({
  conversations,
  activeId,
  loadingId,
  error,
  open,
  onClose,
  onNewChat,
  onSelect,
  onDelete,
}: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      <div
        className={`fixed inset-0 z-30 bg-black/60 transition-opacity md:hidden ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-zinc-800 bg-zinc-900 transition-transform md:static md:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex h-14 items-center justify-between border-b border-zinc-800 px-4">
          <span className="flex items-center gap-2 text-sm font-semibold">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
              ✦
            </span>
            Mini Agent
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-800 md:hidden"
            aria-label="Close sidebar"
          >
            ✕
          </button>
        </div>

        <div className="p-3">
          <button
            type="button"
            onClick={onNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm font-medium hover:bg-zinc-800"
          >
            <span className="text-lg leading-none">+</span> New chat
          </button>
        </div>

        {error && (
          <p className="mx-3 mb-2 rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        <nav className="flex-1 overflow-y-auto px-2 pb-4">
          {conversations.length === 0 && !error && (
            <p className="px-3 py-6 text-center text-xs text-zinc-500">No conversations yet.</p>
          )}
          <ul className="space-y-0.5">
            {conversations.map((c) => {
              const isActive = c.id === activeId;
              return (
                <li key={c.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    className={`flex w-full flex-col items-start rounded-lg px-3 py-2 pr-9 text-left transition-colors ${
                      isActive ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-300 hover:bg-zinc-800/60'
                    }`}
                  >
                    <span className="w-full truncate text-sm">{c.title}</span>
                    <span className="text-[11px] text-zinc-500">
                      {loadingId === c.id ? 'Loading...' : formatDate(c.createdAt)}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(c.id)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-500 opacity-0 hover:bg-zinc-700 hover:text-red-400 focus:opacity-100 group-hover:opacity-100"
                    aria-label={`Delete ${c.title}`}
                  >
                    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>
    </>
  );
}
