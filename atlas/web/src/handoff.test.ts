import { describe, expect, it, vi } from "vitest";
import { CHATGPT_URL, openChatGpt, startCopy } from "./handoff";

describe("startCopy", () => {
  it("reports success only when the clipboard really took the text", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    expect(await startCopy("hello", { clipboardWrite: write })).toBe(true);
    expect(write).toHaveBeenCalledWith("hello");
  });
  it("falls back to the select-and-copy command when the clipboard API is refused", async () => {
    const exec = vi.fn().mockReturnValue(true);
    expect(await startCopy("x", { clipboardWrite: () => Promise.reject(new Error("denied")), execCopy: exec })).toBe(true);
    expect(exec).toHaveBeenCalledOnce();
  });
  it("falls back when there is no clipboard API at all (an insecure page)", async () => {
    expect(await startCopy("x", { clipboardWrite: null, execCopy: () => true })).toBe(true);
  });
  it("says false when everything fails, never true", async () => {
    expect(await startCopy("x", { clipboardWrite: () => Promise.reject(new Error("no")), execCopy: () => false })).toBe(false);
    expect(await startCopy("x", { clipboardWrite: () => Promise.reject(new Error("no")), execCopy: () => { throw new Error("blocked"); } })).toBe(false);
    expect(await startCopy("x", {})).toBe(false);
    expect(await startCopy("x", { clipboardWrite: () => { throw new Error("sync failure"); } })).toBe(false);
  });
  it("does not use the fallback when the clipboard API worked", async () => {
    const exec = vi.fn().mockReturnValue(true);
    await startCopy("x", { clipboardWrite: async () => undefined, execCopy: exec });
    expect(exec).not.toHaveBeenCalled();
  });
});

describe("openChatGpt", () => {
  it("opens the plain address: no query string, no fragment, no context", () => {
    const open = vi.fn().mockReturnValue({ opener: "page" });
    expect(openChatGpt(open)).toBe(true);
    expect(open).toHaveBeenCalledWith(CHATGPT_URL, "_blank");
    const url = new URL(open.mock.calls[0][0]);
    expect(url.origin + url.pathname).toBe("https://chatgpt.com/");
    expect(url.search).toBe("");
    expect(url.hash).toBe("");
  });
  it("detaches the new page from this one", () => {
    const w = { opener: "page" as unknown };
    openChatGpt(() => w);
    expect(w.opener).toBeNull();
  });
  it("reports a blocked tab instead of assuming it opened", () => {
    expect(openChatGpt(() => null)).toBe(false);
    expect(openChatGpt(() => { throw new Error("blocked"); })).toBe(false);
  });
});
