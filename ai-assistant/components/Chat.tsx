'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { MessageBubble } from '@/components/MessageBubble';
import { readErrorMessage } from '@/lib/client-utils';
import type { AgentUIMessage } from '@/lib/types';

interface ChatProps {
  conversationId: string;
  initialMessages: AgentUIMessage[];
  onActivity: () => void;
}

const CONVERSATION_STARTERS = [
  'Merhaba! Nasılsın, seninle biraz sohbet etmek istiyorum.',
  'Bugün biraz yorucu bir gündü, anlatmak istedim.',
  'Şu an güncel saat ve tarih nedir?',
  '(1250 * 0.18) + 42 işlemini hesaplar mısın?',
  'Yapay zeka asistanımız için Türkçe karakterli bir proje özeti PDF belgesi oluştur.',
] as const;

export function Chat({ conversationId, initialMessages, onActivity }: ChatProps) {
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Send the entire conversation history (messages array) to maintain full context and thread memory
  const transport = useMemo(
    () =>
      new DefaultChatTransport<AgentUIMessage>({
        api: '/api/chat',
        prepareSendMessagesRequest: ({ id, messages }) => ({
          body: {
            conversationId: id,
            messages, // Full messages history passed to server
          },
        }),
      }),
    [],
  );

  const {
    messages,
    sendMessage,
    setMessages,
    status,
    error,
    regenerate,
    stop,
    clearError,
  } = useChat<AgentUIMessage>({
    id: conversationId,
    messages: initialMessages,
    transport,
    generateId: () => crypto.randomUUID(),
    onFinish: () => onActivity(),
    onError: () => onActivity(),
  });

  const busy = status === 'submitted' || status === 'streaming';

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, status]);

  const submit = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    if (error) clearError();
    void sendMessage({ text: trimmed });
    setInput('');
    textareaRef.current?.focus();
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submit(input);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit(input);
    }
  };

  const clearChat = () => {
    if (busy) void stop();
    setMessages([]);
    if (error) clearError();
  };

  const lastMessage = messages[messages.length - 1];
  const showThinking = status === 'submitted' || (status === 'streaming' && lastMessage?.role === 'user');

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-zinc-950">
      {/* Subheader / Context Management Bar */}
      <div className="flex items-center justify-between border-b border-zinc-800/80 bg-zinc-900/40 px-4 py-2 text-xs">
        <span className="text-zinc-400">
          Hafıza: <strong className="text-emerald-400">Tam Sohbet Geçmişi Aktif</strong>
        </span>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={clearChat}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md border border-zinc-700/60 px-2.5 py-1 text-zinc-300 hover:border-red-800 hover:bg-red-950/30 hover:text-red-300 transition-colors disabled:opacity-50"
            title="Sohbet geçmişini ve bağlam penceresini sıfırla"
          >
            <span>🗑️</span>
            <span>Sohbeti Sıfırla / Temizle</span>
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
          {messages.length === 0 && (
            <div className="flex flex-col items-center gap-6 py-12 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/15 text-3xl text-emerald-400 shadow-inner">
                💬
              </div>
              <div className="max-w-md">
                <h2 className="text-xl font-semibold text-zinc-100">Nasıl yardımcı olabilirim?</h2>
                <p className="mt-2 text-sm text-zinc-400 leading-relaxed">
                  İster günlük konularda dertleşip samimi sohbet edebilir, ister hassas hesaplama, saat sorgusu veya Türkçe PDF oluşturma görevleri verebilirsiniz.
                </p>
              </div>
              <div className="grid w-full gap-2.5 sm:grid-cols-2">
                {CONVERSATION_STARTERS.map((starter) => (
                  <button
                    key={starter}
                    type="button"
                    onClick={() => submit(starter)}
                    className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3.5 text-left text-xs text-zinc-300 hover:border-zinc-700 hover:bg-zinc-800/80 transition-all leading-normal"
                  >
                    {starter}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((message, index) => (
            <MessageBubble
              key={message.id}
              message={message}
              isStreaming={status === 'streaming' && index === messages.length - 1}
            />
          ))}

          {showThinking && (
            <div className="flex items-center gap-2 pl-11 text-sm text-zinc-500">
              <span className="flex gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500 [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500 [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500" />
              </span>
              <span>Düşünüyor ve yazıyor...</span>
            </div>
          )}

          {error && (
            <div className="flex flex-col gap-3 rounded-xl border border-red-900/60 bg-red-950/40 p-4 text-sm text-red-200 sm:flex-row sm:items-center">
              <span className="flex-1">⚠️ {readErrorMessage(error)}</span>
              <button
                type="button"
                onClick={() => void regenerate()}
                className="shrink-0 rounded-lg bg-red-900/60 px-3 py-1.5 text-xs font-medium hover:bg-red-800/70"
              >
                Yeniden Dene
              </button>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      <form onSubmit={onSubmit} className="border-t border-zinc-800 bg-zinc-950 px-4 py-3">
        <div className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-2xl border border-zinc-800 bg-zinc-900 p-2 focus-within:border-zinc-600">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Bir şeyler yazın veya sohbet edin..."
            className="max-h-48 min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-zinc-100 outline-none placeholder:text-zinc-500 [field-sizing:content]"
            autoFocus
          />
          {busy ? (
            <button
              type="button"
              onClick={() => void stop()}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-zinc-700 hover:bg-zinc-600 transition-colors"
              aria-label="Üretimi Durdur"
            >
              <span className="h-3 w-3 rounded-sm bg-zinc-100" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-600 text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500 transition-colors"
              aria-label="Mesaj Gönder"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2.5}>
                <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
        <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-zinc-500">
          Açık uçlu insansı sohbet ve otonom araç çalıştırma (PDF, Hesap Makinesi, Saat) desteklenir.
        </p>
      </form>
    </div>
  );
}
