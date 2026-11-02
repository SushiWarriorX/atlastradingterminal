import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi, normalizeBaseUrl } from "./client";

type Call = { url: string; init: RequestInit };
function fakeFetch(responder: (c: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const f = (async (url: string, init: RequestInit) => {
    const c = { url, init };
    calls.push(c);
    return responder(c);
  }) as unknown as typeof fetch;
  return { f, calls };
}
const ok = (data: unknown) => new Response(JSON.stringify({ ok: true, data }), { status: 200 });
const fail = (status: number, code: string, message: string) => new Response(JSON.stringify({ ok: false, error: { code, message } }), { status });

describe("api client", () => {
  it("unwraps data, sends the bearer token and encodes ids that contain colons", async () => {
    const { f, calls } = fakeFetch(() => ok({ saved: true }));
    const api = createApi({ baseUrl: "https://signal.example.com/", token: "tok123", fetchImpl: f });
    await api.asset("CRYPTO:COINBASE:BTC-USD:SPOT");
    expect(calls[0].url).toBe("https://signal.example.com/api/signal/asset/CRYPTO%3ACOINBASE%3ABTC-USD%3ASPOT");
    expect((calls[0].init.headers as Record<string, string>).Authorization).toBe("Bearer tok123");
    expect(calls[0].init.method).toBe("GET");
  });
  it("sends no Authorization header without a token and JSON bodies for writes", async () => {
    const { f, calls } = fakeFetch(() => ok({ added: true, id: "x", ids: ["x"] }));
    const api = createApi({ baseUrl: "http://10.0.0.5:8000", fetchImpl: f });
    await api.addToWatchlist("EQUITY:NASDAQ:AAPL");
    await api.reorderWatchlist(["b", "a"]);
    await api.removeFromWatchlist("ETF:ARCA:BTC");
    await api.refreshAgent("EQUITY:NASDAQ:AAPL", "news");
    const h = (i: number) => calls[i].init.headers as Record<string, string>;
    expect(h(0).Authorization).toBeUndefined();
    expect([calls[0].init.method, calls[1].init.method, calls[2].init.method, calls[3].init.method]).toEqual(["POST", "PUT", "DELETE", "POST"]);
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ id: "EQUITY:NASDAQ:AAPL" });
    expect(JSON.parse(calls[1].init.body as string)).toEqual({ ids: ["b", "a"] });
    expect(calls[1].url).toBe("http://10.0.0.5:8000/api/signal/watchlist/positions");
    expect(calls[2].url).toContain("ETF%3AARCA%3ABTC");
    expect(JSON.parse(calls[3].init.body as string)).toEqual({ agent: "news" });
    expect(h(0)["Content-Type"]).toBe("application/json");
  });
  it("logs in as a mobile client", async () => {
    const { f, calls } = fakeFetch(() => ok({ required: true, authenticated: true, token: "t", expires_in: 100 }));
    const r = await createApi({ baseUrl: "http://h", fetchImpl: f }).login("pw");
    expect(r.token).toBe("t");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ password: "pw", client: "mobile" });
  });
  it("turns server errors into coded ApiErrors", async () => {
    const { f } = fakeFetch(() => fail(404, "UNKNOWN_ASSET", "That asset id is not recognised."));
    await expect(createApi({ baseUrl: "http://h", fetchImpl: f }).asset("nope")).rejects.toMatchObject({ code: "UNKNOWN_ASSET", status: 404, message: "That asset id is not recognised." });
  });
  it("reports a 401 as AUTH_REQUIRED and tells the app to show the login", async () => {
    const onAuth = vi.fn();
    const { f } = fakeFetch(() => fail(401, "AUTH_REQUIRED", "Please log in."));
    const err = await createApi({ baseUrl: "http://h", fetchImpl: f, onAuthRequired: onAuth }).watchlist().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isAuth).toBe(true);
    expect(onAuth).toHaveBeenCalledTimes(1);
    const bare = fakeFetch(() => new Response("<html>nope</html>", { status: 401 }));
    expect(await createApi({ baseUrl: "http://h", fetchImpl: bare.f }).watchlist().catch((e) => e.code)).toBe("AUTH_REQUIRED");      // even a non-JSON 401
  });
  it("describes an unreachable server and a non-JSON answer clearly", async () => {
    const down = (async () => { throw new TypeError("Network request failed"); }) as unknown as typeof fetch;
    const e1 = await createApi({ baseUrl: "http://h", fetchImpl: down }).meta().catch((e) => e);
    expect(e1.isNetwork).toBe(true);
    expect(e1.message).toMatch(/Can't reach the Signal server/);
    const html = fakeFetch(() => new Response("<html>bad gateway</html>", { status: 502 }));
    const e2 = await createApi({ baseUrl: "http://h", fetchImpl: html.f }).meta().catch((e) => e);
    expect(e2).toMatchObject({ code: "HTTP_ERROR", status: 502 });
  });
  it("gives up when the server never answers", async () => {
    const hang = ((_u: string, init: RequestInit) => new Promise((_res, rej) => { init.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError"))); })) as unknown as typeof fetch;
    const e = await createApi({ baseUrl: "http://h", fetchImpl: hang, timeoutMs: 30 }).meta().catch((x) => x);
    expect(e).toMatchObject({ code: "NETWORK", message: "The server took too long to answer." });
  });
  it("cleans up server addresses", () => {
    expect(normalizeBaseUrl("signal.example.com")).toBe("http://signal.example.com");
    expect(normalizeBaseUrl("https://signal.example.com/")).toBe("https://signal.example.com");
    expect(normalizeBaseUrl("  http://192.168.1.20:8000// ")).toBe("http://192.168.1.20:8000");
    expect(normalizeBaseUrl("localhost:8000")).toBe("http://localhost:8000");
    for (const bad of ["", "   ", "ftp://x.y", "javascript:alert(1)", "http://"]) expect(normalizeBaseUrl(bad)).toBeNull();
  });
});
