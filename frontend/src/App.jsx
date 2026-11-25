import { useEffect, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const newSessionId = () =>
  "s-" + (crypto.randomUUID ? crypto.randomUUID().slice(0, 12) : Math.random().toString(36).slice(2, 14));

function readableError(status, data) {
  if (status === 503) return "All AI providers are unavailable right now. Try again in a moment.";
  if (status === 422) {
    const d = data?.detail;
    const msg = Array.isArray(d) ? d.map((x) => x.msg).join("; ") : d;
    return `Message not sent: ${msg || "invalid input"}. Check the message (1–4000 characters) and try again.`;
  }
  return data?.detail ? String(data.detail) : `Request failed (HTTP ${status}). Try again.`;
}

const SIMULATIONS = [
  ["", "No simulation"],
  ["key_1=429", "key_1 rate-limited (429)"],
  ["key_1=500", "key_1 server error (500)"],
  ["key_1=429,key_2=500", "key_1 and key_2 fail"],
  ["*=429", "All keys rate-limited"],
];

export default function App() {
  const [sessionId] = useState(newSessionId); // new session on every page load
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setLoading(true);
    try {
      const headers = { "Content-Type": "application/json" };
      if (simulate) headers["X-Simulate-Failure"] = simulate;
      const body = { session_id: sessionId, message: text };
      if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
      const res = await fetch(`${API}/chat`, { method: "POST", headers, body: JSON.stringify(body) });
      let data = null;
      try { data = await res.json(); } catch { /* non-JSON body */ }
      if (!res.ok) throw new Error(readableError(res.status, data));
      setMessages((m) => [...m, { role: "assistant", content: data.reply, metadata: data.metadata }]);
    } catch (e) {
      const msg = e instanceof TypeError ? "Can't reach the server. Check your connection and try again." : e.message;
      setMessages((m) => [...m, { role: "error", content: msg }]);
    } finally {
      setLoading(false);
    }
  }

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <div className="app">
      <header>
        <h1>Chat</h1>
        <span className="sid">session {sessionId}</span>
      </header>

      <details className="settings">
        <summary>Session settings</summary>
        <label>
          System prompt
          <textarea
            data-testid="system-prompt-input" rows={2} value={systemPrompt}
            placeholder="You are a helpful, concise assistant."
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </label>
        <label>
          Simulate provider failure (demo)
          <select value={simulate} onChange={(e) => setSimulate(e.target.value)}>
            {SIMULATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </details>

      <main className="thread" aria-live="polite">
        {messages.length === 0 && <p className="empty">Ask anything to start the conversation.</p>}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg user">{m.content}</div>
          ) : m.role === "error" ? (
            <div key={i} className="msg error" role="alert">{m.content}</div>
          ) : (
            <div key={i} className="msg assistant" data-testid="assistant-message">
              <div className="text">{m.content}</div>
              <dl className="meta">
                <div><dt>Source</dt>
                  <dd data-testid="meta-source" className={m.metadata.resolution_source === "LLM_CACHE" ? "cache" : "live"}>
                    {m.metadata.resolution_source}
                  </dd></div>
                <div><dt>Model</dt><dd data-testid="meta-model">{m.metadata.model}</dd></div>
                <div><dt>Latency</dt><dd data-testid="meta-latency">{m.metadata.latency_ms} ms</dd></div>
                <div><dt>Input tokens</dt><dd data-testid="meta-input-tokens">{m.metadata.input_tokens}</dd></div>
                <div><dt>Output tokens</dt><dd data-testid="meta-output-tokens">{m.metadata.output_tokens}</dd></div>
                <div><dt>Key</dt><dd>{m.metadata.key_id ?? "cache"}{m.metadata.fallback_attempts > 0 ? ` (after ${m.metadata.fallback_attempts} failed)` : ""}</dd></div>
              </dl>
            </div>
          )
        )}
        {loading && <div className="msg assistant pending">Thinking…</div>}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea
          data-testid="chat-input" rows={2} value={input} placeholder="Type a message. Enter sends, Shift+Enter adds a line."
          onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} aria-label="Message"
        />
        <button data-testid="send-button" onClick={send} disabled={loading}>Send</button>
      </footer>
    </div>
  );
}
