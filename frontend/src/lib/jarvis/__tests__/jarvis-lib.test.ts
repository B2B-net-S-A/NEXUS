import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { JARVIS_CHARACTERS } from "@/components/jarvis/characters/JarvisCharacter";
import { screenFromLocation, suggestionsFor } from "../context";
import { applyStreamEvent, replaceAction, type JarvisTurnState } from "../reducer";
import { createSseParser } from "../sse";
import { JarvisHttpError, streamJarvisChat } from "../stream";
import type { JarvisStreamEvent } from "../types";

const EMPTY: JarvisTurnState = { items: [], thinking: false, mood: "idle", conversationId: null };

describe("parser SSE", () => {
  it("składa zdarzenie pocięte w dowolnym miejscu, także w środku znaku UTF-8", () => {
    const parser = createSseParser();
    const bytes = new TextEncoder().encode(
      'event: message\ndata: {"type":"message","markdown":"Zażółć"}\n\n: ping\n\nevent: done\ndata: {"type":"done"}\n\n',
    );
    const events: JarvisStreamEvent[] = [];
    // Tniemy co 7 bajtów — trafiamy w środek „ż”.
    for (let i = 0; i < bytes.length; i += 7) events.push(...parser.feed(bytes.slice(i, i + 7)));
    events.push(...parser.flush());
    expect(events).toEqual([{ type: "message", markdown: "Zażółć" }, { type: "done" }]);
  });

  it("pomija heartbeat i śmieci", () => {
    const parser = createSseParser();
    expect(parser.feed(": ping\n\ndata: nie-json\n\n")).toEqual([]);
  });
});

describe("kontekst ekranu", () => {
  it.each([
    ["/candidates/12", "candidate", 12],
    ["/jobs/5/board", "job", 5],
    ["/clients/7", "client", 7],
    ["/my-clients/3", "client", 3],
    ["/contracts/99", "contract", 99],
  ] as const)("%s → %s #%i", (path, type, id) => {
    expect(screenFromLocation(path, "?tab=x").entity).toEqual({ type, id });
  });

  it("ścieżka bez rekordu nie wymyśla encji, a zapytanie zostaje w ścieżce", () => {
    expect(screenFromLocation("/candidates/search", "q=java")).toEqual({
      path: "/candidates/search?q=java",
      entity: null,
    });
  });

  it("podpowiedzi zależą od ekranu", () => {
    // Na rekrutacji pierwsza podpowiedź to przepięcie „Moich ludzi".
    expect(suggestionsFor({ path: "/jobs/1", entity: { type: "job", id: 1 } })[0]).toContain("moich ludzi");
    expect(suggestionsFor({ path: "/jobs/1", entity: { type: "job", id: 1 } })).toContain(
      "Kto stoi najdłużej na tablicy tej rekrutacji?",
    );
    expect(suggestionsFor({ path: "/" })[0]).toBe("Co mam dziś do zrobienia?");
  });
});

describe("reduktor tury", () => {
  it("krok running → done podmienia status zamiast dublować", () => {
    let state = applyStreamEvent(EMPTY, { type: "step", tool: "get_job", label: "Czytam…", status: "running" });
    expect(state.mood).toBe("working");
    state = applyStreamEvent(state, { type: "step", tool: "get_job", label: "Czytam…", status: "done" });
    expect(state.items).toEqual([{ kind: "steps", steps: [{ tool: "get_job", label: "Czytam…", status: "done" }] }]);
  });

  it("propozycja zostawia maskotkę w nasłuchu po zakończeniu tury", () => {
    let state = applyStreamEvent(EMPTY, {
      type: "action_proposed",
      action: { id: "a1", tool: "create_note", status: "proposed", preview: { text: "x" } },
    });
    state = applyStreamEvent(state, { type: "done" });
    expect(state.mood).toBe("listening");
    expect(state.thinking).toBe(false);
  });

  it("błąd kończy myślenie i zmienia nastrój", () => {
    const state = applyStreamEvent({ ...EMPTY, thinking: true }, { type: "error", message: "Nie działam" });
    expect(state.thinking).toBe(false);
    expect(state.mood).toBe("error");
    expect(state.items.at(-1)).toEqual({ kind: "error", message: "Nie działam" });
  });

  it("zatwierdzenie podmienia kartę i dokłada komunikat oraz kartę „mimo ostrzeżenia”", () => {
    const items = replaceAction(
      [{ kind: "action", action: { id: "a1", tool: "t", status: "proposed", preview: { text: "x" } } }],
      { id: "a1", tool: "t", status: "failed", preview: { text: "x" } },
      { id: "a2", tool: "t", status: "proposed", preview: { text: "x — mimo ostrzeżenia" } },
      "NEXUS ostrzega",
    );
    expect(items.map((i) => i.kind)).toEqual(["action", "message", "action"]);
  });
});

