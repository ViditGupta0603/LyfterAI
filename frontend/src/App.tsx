import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, ApiError, getHealth, sendChat, type Health } from "./api";
import { Composer } from "./components/Composer";
import { MessageList } from "./components/MessageList";
import { SettingsPanel } from "./components/SettingsPanel";
import { newSessionId } from "./session";
import type { ChatItem, RetryArgs } from "./types";

const SLOW_AFTER_MS = 5000;
let counter = 0;
const nextId = () => `m${++counter}`;

export default function App() {
  const [sessionId] = useState(newSessionId); // new session on every page load
  const [items, setItems] = useState<ChatItem[]>([]);
  const [pending, setPending] = useState(false);
  const [slow, setSlow] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [health, setHealth] = useState<Health | "down" | null>(null);
  const inFlight = useRef(false);

  useEffect(() => {
    getHealth().then(setHealth, () => setHealth("down"));
  }, []);

  const send = useCallback(
    async (message: string, existingUserItemId?: string) => {
      if (inFlight.current) return; // no double submits
      inFlight.current = true;

      const userItemId = existingUserItemId ?? nextId();
      setItems((prev) => {
        // A retry re-sends an existing message: un-mark it and drop its error bubble.
        const cleaned = existingUserItemId
          ? prev
              .filter((it) => !(it.kind === "error" && it.retry.userItemId === existingUserItemId))
              .map((it) => (it.id === existingUserItemId && it.kind === "user" ? { ...it, failed: false } : it))
          : [...prev, { id: userItemId, kind: "user" as const, content: message }];
        return cleaned;
      });

      const simulateFailure = simulate;
      setSimulate(""); // the demo header is one-shot
      setPending(true);
      setSlow(false);
      const slowTimer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);

      try {
        const res = await sendChat({ sessionId, message, systemPrompt, simulateFailure });
        setItems((prev) => [...prev, { id: nextId(), kind: "assistant", content: res.reply, metadata: res.metadata }]);
      } catch (err) {
        const e = err instanceof ApiError ? err : new ApiError("Something went wrong. Please try again.", null);
        setItems((prev) => [
          ...prev.map((it) => (it.id === userItemId && it.kind === "user" ? { ...it, failed: true } : it)),
          { id: nextId(), kind: "error", content: e.message, status: e.status, retry: { message, userItemId } },
        ]);
      } finally {
        clearTimeout(slowTimer);
        setPending(false);
        setSlow(false);
        inFlight.current = false;
      }
    },
    [sessionId, systemPrompt, simulate],
  );

  const onRetry = useCallback((r: RetryArgs) => send(r.message, r.userItemId), [send]);

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Lyftr Chat</h1>
          <p className="session" title="A new session starts on every page load">
            Session <code>{sessionId}</code>
          </p>
        </div>
        <HealthBadge health={health} />
      </header>
      <SettingsPanel
        systemPrompt={systemPrompt}
        onSystemPrompt={setSystemPrompt}
        simulate={simulate}
        onSimulate={setSimulate}
      />
      <MessageList items={items} pending={pending} slow={slow} onRetry={onRetry} />
      <Composer disabled={pending} onSend={(text) => send(text)} />
    </div>
  );
}

function HealthBadge({ health }: { health: Health | "down" | null }) {
  if (health === null) return <span className="health checking">Connecting…</span>;
  if (health === "down")
    return (
      <span className="health down" title={API_URL}>
        Backend unreachable
      </span>
    );
  return (
    <span className="health up" title={`${API_URL} · ${health.model ?? ""}`}>
      Online · {health.keys_configured} keys · cache {health.cache_enabled ? "on" : "off"}
    </span>
  );
}
