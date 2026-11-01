import { useEffect, useState } from "react";

/** The value, but only once it has stopped changing for `ms`: keeps a search box from firing one request per keystroke. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}
