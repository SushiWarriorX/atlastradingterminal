// Browser and phone actions for the "Ask ChatGPT" handoff (the phone app also runs in a browser, where the browser actions are used; inside a native build the system share sheet is the manual-copy path). Pure and injectable so each behaviour can be tested: copy only reports success when something was really copied, the ChatGPT address never
// carries any context, and a blocked new tab is reported instead of assumed.
export const CHATGPT_URL = "https://chatgpt.com/";
export const COPIED = "Context copied. Paste it into ChatGPT and ask your question.";
export const COPY_FAILED = "Could not copy automatically. The context below is selected: press Ctrl+C (Cmd+C on a Mac) to copy it, then paste it into ChatGPT.";
export const POPUP_BLOCKED = "Your browser blocked the new tab. Use the Open ChatGPT link below, then paste.";

export interface CopyEnv {
  clipboardWrite?: ((text: string) => Promise<void>) | null;   // the asynchronous Clipboard API (needs a secure page and permission)
  execCopy?: (() => boolean) | null;                            // the older select-and-copy command, as a fallback
}

const attempt = (f: () => boolean): boolean => { try { return f() === true; } catch { return false; } };

/** Starts copying inside the click (so the browser accepts it) and resolves true ONLY if the text was actually copied. */
export function startCopy(text: string, env: CopyEnv): Promise<boolean> {
  let viaApi: Promise<boolean>;
  try { viaApi = env.clipboardWrite ? env.clipboardWrite(text).then(() => true, () => false) : Promise.resolve(false); } catch { viaApi = Promise.resolve(false); }
  return viaApi.then((ok) => (ok ? true : env.execCopy ? attempt(env.execCopy) : false));
}

/** Opens ChatGPT in a new tab with a plain address (never any context in it). Returns false when the browser blocked the tab. */
export function openChatGpt(open: (url: string, target: string) => { opener: unknown } | null): boolean {
  let w: { opener: unknown } | null = null;
  try { w = open(CHATGPT_URL, "_blank"); } catch { w = null; }
  if (!w) return false;
  try { w.opener = null; } catch { /* the new page is already detached */ }
  return true;
}

export function browserCopyEnv(el: HTMLTextAreaElement | null): CopyEnv {
  const nav = typeof navigator !== "undefined" ? navigator : undefined;
  const secure = typeof window !== "undefined" && window.isSecureContext;
  return {
    clipboardWrite: nav?.clipboard?.writeText && secure ? (t) => nav.clipboard.writeText(t) : null,
    execCopy: el ? () => { el.focus(); el.select(); return document.execCommand("copy"); } : null,
  };
}

/** Saves the text as a Markdown file through a temporary link. */
export function downloadMarkdown(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = filename.replace(/[^A-Za-z0-9._-]/g, "_"); a.rel = "noopener"; a.style.display = "none";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
