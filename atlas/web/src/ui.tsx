import { ReactNode } from "react";
import { ApiFailure, Prov, Status } from "./api";
import { ago } from "./fmt";

const TIPS: Record<Status, string> = {
  LIVE: "Real-time from the provider", DELAYED: "Provider data is delayed", HISTORICAL: "Last available observation (market closed or periodic series)",
  STALE: "Data is older than the allowed freshness window", DEMO: "Synthetic demo data: NOT market data", UNAVAILABLE: "No data from the provider",
};

export function Badge({ status, title }: { status: Status; title?: string }) {
  return <span className={`badge ${status}`} title={title ?? TIPS[status]}>{status}</span>;
}

export function ProvLine({ prov, extra }: { prov: Prov; extra?: string }) {
  const tip = [`provider: ${prov.provider}`, `venue: ${prov.venue ?? "—"}`, `entitlement: ${prov.entitlement}`,
    `event: ${prov.event_time ?? "—"}`, `ingested: ${prov.ingested_time}`, ...prov.quality].join("\n");
  return (
    <span className="prov" title={tip}>
      <Badge status={prov.status} /> {prov.provider}{prov.venue ? `/${prov.venue}` : ""} · {ago(prov.event_time)}{extra ? ` · ${extra}` : ""}
    </span>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const e = error instanceof ApiFailure ? error : null;
  return (
    <div className="errbox">
      <Badge status="UNAVAILABLE" />
      <div>{e ? e.message : String(error)}</div>
      {e?.code && <div className="dim mono">{e.code}</div>}
    </div>
  );
}

export function Panel({ title, right, children, className = "" }: { title: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`panel ${className}`}>
      <div className="panel-h"><span className="panel-t">{title}</span><span className="panel-r">{right}</span></div>
      <div className="panel-b">{children}</div>
    </div>
  );
}
