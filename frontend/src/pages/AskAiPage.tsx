import {
  ArrowRight,
  Bot,
  CircleAlert,
  Info,
  RotateCcw,
  SendHorizontal,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserRound,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import { fetchAssistantInfo } from "../api/endpoints";
import type { AskResponse, AssistantInfo, KpiResult } from "../api/types";
import { canAccess } from "../auth/access";
import { useCurrentUser } from "../auth/session";
import { ResultChart, ResultTable } from "../components/data/ResultView";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import type { Tone } from "../components/ui/Badge";
import { Button, ButtonLink } from "../components/ui/Button";
import { EmptyState, ErrorState, LoadingState, Spinner } from "../components/ui/States";
import { useConversation } from "../lib/conversation";
import type { Message } from "../lib/conversation";
import { formatAge, formatDate, formatPeriod } from "../lib/format";
import { useApi } from "../lib/useApi";
import { PAGES } from "../navigation";

const STATUS: Record<string, [string, Tone]> = {
  answered: ["Answer from warehouse data", "success"],
  clarification_needed: ["Needs clarification", "warning"],
  unsupported: ["Not supported", "neutral"],
  forbidden: ["Not authorised", "danger"],
  invalid_filter: ["Check your filter", "warning"],
  no_data: ["No matching data", "neutral"],
  invalid_request: ["Invalid question", "warning"],
  error: ["Service unavailable", "danger"],
};

function interpreterLabel(response: AskResponse): string {
  if (response.llm_used) return `Interpreted by ${response.interpreter} (language model)`;
  const detail = response.interpreter && response.interpreter !== "rules" ? ` · ${response.interpreter}` : "";
  return `Deterministic rules, no language model${detail}`;
}

function ResultDetails({ result }: { result: KpiResult }) {
  const user = useCurrentUser();
  const page = result.domain === "hr" ? PAGES.hr : PAGES.accounts;
  return (
    <div className="answer__result">
      <div className="answer__meta">
        <Badge tone="neutral">
          {result.title} · {result.kpi_ids.join(", ")}
        </Badge>
        <Badge tone="neutral">{result.as_of ? `As of ${formatDate(result.as_of)}` : formatPeriod(result.period)}</Badge>
        {Object.entries(result.filters).map(([k, v]) => (
          <Badge key={k} tone="info">
            {k}: {v}
          </Badge>
        ))}
        {result.branch_restricted && <Badge tone="info">Limited to your branch</Badge>}
        <Badge tone={result.stale ? "warning" : "success"}>Refreshed {formatAge(result.hours_since_publication)}</Badge>
        {result.stale && <Badge tone="warning">Data may be out of date</Badge>}
        {result.synthetic && <Badge tone="danger">Synthetic demonstration data</Badge>}
      </div>
      <ResultChart result={result} />
      <details className="answer__table">
        <summary>Show the figures as a table ({result.rows.length} rows)</summary>
        <ResultTable result={result} caption={result.title} />
      </details>
      {canAccess(user, page.requires) && (
        <ButtonLink to={page.path} size="sm" icon={<ArrowRight size={16} aria-hidden="true" />}>
          Explore in {page.label}
        </ButtonLink>
      )}
    </div>
  );
}

function AssistantMessage({ message, onAsk }: { message: Extract<Message, { role: "assistant" }>; onAsk: (q: string) => void }) {
  const { response } = message;
  const [label, tone] = STATUS[response.status] ?? [response.status, "neutral" as Tone];
  return (
    <article className="msg msg--assistant" aria-label="Assistant answer">
      <span className="msg__avatar" aria-hidden="true">
        <Bot size={18} />
      </span>
      <div className="msg__body">
        <div className="msg__head">
          <Badge tone={tone}>{label}</Badge>
          <span className="msg__by">{interpreterLabel(response)}</span>
        </div>
        <p className="answer__text">{response.answer}</p>
        {response.options.length > 0 && (
          <div className="chips" aria-label="Suggested questions">
            {response.options.map((option) => (
              <button key={option} type="button" className="chip" onClick={() => onAsk(option)}>
                {option}
              </button>
            ))}
          </div>
        )}
        {response.result && <ResultDetails result={response.result} />}
        {response.notes.length > 0 && (
          <ul className="answer__notes">
            {response.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

function Conversation({ onAsk }: { onAsk: (q: string) => void }) {
  const { messages, pending } = useConversation();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [messages.length, pending]);

  return (
    <div className="conversation" role="log" aria-live="polite" aria-label="Conversation">
      {messages.map((m) =>
        m.role === "user" ? (
          <article key={m.id} className="msg msg--user" aria-label="You asked">
            <div className="msg__body">
              <p>{m.text}</p>
            </div>
            <span className="msg__avatar" aria-hidden="true">
              <UserRound size={18} />
            </span>
          </article>
        ) : m.role === "assistant" ? (
          <AssistantMessage key={m.id} message={m} onAsk={onAsk} />
        ) : (
          <article key={m.id} className="msg msg--assistant msg--error" aria-label="Error">
            <span className="msg__avatar" aria-hidden="true">
              <CircleAlert size={18} />
            </span>
            <div className="msg__body" role="alert">
              <p>{m.message}</p>
              <Button variant="secondary" size="sm" icon={<RotateCcw size={14} aria-hidden="true" />} onClick={() => onAsk(m.question)}>
                Ask again
              </Button>
            </div>
          </article>
        ),
      )}
      {pending && (
        <article className="msg msg--assistant" aria-label="Assistant is working">
          <span className="msg__avatar" aria-hidden="true">
            <Bot size={18} />
          </span>
          <div className="msg__body msg__body--pending">
            <Spinner label="Looking up approved KPIs" />
            <span>Looking up approved KPIs…</span>
          </div>
        </article>
      )}
      <div ref={endRef} />
    </div>
  );
}

function Composer({ info, onAsk, disabled }: { info: AssistantInfo; onAsk: (q: string) => void; disabled: boolean }) {
  const [text, setText] = useState("");
  const counterId = useId();
  const limit = info.max_question_length;

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const question = text.trim();
    if (!question || question.length > limit || disabled) return;
    onAsk(question);
    setText("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) submit(event);
  }

  return (
    <form className="composer" onSubmit={submit}>
      <label htmlFor="question" className="visually-hidden">
        Your question
      </label>
      <textarea
        id="question"
        className="composer__input"
        rows={2}
        placeholder="Ask about headcount, leave, receivables, payables or overdue balances…"
        value={text}
        maxLength={limit}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        aria-describedby={counterId}
      />
      <div className="composer__bar">
        <span id={counterId} className="composer__hint">
          Enter to send · Shift+Enter for a new line · {text.length}/{limit}
        </span>
        <Button type="submit" disabled={disabled || !text.trim()} icon={<SendHorizontal size={16} aria-hidden="true" />}>
          Ask
        </Button>
      </div>
    </form>
  );
}

export function AskAiPage() {
  const user = useCurrentUser();
  const info = useApi((signal) => fetchAssistantInfo(signal), user.username);
  const { messages, pending, ask, clear } = useConversation();

  return (
    <>
      <PageHeader
        title={PAGES.ask.label}
        description={PAGES.ask.description}
        actions={
          messages.length > 0 ? (
            <Button variant="ghost" size="sm" icon={<Trash2 size={16} aria-hidden="true" />} onClick={clear}>
              Clear conversation
            </Button>
          ) : undefined
        }
      />
      {info.status === "loading" && <LoadingState message="Preparing the assistant…" />}
      {info.status === "error" && <ErrorState message={info.error.message} onRetry={info.reload} />}
      {info.status === "ready" && (
        <div className="ask">
          <section className="ask__main" aria-label="Assistant">
            {messages.length === 0 && !pending ? (
              <EmptyState
                icon={<Sparkles size={28} />}
                title="Ask a question about your HR or Accounts data"
                message="Answers come only from approved KPI functions over the validated warehouse, limited to your role and branch. Try one of the suggested questions."
              />
            ) : (
              <Conversation onAsk={ask} />
            )}
            <Composer info={info.data} onAsk={ask} disabled={pending !== null} />
          </section>
          <aside className="ask__side" aria-label="Suggestions and how answers work">
            <div className="card side-card">
              <h2 className="side-card__title">Suggested questions</h2>
              <ul className="suggestions">
                {info.data.suggestions.map((s) => (
                  <li key={s.question}>
                    <button type="button" className="suggestion" onClick={() => ask(s.question)} disabled={pending !== null}>
                      <span>{s.question}</span>
                      <Badge tone="neutral">{s.domain === "hr" ? "HR" : "Accounts"}</Badge>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="card side-card">
              <h2 className="side-card__title">
                <ShieldCheck size={16} aria-hidden="true" /> How answers work
              </h2>
              <ul className="side-card__list">
                <li>Your question is matched to one approved KPI function; no free SQL is ever run.</li>
                <li>Your role and branch are applied by the server before any data is read.</li>
                <li>Every number in an answer comes from the validated warehouse.</li>
                <li>
                  <Info size={14} aria-hidden="true" /> Interpreter:{" "}
                  {info.data.provider.llm
                    ? `${info.data.provider.provider} language model (${info.data.provider.model})`
                    : "deterministic rules (no language model)"}
                  .
                </li>
              </ul>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
