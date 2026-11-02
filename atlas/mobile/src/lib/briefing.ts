import type { AgentName, Briefing, BriefingLine, Finding, Stance } from "../api/types";
import { countdown, localDateTime } from "./format";

/** The order the agents are shown in (as requested): News, Technical, Macro, Fundamentals. */
export const AGENT_ORDER: AgentName[] = ["news", "technical", "macro", "fundamentals"];
export const AGENT_TITLE: Record<AgentName, string> = { news: "News", technical: "Technical", macro: "Macro", fundamentals: "Fundamentals" };
export const STANCE_LABEL: Record<Stance, string> = { supportive: "Supportive", mixed: "Mixed", cautious: "Cautious", neutral: "Neutral", insufficient: "Not enough data" };

export type RowKind = "pending" | "ready" | "partial" | "unavailable" | "not_applicable";
export function rowKind(f: Finding | undefined): RowKind {
  if (!f) return "pending";
  return f.status === "ok" ? "ready" : f.status;
}

export interface Section { key: "changed" | "supports" | "risks" | "watch"; title: string; lines: BriefingLine[] }

/** The four briefing questions, in order. Empty sections are kept (the screen says "Nothing notable") so the structure never jumps around. */
export function briefingSections(b: Briefing): Section[] {
  return [
    { key: "changed", title: "What changed", lines: b.changed },
    { key: "supports", title: "What supports it", lines: b.supports },
    { key: "risks", title: "Main risks", lines: b.risks },
    { key: "watch", title: "Watch next", lines: b.watch },
  ];
}

export function lineText(l: BriefingLine, nowMs: number, tz?: string): string {
  if (!l.at_utc) return l.text;
  const c = countdown(l.at_utc, nowMs);
  return `${l.text} ${localDateTime(l.at_utc, tz)}${c ? ` (${c})` : ""}`;
}

/** One line saying how much of the picture this briefing covers, or null when all four agents contributed. */
export function coverageNote(b: Briefing): string | null {
  const c = b.coverage;
  const parts: string[] = [];
  if (c.pending.length) parts.push(`${c.pending.map((a) => AGENT_TITLE[a as AgentName] ?? a).join(", ")} still loading`);
  if (c.unavailable.length) parts.push(`${c.unavailable.map((u) => AGENT_TITLE[u.agent as AgentName] ?? u.agent).join(", ")} unavailable`);
  if (c.partial.length) parts.push(`${c.partial.map((a) => AGENT_TITLE[a as AgentName] ?? a).join(", ")} partly available`);
  if (!parts.length) return null;
  const used = c.agents_ok + c.partial.length;
  if (used === c.agents_total && !c.pending.length && !c.unavailable.length) return `All ${c.agents_total} agents contributed; ${c.partial.map((a) => AGENT_TITLE[a as AgentName] ?? a).join(", ")} ${c.partial.length === 1 ? "is" : "are"} only partly available (open its row to see what is missing).`;
  return `Based on ${used} of ${c.agents_total} agents: ${parts.join("; ")}.`;
}

export function pendingAgents(r: { pending: AgentName[] } | undefined): boolean {
  return !!r && r.pending.length > 0;
}

export function stanceTone(s: Stance | null): "good" | "warn" | "mid" | "none" {
  return s === "supportive" ? "good" : s === "cautious" ? "warn" : s === "mixed" ? "mid" : "none";
}
