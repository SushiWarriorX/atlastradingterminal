import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, errText } from "../api";
import { browserCopyEnv, CHATGPT_URL, COPIED, COPY_FAILED, downloadMarkdown, openChatGpt, POPUP_BLOCKED, startCopy } from "../handoff";

type Status = { kind: "ok" | "warn" | "info"; text: string } | null;

/** "Ask ChatGPT": a manual research handoff. The brief is built locally from research the app already holds (no AI call, no key); I copy it and paste it into ChatGPT myself. */
export function AskChatGpt({ symbol, where }: { symbol: string; where: "research" | "valuation" | "scenario" }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [debounced, setDebounced] = useState("");
  const [detail, setDetail] = useState<"concise" | "detailed">("concise");
  const [notes, setNotes] = useState(false);
  const [position, setPosition] = useState(false);
  const [shares, setShares] = useState("");
  const [buy, setBuy] = useState("");
  const [status, setStatus] = useState<Status>(null);
  const [blocked, setBlocked] = useState(false);
  const preview = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { const t = setTimeout(() => setDebounced(question), 400); return () => clearTimeout(t); }, [question]);
  const body = { detail, question: debounced.trim() || undefined, include_notes: notes, include_position: position, shares: position && Number(shares) > 0 ? Number(shares) : undefined, buy_price: position && Number(buy) > 0 ? Number(buy) : undefined };
  const q = useQuery({ queryKey: ["brief", symbol, JSON.stringify(body)], queryFn: () => api.researchBrief(symbol, body), enabled: open, retry: 0, staleTime: 0, gcTime: 60_000, placeholderData: (prev) => prev });
  const d = q.data;
  const updating = q.isFetching;                                          // the preview stays visible while a changed option is being rebuilt, but nothing can be copied until it is current
  const text = d?.markdown ?? "";

  const copyOpen = async () => {
    if (!text) return;
    setBlocked(false);
    const copying = startCopy(text, browserCopyEnv(preview.current));      // started inside the click, so the browser accepts it
    const opened = openChatGpt((u, t) => window.open(u, t));
    const copied = await copying;
    if (!opened) setBlocked(true);
    if (!copied) { preview.current?.focus(); preview.current?.select(); setStatus({ kind: "warn", text: COPY_FAILED + (opened ? "" : " " + POPUP_BLOCKED) }); return; }
    setStatus(opened ? { kind: "ok", text: COPIED } : { kind: "warn", text: `${COPIED} ${POPUP_BLOCKED}` });
  };
  const copyOnly = async () => {
    if (!text) return;
    const copied = await startCopy(text, browserCopyEnv(preview.current));
    if (!copied) { preview.current?.focus(); preview.current?.select(); setStatus({ kind: "warn", text: COPY_FAILED }); return; }
    setStatus({ kind: "ok", text: COPIED });
  };
  const download = () => { if (!d) return; downloadMarkdown(d.filename, d.markdown); setStatus({ kind: "info", text: `Download started: ${d.filename}` }); };

  return (
    <span data-testid={`ask-${where}`}>
      <button className="mini" onClick={() => setOpen(!open)} aria-expanded={open} data-testid="ask-chatgpt-button">Ask ChatGPT</button>
      {open && (
        <div className="note" data-testid="ask-panel" style={{ marginTop: 6 }}>
          <div className="small"><b>Ask ChatGPT about {symbol}</b> <span className="dim">· {where === "valuation" ? "valuation view" : where === "scenario" ? "position scenario" : "research page"}</span></div>
          <div className="small dim" data-testid="ask-explanation">{d?.explanation ?? "This handoff makes no AI API calls from this app. ChatGPT usage is subject to your own account's plan and limits."}</div>
          <label className="small" style={{ display: "block", marginTop: 6 }}>What would you like to research? <span className="dim">(optional)</span>
            <textarea aria-label="What would you like to research?" data-testid="ask-question" rows={2} maxLength={2000} value={question} onChange={(e) => setQuestion(e.target.value)} style={{ width: "100%" }}
              placeholder="e.g. How durable is the recurring revenue? Leave empty for the default questions." /></label>
          <div className="small" style={{ marginTop: 4 }}>
            <label><input type="radio" name={`detail-${where}`} checked={detail === "concise"} onChange={() => setDetail("concise")} data-testid="ask-concise" /> Concise brief</label>{" "}
            <label><input type="radio" name={`detail-${where}`} checked={detail === "detailed"} onChange={() => setDetail("detailed")} data-testid="ask-detailed" /> Detailed brief</label>
          </div>
          <div className="small">
            <label><input type="checkbox" checked={notes} onChange={(e) => setNotes(e.target.checked)} data-testid="ask-include-notes" /> Include my private notes</label>{" "}
            <label><input type="checkbox" checked={position} onChange={(e) => setPosition(e.target.checked)} data-testid="ask-include-position" /> Include my holdings (shares and buy price)</label>
            <span className="dim"> · both are left out unless you switch them on</span>
          </div>
          {position && <div className="small">Shares <input aria-label="Shares" className="mono" style={{ width: 70 }} inputMode="decimal" value={shares} onChange={(e) => setShares(e.target.value)} data-testid="ask-shares" /> · buy price $<input aria-label="Buy price" className="mono" style={{ width: 70 }} inputMode="decimal" value={buy} onChange={(e) => setBuy(e.target.value)} data-testid="ask-buy" /> <span className="dim">(typed here, sent only into the brief)</span></div>}
          {(q.isLoading || updating) && <div className="small dim" data-testid="ask-updating">{q.isLoading ? "Preparing the context…" : "Updating the preview…"}</div>}
          {q.isError && <div className="small warnc" data-testid="ask-error">{errText(q.error)}</div>}
          {d && <>
            <div className="small dim" data-testid="ask-meta">Preview of the context that will be copied · {d.chars.toLocaleString()} characters · {d.detail} · private notes {d.included.notes ? "INCLUDED" : "not included"} · holdings {d.included.position ? "INCLUDED" : "not included"}{d.redactions ? ` · ${d.redactions} item(s) that looked like emails or keys were removed` : ""}</div>
            <textarea ref={preview} readOnly aria-label="Context preview" data-testid="ask-preview" value={text} rows={12} style={{ width: "100%", fontFamily: "var(--mono, monospace)", fontSize: 11 }} onFocus={(e) => e.currentTarget.select()} />
          </>}
          <div style={{ marginTop: 6 }}>
            <button className="mini on" disabled={!text || updating} onClick={copyOpen} data-testid="ask-copy-open">Copy context &amp; open ChatGPT</button>{" "}
            <button className="mini" disabled={!text || updating} onClick={copyOnly} data-testid="ask-copy">Copy context only</button>{" "}
            <button className="mini" disabled={!d || updating} onClick={download} data-testid="ask-download">Download context as Markdown</button>{" "}
            <a href={CHATGPT_URL} target="_blank" rel="noopener noreferrer" data-testid="ask-open-link" className="small" style={{ color: "var(--accent)", textDecoration: "underline", fontWeight: 600 }}>Open ChatGPT</a>
          </div>
          {status && <div className={`small ${status.kind === "warn" ? "warnc" : ""}`} role="status" data-testid="ask-status" data-kind={status.kind}>{status.text}</div>}
          {blocked && <div className="small warnc" data-testid="ask-blocked">{POPUP_BLOCKED}</div>}
        </div>)}
    </span>);
}
