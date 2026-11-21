import { useState, type FormEvent, type KeyboardEvent } from "react";

const MAX_CHARS = 4000;

interface Props {
  disabled: boolean;
  onSend: (text: string) => void;
}

export function Composer({ disabled, onSend }: Props) {
  const [text, setText] = useState("");
  const length = text.trim().length;
  const tooLong = length > MAX_CHARS;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    if (disabled || !text.trim()) return; // only empty input is blocked client-side
    onSend(text);
    setText(""); // spec: input is empty after sending
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter adds a newline; never send mid IME composition.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        data-testid="chat-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
        rows={2}
        aria-label="Message"
        autoFocus
      />
      <div className="composer-side">
        <span className={`counter ${tooLong ? "over" : ""}`} title="Messages over 4000 characters are rejected by the server">
          {length}/{MAX_CHARS}
        </span>
        <button type="submit" data-testid="send-button" disabled={disabled || !text.trim()}>
          Send
        </button>
      </div>
    </form>
  );
}
