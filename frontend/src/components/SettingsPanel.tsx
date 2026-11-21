interface Props {
  systemPrompt: string;
  onSystemPrompt: (value: string) => void;
  simulate: string;
  onSimulate: (value: string) => void;
}

export const SIMULATION_PRESETS = [
  { value: "", label: "None (normal request)" },
  { value: "key_1=429", label: "key_1 rate-limited (429) → expect key_2" },
  { value: "key_1=500", label: "key_1 server error (500) → expect key_2" },
  { value: "*=429", label: "All keys rate-limited → expect 503" },
];

export function SettingsPanel({ systemPrompt, onSystemPrompt, simulate, onSimulate }: Props) {
  return (
    <details className="settings">
      <summary>Session settings</summary>
      <div className="settings-body">
        <label className="field">
          <span>System prompt (optional, this session)</span>
          <textarea
            data-testid="system-prompt-input"
            value={systemPrompt}
            onChange={(e) => onSystemPrompt(e.target.value)}
            placeholder="e.g. You are a concise assistant. Answer in one sentence."
            rows={1}
            maxLength={4000}
          />
        </label>
        <label className="field">
          <span>Failover demo (X-Simulate-Failure, next message only)</span>
          <select data-testid="simulate-select" value={simulate} onChange={(e) => onSimulate(e.target.value)}>
            {SIMULATION_PRESETS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          <small>Needs ENABLE_FAILURE_SIMULATION=true on the backend.</small>
        </label>
      </div>
    </details>
  );
}
