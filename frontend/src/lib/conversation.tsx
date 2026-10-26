import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { askQuestion } from "../api/endpoints";
import type { AskResponse } from "../api/types";

export type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; question: string; response: AskResponse }
  | { id: number; role: "error"; question: string; message: string };

interface ConversationValue {
  messages: Message[];
  pending: string | null;
  ask: (question: string) => Promise<void>;
  clear: () => void;
}

const ConversationContext = createContext<ConversationValue | null>(null);

/**
 * The Ask AI conversation of the signed-in user. Kept in memory for the browser session only
 * (it survives moving between pages, and disappears on sign-out or reload): questions and
 * answers are logged on the server (assistant QuestionLog), not in the browser.
 */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const nextId = useRef(1);

  const ask = useCallback(async (question: string) => {
    const text = question.trim();
    if (!text) return;
    setMessages((m) => [...m, { id: nextId.current++, role: "user", text }]);
    setPending(text);
    try {
      const response = await askQuestion(text);
      setMessages((m) => [...m, { id: nextId.current++, role: "assistant", question: text, response }]);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.code === "network"
            ? "The DrukSmart server could not be reached. Check your connection and try again."
            : err.message
          : "The question could not be answered because of an unexpected error.";
      setMessages((m) => [...m, { id: nextId.current++, role: "error", question: text, message }]);
    } finally {
      setPending(null);
    }
  }, []);

  const clear = useCallback(() => setMessages([]), []);
  const value = useMemo(() => ({ messages, pending, ask, clear }), [messages, pending, ask, clear]);
  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}

export function useConversation(): ConversationValue {
  const value = useContext(ConversationContext);
  if (!value) throw new Error("useConversation must be used inside <ConversationProvider>");
  return value;
}
