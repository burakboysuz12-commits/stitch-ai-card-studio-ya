'use client';

import { useCallback, useEffect, useState } from 'react';
import { Chat } from '@/components/Chat';
import { OllamaStatus } from '@/components/OllamaStatus';
import { Sidebar } from '@/components/Sidebar';
import { fetchJson, readErrorMessage } from '@/lib/client-utils';
import type { AgentUIMessage, ConversationSummary } from '@/lib/types';

interface ActiveChat {
  id: string;
  messages: AgentUIMessage[];
}

export function ChatApp() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [active, setActive] = useState<ActiveChat | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const refreshConversations = useCallback(async () => {
    try {
      const data = await fetchJson<{ conversations: ConversationSummary[] }>('/api/conversations');
      setConversations(data.conversations);
      setListError(null);
    } catch (error) {
      setListError(readErrorMessage(error));
    }
  }, []);

  const startNewChat = useCallback(() => {
    setActive({ id: crypto.randomUUID(), messages: [] });
    setSidebarOpen(false);
  }, []);

  useEffect(() => {
    void refreshConversations();
    startNewChat();
  }, [refreshConversations, startNewChat]);

  const selectConversation = useCallback(
    async (id: string) => {
      if (id === active?.id) {
        setSidebarOpen(false);
        return;
      }
      setLoadingId(id);
      try {
        const data = await fetchJson<{ messages: AgentUIMessage[] }>(`/api/conversations/${id}`);
        setActive({ id, messages: data.messages });
        setSidebarOpen(false);
      } catch (error) {
        setListError(readErrorMessage(error));
      } finally {
        setLoadingId(null);
      }
    },
    [active?.id],
  );

  const removeConversation = useCallback(
    async (id: string) => {
      if (!window.confirm('Delete this conversation and its generated documents?')) return;
      try {
        const res = await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
        if (!res.ok && res.status !== 404) throw new Error(await res.text());
        setConversations((prev) => prev.filter((c) => c.id !== id));
        if (active?.id === id) startNewChat();
      } catch (error) {
        setListError(readErrorMessage(error));
      }
    },
    [active?.id, startNewChat],
  );

  const activeTitle = conversations.find((c) => c.id === active?.id)?.title ?? 'New conversation';

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar
        conversations={conversations}
        activeId={active?.id ?? null}
        loadingId={loadingId}
        error={listError}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onNewChat={startNewChat}
        onSelect={(id) => void selectConversation(id)}
        onDelete={(id) => void removeConversation(id)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-zinc-800 px-4">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="rounded-md p-2 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 md:hidden"
            aria-label="Open conversations"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
            </svg>
          </button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-200">{activeTitle}</h1>
          <OllamaStatus />
        </header>

        {active ? (
          <Chat
            key={active.id}
            conversationId={active.id}
            initialMessages={active.messages}
            onActivity={() => void refreshConversations()}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-zinc-500">Loading...</div>
        )}
      </main>
    </div>
  );
}
