import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiFailure } from "../api";
import { useDebounced } from "../hooks";
import { ago } from "../fmt";
import { useSelectedId } from "../scope";
import { Badge, ErrorBox, Panel } from "../ui";

const symbolOf = (id: string) => { const p = id.split(":"); return p[0] === "CRYPTO" ? p[2] : p[p.length - 1]; };
const when = (iso: string | null) => (iso ? new Date(iso).toISOString().replace("T", " ").slice(0, 16) + " UTC" : "time not given");
const err = (e: unknown) => (e instanceof ApiFailure ? e.message : String(e));

export function NewsWidget() {
  const qc = useQueryClient();
  const selected = useSelectedId();
  const sym = symbolOf(selected);
  const [scope, setScope] = useState<"all" | "symbol">("all");
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const dq = useDebounced(q);
  const news = useQuery({ queryKey: ["news", scope, sym, dq], queryFn: () => api.news({ symbol: scope === "symbol" ? sym : undefined, q: dq.trim() || undefined }), refetchInterval: 120_000, retry: 0 });
  const refresh = useMutation({
    mutationFn: () => api.newsRefresh(),
    onSuccess: (r) => { const bad = r.results.filter((x) => !x.ok).length; setMsg(`Fetched ${r.results.length} feeds: ${r.results.reduce((a, x) => a + x.new, 0)} new headlines${bad ? `, ${bad} failed (see the feeds panel)` : ""}.`); qc.invalidateQueries({ queryKey: ["news"] }); qc.invalidateQueries({ queryKey: ["news-feeds"] }); },
    onError: (e) => setMsg(err(e)),
  });
  const d = news.data;
  const m = d?.meta;
  return (
    <Panel title={scope === "symbol" ? `NEWS ${sym}` : "NEWS"} right={m && <span className="dim">{m.feeds_ok}/{m.feeds_enabled} feeds ok{m.as_of ? ` · updated ${ago(m.as_of)}` : ""}</span>} className="news">
      <div className="toolbar">
        <button className={`mini ${scope === "all" ? "on" : ""}`} onClick={() => setScope("all")}>All headlines</button>
        <button className={`mini ${scope === "symbol" ? "on" : ""}`} onClick={() => setScope("symbol")} title="Headlines that explicitly name the selected symbol">{sym}</button>
        <input className="fval" style={{ width: 170 }} placeholder="search headlines" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search headlines" />
        <Badge status="DELAYED" title="RSS is polled every 15 minutes: not real time" />
        <button className="mini on spacer" disabled={refresh.isPending} onClick={() => refresh.mutate()}>{refresh.isPending ? "fetching…" : "refresh feeds"}</button>
      </div>
      {msg && <div className="note" onClick={() => setMsg(null)}>{msg}</div>}
      {news.isError && <ErrorBox error={news.error} />}
      {m && m.never_fetched > 0 && !m.as_of && <div className="note warn">⚠ No feed has been fetched yet. Press "refresh feeds". Nothing is shown until a real feed answers; there are no placeholder headlines.</div>}
      {m && m.feeds_failing.length > 0 && (
        <div className="note warn" title={m.feeds_failing.map((f) => `${f.name}: ${f.error}`).join("\n")}>⚠ {m.feeds_failing.length} feed(s) failing: {m.feeds_failing.map((f) => f.name).join(", ")} (hover for reasons)</div>)}
      {m?.symbol_fetch && !m.symbol_fetch.ok && <div className="note warn">⚠ Per-symbol headlines unavailable: {m.symbol_fetch.error}</div>}
      <div className="results news-list">
        {d?.items.map((it) => (
          <div key={it.id} className="news-item">
            <div className="news-h">
              {it.link ? <a href={it.link} target="_blank" rel="noopener noreferrer">{it.title}</a> : <span>{it.title}</span>}
              {it.symbols.map((s) => <span key={s} className="badge DEMO" style={{ background: "transparent", border: "1px solid var(--border)", color: "var(--accent)" }} title="The headline names this symbol explicitly. A tag is not relevance or sentiment.">{s}</span>)}
            </div>
            <div className="dim small" title={`${when(it.published)} · fetched ${when(it.fetched_at)}`}>
              {it.feed} · {it.published ? ago(it.published) : "no publish time"}
              {it.also.length > 0 && <span title={it.also.map((a) => `${a.feed}: ${a.title}`).join("\n")}> · also reported by {it.also.map((a) => a.feed).join(", ")}</span>}
            </div>
            {it.summary && <div className="small news-s">{it.summary}</div>}
          </div>))}
        {d && !d.items.length && <div className="note">{q ? "No headline matches that search." : scope === "symbol" ? `No headline in the last 72 hours names ${sym} explicitly. Tags are conservative ($${sym} or (NASDAQ: ${sym}) in the headline).` : "No headlines stored yet."}</div>}
      </div>
      {m && <div className="note">{d?.total_stories} stories from {d?.raw_items} headlines (near-duplicates grouped). {m.note}</div>}
    </Panel>
  );
}

