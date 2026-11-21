import { useEffect, useRef } from "react";
import type { ChatItem, RetryArgs } from "../types";
import { AssistantMessage } from "./AssistantMessage";

interface Props {
  items: ChatItem[];
  pending: boolean;
  slow: boolean;
  onRetry: (retry: RetryArgs) => void;
}

export function MessageList({ items, pending, slow, onRetry }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items, pending]);

  return (
    <main className="messages" aria-live="polite">
      {items.length === 0 && !pending && (
        <div className="empty">
          <h2>Start a conversation</h2>
          <p>Each reply shows where it came from (live model or cache), the model, latency and tokens.</p>
        </div>
      )}
      {items.map((item) => {
        if (item.kind === "user") {
          return (
            <div key={item.id} className={`bubble user ${item.failed ? "failed" : ""}`} data-testid="user-message">
              {item.content}
              {item.failed && <span className="failed-note">not sent</span>}
            </div>
          );
        }
        if (item.kind === "assistant") {
          return <AssistantMessage key={item.id} content={item.content} metadata={item.metadata} />;
        }
        return (
          <div key={item.id} className="bubble error" role="alert" data-testid="error-message">
            <span className="error-title">{item.status ? `Error ${item.status}` : "Connection problem"}</span>
            <span className="error-text">{item.content}</span>
            <button type="button" className="retry" onClick={() => onRetry(item.retry)} disabled={pending}>
              Retry
            </button>
          </div>
        );
      })}
      {pending && (
        <div className="bubble assistant typing" aria-label="Assistant is typing">
          <span className="dots">
            <i />
            <i />
            <i />
          </span>
          {slow && <span className="slow-note">Still working… the server may be waking up.</span>}
        </div>
      )}
      <div ref={endRef} />
    </main>
  );
}
