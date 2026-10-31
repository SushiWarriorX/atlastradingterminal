import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Instrument, isErr } from "../api";
import { dir, pct, px } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";

export function WatchlistWidget() {
  const qc = useQueryClient();
  const { selected, select } = useStore();
  const every = useStore((s) => s.updateSeconds) * 1000;
  const [active, setActive] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const lists = useQuery({ queryKey: ["watchlists"], queryFn: api.watchlists });
  const wl = lists.data?.find((w) => w.id === active) ?? lists.data?.[0];
  const quotes = useQuery({ queryKey: ["quotes", wl?.items.join()], queryFn: () => api.quotes(wl!.items), enabled: !!wl && wl.items.length > 0, refetchInterval: every });
  const found = useQuery({ queryKey: ["search", q], queryFn: () => api.search(q), enabled: q.trim().length > 0 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["watchlists"] });
  const add = useMutation({ mutationFn: (i: Instrument) => api.wlAdd(wl!.id, i.id), onSuccess: () => { setQ(""); refresh(); } });
  const rm = useMutation({ mutationFn: (id: string) => api.wlRemove(wl!.id, id), onSuccess: refresh });
  const create = useMutation({ mutationFn: (n: string) => api.wlCreate(n), onSuccess: (w) => { setActive(w.id); refresh(); } });
  const del = useMutation({ mutationFn: (id: number) => api.wlDelete(id), onSuccess: () => { setActive(null); refresh(); } });

  const byId = new Map((quotes.data ?? []).map((x) => [x.instrument_id, x]));
  return (
    <Panel title="WATCHLIST" right={wl && lists.data!.length > 1 && <button className="mini" onClick={() => confirm(`Delete watchlist "${wl.name}"?`) && del.mutate(wl.id)}>delete list</button>}>
      <div className="toolbar">
        {lists.data?.map((w) => <button key={w.id} className={`mini ${w.id === wl?.id ? "on" : ""}`} onClick={() => setActive(w.id)}>{w.name}</button>)}
        <button className="mini" onClick={() => { const n = prompt("New watchlist name"); if (n?.trim()) create.mutate(n.trim()); }}>+ list</button>
      </div>
      <div className="addrow">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Add symbol…" aria-label="Add symbol to watchlist" />
        {q && found.data && (
          <div className="dropdown">
            {found.data.slice(0, 6).map((i) => <div key={i.id} className="opt" onClick={() => add.mutate(i)}><b>{i.symbol}</b> <span className="dim">{i.name}{i.exchange === "UNVERIFIED" ? " · unverified" : ""}</span></div>)}
            {!found.data.length && <div className="opt dim">no match</div>}
          </div>)}
      </div>
      {lists.isError && <ErrorBox error={lists.error} />}
      <table className="tbl">
        <thead><tr><th>Symbol</th><th className="r">Last</th><th className="r">Chg%</th><th>Data</th><th /></tr></thead>
        <tbody>
          {wl?.items.map((id) => {
            const x = byId.get(id);
            const sym = id.split(":").slice(2, 3)[0] ?? id;
            return (
              <tr key={id} className={id === selected ? "sel" : ""} onClick={() => select(id)}>
                <td><b>{sym}</b></td>
                {x && !isErr(x) ? <>
                  <td className="r mono">{px(x.price)}</td>
                  <td className={`r mono ${dir(x.change_pct)}`}>{pct(x.change_pct)}</td>
                  <td><Badge status={x.prov.status} /></td></> : <>
                  <td className="r dim" colSpan={2} title={x && isErr(x) ? x.error : undefined}>{quotes.isLoading ? "…" : "no data"}</td>
                  <td><Badge status="UNAVAILABLE" title={x && isErr(x) ? x.error : "no quote"} /></td></>}
                <td className="r"><button className="mini" onClick={(e) => { e.stopPropagation(); rm.mutate(id); }} aria-label={`Remove ${sym}`}>✕</button></td>
              </tr>);
          })}
        </tbody>
      </table>
      {wl && !wl.items.length && <div className="note">Empty list. Search above to add symbols.</div>}
    </Panel>
  );
}