export function NewsFeedsWidget() {
  const qc = useQueryClient();
  const feeds = useQuery({ queryKey: ["news-feeds"], queryFn: api.newsFeeds, refetchInterval: 30_000 });
  const [f, setF] = useState({ name: "", url: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const inv = () => { qc.invalidateQueries({ queryKey: ["news-feeds"] }); qc.invalidateQueries({ queryKey: ["news"] }); };
  const add = useMutation({ mutationFn: () => api.newsFeedAdd(f.name.trim(), f.url.trim()), onSuccess: () => { setF({ name: "", url: "" }); setMsg({ ok: true, text: "Feed added. Press “refresh feeds” in the news panel to fetch it." }); inv(); }, onError: (e) => setMsg({ ok: false, text: err(e) }) });
  const toggle = useMutation({ mutationFn: (x: { id: number; enabled: boolean }) => api.newsFeedToggle(x.id, x.enabled), onSuccess: inv });
  const del = useMutation({ mutationFn: (id: number) => api.newsFeedDelete(id), onSuccess: inv });
  return (
    <Panel title="NEWS FEEDS">
      {feeds.isError && <ErrorBox error={feeds.error} />}
      <table className="tbl"><thead><tr><th /><th>Feed</th><th>Health</th><th className="r">Items</th><th /></tr></thead>
        <tbody>{feeds.data?.feeds.map((x) => (
          <tr key={x.id} className={x.enabled ? "" : "dim"}>
            <td><input type="checkbox" checked={x.enabled} aria-label={`Enable ${x.name}`} onChange={(e) => toggle.mutate({ id: x.id, enabled: e.target.checked })} /></td>
            <td title={x.url}><b>{x.name}</b><div className="dim small mono">{x.url}</div></td>
            <td className="small">{x.last_error ? <span className="down" title={x.last_error}>✕ {x.last_error}</span> : x.last_ok ? <span className="up">✓ {ago(x.last_ok)}</span> : <span className="dim">not fetched</span>}</td>
            <td className="r mono">{x.items}</td>
            <td className="r"><button className="mini" aria-label={`Remove ${x.name}`} onClick={() => confirm(`Remove "${x.name}" and its stored headlines?`) && del.mutate(x.id)}>✕</button></td></tr>))}</tbody></table>
      <div className="aform"><div className="aform-h">ADD A FEED (RSS or Atom, http/https)</div>
        <div className="frow"><input className="w140" placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} aria-label="Feed name" />
          <input className="fval" style={{ width: 300 }} placeholder="https://example.com/feed.xml" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} aria-label="Feed URL" spellCheck={false} />
          <button className="mini on" disabled={add.isPending || !f.name.trim() || !f.url.trim()} onClick={() => add.mutate()}>Add</button></div></div>
      {msg && <div className={`note ${msg.ok ? "" : "warn"}`} onClick={() => setMsg(null)}>{msg.text}</div>}
      <div className="note">{feeds.data?.note} Only headline, link and a short summary are stored, for 14 days. Respect each publisher's terms. Feed URLs with a key in the query string are shown masked.</div>
    </Panel>
  );
}
