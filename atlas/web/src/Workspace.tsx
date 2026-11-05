import { useEffect, useMemo, useRef } from "react";
import RGL, { Layout, WidthProvider } from "react-grid-layout";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { api } from "./api";
import { WidgetCfg, WORKSPACES } from "./workspaces";
import { ChartWidget } from "./widgets/Chart";
import { WatchlistWidget } from "./widgets/Watchlist";
import { HealthWidget, QuoteWidget, TechWidget, UnavailableWidget, YieldsWidget } from "./widgets/Info";
import { AIWidget } from "./widgets/AI";
import { ScannerWidget } from "./widgets/Scanner";
import { BacktestWidget } from "./widgets/Backtest";
import { NewsFeedsWidget, NewsWidget } from "./widgets/News";
import { ScopeContext } from "./scope";
import { DerivativesWidget } from "./widgets/Derivatives";
import { MtfWidget } from "./widgets/Mtf";
import { JournalEditorWidget, JournalImportWidget, JournalSourcesWidget, JournalTradesWidget, PerformanceWidget2 } from "./widgets/Journal";
import { SettingsWidget } from "./widgets/Settings";
import { MacroDashboard } from "./widgets/Macro";
import { StatsStrip } from "./widgets/StatsStrip";
import { EarningsWidget, StockResearchWidget } from "./widgets/StockResearch";
import { JournalQuickWidget } from "./widgets/JournalQuick";

const Grid = WidthProvider(RGL);

function render(w: WidgetCfg, view: string) {
  const p = w.props ?? {};
  switch (w.type) {
    case "chart": return <ChartWidget instrumentId={p.id} defaultInterval={p.interval} title={p.title} wid={`${view}.${w.i}`} pick={p.pick as "any" | "equity" | undefined} />;
    case "watchlist": return <WatchlistWidget />;
    case "quote": return <QuoteWidget instrumentId={p.id} />;
    case "tech": return <TechWidget />;
    case "ai": return <AIWidget />;
    case "scanner": return <ScannerWidget />;
    case "backtest": return <BacktestWidget />;
    case "news": return <NewsWidget />;
    case "derivatives": return <DerivativesWidget />;
    case "newsfeeds": return <NewsFeedsWidget />;
    case "mtf": return <MtfWidget />;
    case "stockresearch": return <StockResearchWidget />;
    case "earnings": return <EarningsWidget />;
    case "journalquick": return <JournalQuickWidget />;
    case "journaltrades": return <JournalTradesWidget />;
    case "journaleditor": return <JournalEditorWidget />;
    case "journalimport": return <JournalImportWidget />;
    case "journalsources": return <JournalSourcesWidget />;
    case "performance2": return <PerformanceWidget2 />;
    case "health": return <HealthWidget />;
    case "yields": return <YieldsWidget />;
    case "settings": return <SettingsWidget />;
    case "unavailable": return p.view === "macro_fed" ? <MacroDashboard /> : p.view === "news" ? <NewsWidget /> : p.view === "btc_deriv" ? <DerivativesWidget /> : <UnavailableWidget view={p.view} />;      // layouts saved before news existed still hold the placeholder
  }
}

export function Workspace({ view }: { view: string }) {
  const qc = useQueryClient();
  const def = WORKSPACES[view];
  const saved = useQuery({ queryKey: ["layout", view], queryFn: () => api.layout(view), enabled: !!def, staleTime: Infinity });
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const layout: Layout[] = useMemo(() => {
    if (!def) return [];
    const s = (saved.data as { items?: Layout[] } | null)?.items ?? [];
    return def.widgets.map((w) => ({ ...{ i: w.i, x: w.x, y: w.y, w: w.w, h: w.h, minW: 2, minH: 4 }, ...(s.find((l) => l.i === w.i) ? pick(s.find((l) => l.i === w.i)!) : {}) }));
  }, [def, saved.data]);

  if (!def) return <div className="single"><UnavailableWidget view={view} /></div>;
  if (saved.isLoading) return <div className="note">Loading layout…</div>;

  const onChange = (l: Layout[]) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { api.saveLayout(view, { items: l.map(pick) }).catch(() => undefined); }, 500);
  };
  const reset = async () => { await api.resetLayout(view); qc.setQueryData(["layout", view], null); };

  return (
    <ScopeContext.Provider value={def.scope ?? null}>
    <div className="ws">
      <div className="ws-bar"><span>{def.name}</span><span className="dim small">drag headers to move · drag corners to resize · layout is saved</span><button className="mini" onClick={reset}>reset layout</button></div>
      {view === "overview" && <StatsStrip />}
      <Grid className="layout" layout={layout} cols={12} rowHeight={30} margin={[6, 6]} draggableHandle=".panel-h" draggableCancel="button,input,select,textarea,a,label" onLayoutChange={onChange} compactType="vertical" key={`${view}-${saved.dataUpdatedAt}`}>
        {def.widgets.map((w) => <div key={w.i}>{render(w, view)}</div>)}
      </Grid>
    </div>
    </ScopeContext.Provider>
  );
}
const pick = (l: Layout) => ({ i: l.i, x: l.x, y: l.y, w: l.w, h: l.h });
