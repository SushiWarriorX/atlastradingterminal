/** At this width and above the app shows three panes side by side (watchlist, research, news) instead of one screen at a time. */
export const WIDE_MIN = 1000;
export const isWide = (width: number): boolean => width >= WIDE_MIN;
