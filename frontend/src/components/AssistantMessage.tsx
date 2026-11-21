import type { ChatMetadata } from "../api";
import { RichText } from "./RichText";

/** One assistant reply + its metadata. Each data-testid element holds ONLY its value;
 * labels live in sibling <dt> elements so automated checks read exact values. */
export function AssistantMessage({ content, metadata }: { content: string; metadata: ChatMetadata }) {
  const cached = metadata.resolution_source === "LLM_CACHE";
  const failedOver = metadata.fallback_attempts > 0;
  return (
    <div className="bubble assistant" data-testid="assistant-message">
      <p className="reply">
        <RichText text={content} />
      </p>
      <dl className="meta">
        <div className={`meta-item source ${cached ? "is-cache" : "is-live"}`}>
          <dt>Source</dt>
          <dd data-testid="meta-source">{metadata.resolution_source}</dd>
        </div>
        <div className="meta-item">
          <dt>Model</dt>
          <dd data-testid="meta-model">{metadata.model}</dd>
        </div>
        <div className="meta-item">
          <dt>Latency</dt>
          <dd data-testid="meta-latency">{metadata.latency_ms} ms</dd>
        </div>
        <div className="meta-item">
          <dt>Tokens in</dt>
          <dd data-testid="meta-input-tokens">{metadata.input_tokens}</dd>
        </div>
        <div className="meta-item">
          <dt>Tokens out</dt>
          <dd data-testid="meta-output-tokens">{metadata.output_tokens}</dd>
        </div>
        <div className={`meta-item ${failedOver ? "is-fallback" : ""}`}>
          <dt>Key</dt>
          <dd data-testid="meta-key">
            {metadata.key_id ?? "none (cache)"}
            {failedOver ? ` · ${metadata.fallback_attempts} failed before` : ""}
          </dd>
        </div>
      </dl>
    </div>
  );
}
