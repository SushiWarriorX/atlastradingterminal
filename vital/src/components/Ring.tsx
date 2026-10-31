import type { CSSProperties, ReactNode } from 'react';

interface RingProps {
  /** 0–1 */
  value: number;
  color: string;
  size?: number;
  stroke?: number;
  label: string;
  children?: ReactNode;
}

export function Ring({ value, color, size = 120, stroke = 9, label, children }: RingProps) {
  const r = 50 - stroke / 2;
  const c = 2 * Math.PI * r;
  const v = Math.min(1, Math.max(0, value));
  return (
    <div className="ring" style={{ '--ring': `${size}px` } as CSSProperties} role="img" aria-label={label}>
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle className="ring-track" cx="50" cy="50" r={r} strokeWidth={stroke} />
        {v > 0 && (
          <circle
            className="ring-value"
            cx="50"
            cy="50"
            r={r}
            strokeWidth={stroke}
            strokeDasharray={c}
            strokeDashoffset={c * (1 - v)}
            style={{ stroke: color }}
            transform="rotate(-90 50 50)"
          />
        )}
      </svg>
      <div className="ring-center">{children}</div>
    </div>
  );
}
