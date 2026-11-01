import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useStore } from "./store";

export function useRunCommand() {
  const { select, setWorkspace, setNotice } = useStore();
  const setAsk = useStore((s) => s.setPendingAsk);
  const setHelp = useStore((s) => s.setHelp);
  const setScan = useStore((s) => s.setPendingScan);
  const setBt = useStore((s) => s.setPendingBacktest);
  const setCompare = useStore((s) => s.setPendingCompare);
  return async (text: string) => {
    try {
      const c = await api.command(text);
      if (!c.ok) { setNotice(c.error ?? "Invalid command"); return false; }
      if (c.view === "help") { setHelp(true); setNotice(null); return true; }
      if (c.instrument_ids[0]) select(c.instrument_ids[0]);
      if (c.view) setWorkspace(c.view);
      if (c.view === "scanner" && typeof c.params.preset === "string") setScan(c.params.preset);
      if (c.view === "backtest" && typeof c.params.preset === "string") setBt(c.params.preset);
      if (Array.isArray(c.params.compare)) setCompare(c.params.compare as string[]);
      if (typeof c.params.ask === "string") setAsk(c.params.ask);
      if (c.params.brief) setAsk("Give me a technical brief on the selected instrument with bull/bear readings and invalidation.");
      setNotice(!c.implemented ? `${c.message ?? "Not built yet"}${c.phase ? ` (roadmap Phase ${c.phase})` : ""}` : c.message);
      return true;
    } catch (e) {
      setNotice((e as Error).message);
      return false;
    }
  };
}

export function CommandBar() {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(-1);
  const ref = useRef<HTMLInputElement>(null);
  const run = useRunCommand();
  const sug = useQuery({ queryKey: ["suggest", text], queryFn: () => api.suggest(text), enabled: open, staleTime: 5000 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); ref.current?.focus(); }
      else if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA") { e.preventDefault(); ref.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const items = text.trim() ? (sug.data?.suggestions ?? []).map((s) => ({ label: s.text, sub: s.name ?? s.kind, value: s.kind === "symbol" ? s.text : `${text.trim().split(/\s+/).slice(0, -1).concat(s.text).join(" ")}` }))
    : (sug.data?.recent ?? []).map((r) => ({ label: r, sub: "recent", value: r }));
  const submit = async (v: string) => { if (!v.trim()) return; if (await run(v)) { setText(""); setOpen(false); ref.current?.blur(); } };

  return (
    <div className="cmd">
      <input ref={ref} value={text} placeholder="Command or symbol  ( / or Ctrl+K )  e.g. BTC CHART · NVDA TECH · MACRO · HELP" aria-label="Command bar"
        onChange={(e) => { setText(e.target.value); setIdx(-1); }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, items.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, -1)); }
          else if (e.key === "Tab" && items[Math.max(idx, 0)]) { e.preventDefault(); setText(items[Math.max(idx, 0)].value + " "); }
          else if (e.key === "Enter") submit(idx >= 0 ? items[idx].value : text);
          else if (e.key === "Escape") { setText(""); ref.current?.blur(); }
        }} />
      {open && items.length > 0 && (
        <div className="dropdown">{items.map((s, i) => (
          <div key={s.label + i} className={`opt ${i === idx ? "act" : ""}`} onMouseDown={(e) => { e.preventDefault(); submit(s.value); }}>
            <b>{s.label}</b> <span className="dim">{s.sub}</span></div>))}</div>)}
    </div>
  );
}
