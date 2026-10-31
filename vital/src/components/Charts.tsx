import { useLayoutEffect, useRef, useState, type PointerEvent } from 'react';

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

/** Path through points, lifting the pen over gaps (nulls). */
function path(points: ({ x: number; y: number } | null)[]): string {
  let d = '';
  let pen = false;
  for (const p of points) {
    if (!p) {
      pen = false;
      continue;
    }
    d += `${pen ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    pen = true;
  }
  return d;
}

const PAD = { l: 34, r: 8, t: 10, b: 24 };

function Tooltip({ x, width, title, lines }: { x: number; width: number; title: string; lines: string[] }) {
  return (
    <div className="tooltip" style={{ left: clamp(x, 56, Math.max(56, width - 56)) }} role="presentation">
      <strong>{title}</strong>
      {lines.map((l) => (
        <span key={l}>{l}</span>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ bars

export interface BarDatum {
  label: string;
  /** Longer name for the tooltip (defaults to `label`). */
  title?: string;
  value: number | null;
  color?: string;
  /** Tooltip lines (defaults to the formatted value). */
  tip?: string[];
}

interface BarChartProps {
  data: BarDatum[];
  max?: number;
  height?: number;
  color?: string;
  /** Optional dashed line over the bars (e.g. sleep need). Same length as `data`. */
  line?: (number | null)[];
  lineColor?: string;
  /** Y-axis tick values (default: 0, half, max). */
  ticks?: number[];
  format?: (v: number) => string;
  ariaLabel: string;
}

export function BarChart({
  data,
  max,
  height = 170,
  color = 'var(--blue)',
  line,
  lineColor = 'var(--muted)',
  ticks,
  format = (v) => String(Math.round(v)),
  ariaLabel,
}: BarChartProps) {
  const [ref, w] = useWidth();
  const [hover, setHover] = useState<number | null>(null);

  const innerW = Math.max(0, w - PAD.l - PAD.r);
  const innerH = height - PAD.t - PAD.b;
  const n = Math.max(1, data.length);
  const step = innerW / n;
  const bw = Math.max(2, Math.min(30, step * 0.64));
  const top = max ?? niceMax(Math.max(1, ...data.map((d) => d.value ?? 0), ...(line ?? []).map((v) => v ?? 0)));
  const y = (v: number) => PAD.t + innerH - (clamp(v, 0, top) / top) * innerH;
  const cx = (i: number) => PAD.l + i * step + step / 2;
  const every = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(innerW / 46))));

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const i = Math.floor((e.clientX - e.currentTarget.getBoundingClientRect().left - PAD.l) / step);
    setHover(i >= 0 && i < n ? i : null);
  };

  return (
    <div className="chart" ref={ref} style={{ height }} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
      {w > 0 && (
        <svg width={w} height={height} role="img" aria-label={ariaLabel}>
          {(ticks ?? [0, top / 2, top]).map((v) => (
            <g key={v}>
              <line x1={PAD.l} x2={w - PAD.r} y1={y(v)} y2={y(v)} className="grid" />
              <text x={PAD.l - 6} y={y(v) + 3.5} className="axis" textAnchor="end">
                {format(v)}
              </text>
            </g>
          ))}
          {data.map((d, i) =>
            d.value == null ? null : (
              <rect
                key={i}
                x={cx(i) - bw / 2}
                y={y(d.value)}
                width={bw}
                height={Math.max(0, PAD.t + innerH - y(d.value))}
                rx={Math.min(4, bw / 2)}
                fill={d.color ?? color}
                opacity={hover === null || hover === i ? 1 : 0.5}
              />
            ),
          )}
          {line && (
            <path
              d={path(line.map((v, i) => (v == null ? null : { x: cx(i), y: y(v) })))}
              fill="none"
              stroke={lineColor}
              strokeWidth="1.75"
              strokeDasharray="4 3"
            />
          )}
          {data.map((d, i) =>
            i % every === 0 ? (
              <text key={i} x={cx(i)} y={height - 7} className="axis" textAnchor="middle">
                {d.label}
              </text>
            ) : null,
          )}
        </svg>
      )}
      {hover !== null && data[hover] && (
        <Tooltip
          x={cx(hover)}
          width={w}
          title={data[hover].title ?? data[hover].label}
          lines={data[hover].tip ?? [data[hover].value == null ? 'No data' : format(data[hover].value as number)]}
        />
      )}
    </div>
  );
}

// ------------------------------------------------------------------ lines

export interface Series {
  label: string;
  values: (number | null)[];
  color: string;
}

interface LineChartProps {
  labels: string[];
  /** Longer names for tooltips (defaults to `labels`). */
  titles?: string[];
  series: Series[];
  /** Shaded "normal range". */
  band?: { lo: number; hi: number } | null;
  height?: number;
  format?: (v: number) => string;
  ariaLabel: string;
}

export function LineChart({ labels, titles, series, band, height = 170, format = (v) => String(Math.round(v)), ariaLabel }: LineChartProps) {
  const [ref, w] = useWidth();
  const [hover, setHover] = useState<number | null>(null);

  const innerW = Math.max(0, w - PAD.l - PAD.r);
  const innerH = height - PAD.t - PAD.b;
  const n = Math.max(1, labels.length);
  const step = innerW / n;
  const cx = (i: number) => PAD.l + i * step + step / 2;

  const all = series.flatMap((s) => s.values).filter((v): v is number => v != null);
  if (band) all.push(band.lo, band.hi);
  let lo = all.length ? Math.min(...all) : 0;
  let hi = all.length ? Math.max(...all) : 1;
  if (hi - lo < 1e-6) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.12;
  lo -= pad;
  hi += pad;
  const y = (v: number) => PAD.t + innerH - ((v - lo) / (hi - lo)) * innerH;
  const every = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(innerW / 46))));

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const i = Math.floor((e.clientX - e.currentTarget.getBoundingClientRect().left - PAD.l) / step);
    setHover(i >= 0 && i < n ? i : null);
  };

  return (
    <div className="chart" ref={ref} style={{ height }} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
      {w > 0 && (
        <svg width={w} height={height} role="img" aria-label={ariaLabel}>
          {[0, 0.5, 1].map((f) => {
            const v = lo + (hi - lo) * f;
            return (
              <g key={f}>
                <line x1={PAD.l} x2={w - PAD.r} y1={y(v)} y2={y(v)} className="grid" />
                <text x={PAD.l - 6} y={y(v) + 3.5} className="axis" textAnchor="end">
                  {format(v)}
                </text>
              </g>
            );
          })}
          {band && (
            <rect
              x={PAD.l}
              width={innerW}
              y={y(band.hi)}
              height={Math.max(0, y(band.lo) - y(band.hi))}
              className="band"
            />
          )}
          {hover !== null && <line x1={cx(hover)} x2={cx(hover)} y1={PAD.t} y2={PAD.t + innerH} className="guide" />}
          {series.map((s) => (
            <g key={s.label}>
              <path
                d={path(s.values.map((v, i) => (v == null ? null : { x: cx(i), y: y(v) })))}
                fill="none"
                stroke={s.color}
                strokeWidth="2.25"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {hover !== null && s.values[hover] != null && (
                <circle cx={cx(hover)} cy={y(s.values[hover] as number)} r="4" fill={s.color} className="dot" />
              )}
            </g>
          ))}
          {labels.map((l, i) =>
            i % every === 0 ? (
              <text key={i} x={cx(i)} y={height - 7} className="axis" textAnchor="middle">
                {l}
              </text>
            ) : null,
          )}
        </svg>
      )}
      {hover !== null && labels[hover] !== undefined && (
        <Tooltip
          x={cx(hover)}
          width={w}
          title={titles?.[hover] ?? labels[hover]}
          lines={series.map((s) => `${s.label}: ${s.values[hover] == null ? '–' : format(s.values[hover] as number)}`)}
        />
      )}
    </div>
  );
}