function streamResponse(chunks: string[], init: ResponseInit = { status: 200 }): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
  });
  return new Response(body, init);
}

describe("strumień czatu", () => {
  it("przekazuje zdarzenia w kolejności", async () => {
    const events: JarvisStreamEvent[] = [];
    const fetchImpl = vi.fn(async () =>
      streamResponse(['data: {"type":"conversation","conversation_id":"c1"}\n\n', 'data: {"type":"done"}\n\n']),
    );
    await streamJarvisChat({ message: "hej" }, { onEvent: (e) => events.push(e), fetchImpl });
    expect(events).toEqual([{ type: "conversation", conversation_id: "c1" }, { type: "done" }]);
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ message: "hej" });
  });

  it("urwany strumień (bez done) kończy się jawnym błędem, nie ciszą", async () => {
    const events: JarvisStreamEvent[] = [];
    const fetchImpl = vi.fn(async () => streamResponse(['data: {"type":"thinking","step":1}\n\n']));
    await streamJarvisChat({ message: "hej" }, { onEvent: (e) => events.push(e), fetchImpl });
    expect(events.at(-1)).toMatchObject({ type: "error", code: "interrupted" });
  });

  it("409 przed strumieniem to błąd z komunikatem serwera", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Jarvis jeszcze odpowiada na poprzednie pytanie — poczekaj chwilę." }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
    );
    await expect(streamJarvisChat({ message: "hej" }, { onEvent: () => undefined, fetchImpl })).rejects.toBeInstanceOf(
      JarvisHttpError,
    );
  });

  it("401 wylogowuje", async () => {
    const onUnauthorized = vi.fn();
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 401 }));
    await expect(
      streamJarvisChat({ message: "hej" }, { onEvent: () => undefined, fetchImpl, onUnauthorized }),
    ).rejects.toBeInstanceOf(JarvisHttpError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});

describe("lista postaci = lista w backendzie", () => {
  it("front i `prefs.py` znają te same postaci", () => {
    const source = readFileSync(resolve(__dirname, "../../../../../backend/app/services/jarvis/prefs.py"), "utf8");
    const literal = /JarvisCharacter = Literal\[([\s\S]*?)\]/.exec(source)?.[1] ?? "";
    const backend = [...literal.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
    expect(JARVIS_CHARACTERS.map((c) => c.id).sort()).toEqual(backend);
    const unlockable = JARVIS_CHARACTERS.filter((c) => c.unlockable).map((c) => c.id).sort();
    expect(unlockable).toEqual(["robot_gold", "trophy"]);
  });
});

describe("źródła w reduktorze", () => {
  it("zdarzenie sources dokłada pozycję ze źródłami", () => {
    const state = applyStreamEvent(EMPTY, { type: "sources", items: [{ url: "https://a.pl", title: "A" }] });
    expect(state.items).toEqual([{ kind: "sources", items: [{ url: "https://a.pl", title: "A" }] }]);
  });

  it("strumień wysyła flagę web", async () => {
    const fetchImpl = vi.fn(async () => streamResponse(['data: {"type":"done"}\n\n']));
    await streamJarvisChat({ message: "hej", web: true }, { onEvent: () => undefined, fetchImpl });
    const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ message: "hej", web: true });
  });
});
