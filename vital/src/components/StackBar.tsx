export interface Segment {
  label: string;
  value: number;
  color: string;
  /** Text shown in the legend, e.g. "1h 42m · 23%". */
  display: string;
}

export function StackBar({ segments, ariaLabel }: { segments: Segment[]; ariaLabel: string }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  return (
    <div>
      <div className="stack" role="img" aria-label={ariaLabel}>
        {total > 0 &&
          segments.map((s) =>
            s.value > 0 ? <span key={s.label} style={{ flexGrow: s.value, background: s.color }} /> : null,
          )}
      </div>
      <ul className="legend">
        {segments.map((s) => (
          <li key={s.label}>
            <i style={{ background: s.color }} />
            <span className="legend-label">{s.label}</span>
            <span className="legend-value">{s.display}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
