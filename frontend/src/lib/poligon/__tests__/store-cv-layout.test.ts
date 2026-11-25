import { describe, expect, it } from "vitest";

import dataset from "../dataset.json";
import { createPoligonStore, type PoligonDataset } from "../store";
import { POLIGON_NEW_CV_CANDIDATES } from "../tools";

const DATA = dataset as unknown as PoligonDataset;
const NOW = Date.UTC(2026, 10, 20, 12, 0, 0);
const [, second] = DATA.meta.people;

const setup = () => ({ store: createPoligonStore(DATA, NOW) });

describe("poligon: układ CV (lekcja „Nowe CV”, 23.11.2026)", () => {
  const meta = DATA.meta as PoligonDataset["meta"] & { ready_cv_candidate_id: number };
  const ready = DATA.meta.people.find((p) => p.candidate_id === meta.ready_cv_candidate_id)!;
  const tpl = DATA.meta.template_entry_id;
  const branded = (store: ReturnType<typeof createPoligonStore>, entry: number) =>
    store.handle({ method: "get", url: `/api/candidates/stages/${entry}/cv/branded` }) as { status: number; data: Record<string, unknown> };

  it("CV etapu ma przełącznik układu: domyślnie Klasyczne, jak u klienta bez reguły", () => {
    const { store } = setup();
    expect(branded(store, tpl).data).toMatchObject({ new_layout_enabled: true, cv_layout: "classic", default_layout: "classic" });
    expect(store.cvLayoutOf(tpl)).toBe("classic");
    expect(store.cvLayoutOf(123456)).toBeNull();
  });

  it("zmiana układu zostaje w pamięci tej osoby i nie rusza treści ani innych osób", () => {
    const { store } = setup();
    const before = branded(store, tpl).data;
    const res = store.handle({ method: "patch", url: `/api/candidates/stages/${tpl}/cv/layout`, body: { cv_layout: "new" } });
    expect(res).not.toBe("network");
    expect(res).toMatchObject({ status: 200, data: { cv_layout: "new", content_html: before.content_html, edit_revision: before.edit_revision } });
    expect(branded(store, tpl).data.cv_layout).toBe("new");
    expect(store.cvLayoutOf(tpl)).toBe("new");
    expect(branded(store, second.entry_id).data.cv_layout).toBe("classic");
    expect(store.handle({ method: "patch", url: `/api/candidates/stages/${tpl}/cv/layout`, body: { cv_layout: "fancy" } })).toMatchObject({ status: 422 });
    // Etap bez CV do klienta: nie ma czego przełączać.
    expect(store.handle({ method: "patch", url: `/api/candidates/stages/${ready.entry_id}/cv/layout`, body: { cv_layout: "new" } })).toMatchObject({ status: 409 });
  });

  it("wieniec nowego CV zapisuje się w pamięci; pusta zmiana strony 1 — odmowa", () => {
    const { store } = setup();
    expect(branded(store, tpl).data.page1_extras).toMatchObject({ wreath: "auto" });
    expect(store.handle({ method: "patch", url: `/api/candidates/stages/${tpl}/cv/page1`, body: { wreath: "school" } })).toMatchObject({ status: 200, data: { page1_extras: { wreath: "school" } } });
    expect(store.handle({ method: "patch", url: `/api/candidates/stages/${tpl}/cv/page1`, body: {} })).toMatchObject({ status: 422 });
    expect(store.handle({ method: "patch", url: `/api/candidates/stages/${tpl}/cv/page1`, body: { wreath: "x" } })).toMatchObject({ status: 422 });
  });
});

describe("poligon: edytor „Strona 1” Nowego CV (lekcja „Nowe CV: strona 1”, 25.11.2026)", () => {
  const [showId, soloId] = POLIGON_NEW_CV_CANDIDATES;
  const entryOf = (candidateId: number) => DATA.meta.people.find((p) => p.candidate_id === candidateId)!.entry_id;
  const branded = (store: ReturnType<typeof createPoligonStore>, entry: number) =>
    store.handle({ method: "get", url: `/api/candidates/stages/${entry}/cv/branded` }) as { status: number; data: Record<string, unknown> };
  const page1 = (store: ReturnType<typeof createPoligonStore>, entry: number, body: Record<string, unknown>) =>
    store.handle({ method: "patch", url: `/api/candidates/stages/${entry}/cv/page1`, body }) as {
      status: number;
      data: { page1_extras?: Record<string, unknown> };
    };

  it("osoby z lekcji mają od startu Nowe CV i zdania z generatora", () => {
    const { store } = setup();
    for (const candidateId of [showId, soloId]) {
      const data = branded(store, entryOf(candidateId)).data;
      expect(data.cv_layout).toBe("new");
      expect(store.cvLayoutOf(entryOf(candidateId))).toBe("new");
      expect((data.page1_extras as { why: string[] }).why).toHaveLength(3);
    }
    expect(branded(store, DATA.meta.template_entry_id).data.page1_extras).not.toHaveProperty("why");
  });

  it("poprawka zdania i „Przywróć z generatora” w pamięci, jak na serwerze", () => {
    const { store } = setup();
    const entry = entryOf(soloId);
    const generated = (branded(store, entry).data.page1_extras as { why: string[] }).why;
    const edited = page1(store, entry, { why: [null, null, "Moje zdanie."] });
    expect(edited.status).toBe(200);
    expect(edited.data.page1_extras?.why).toEqual([generated[0], generated[1], "Moje zdanie."]);
    const restored = page1(store, entry, { why: [null, null, ""] });
    expect(restored.data.page1_extras?.why).toEqual(generated);
    expect(page1(store, entry, { why: ["x".repeat(401)] }).status).toBe(422);
    // Inna osoba bez zmian.
    expect((branded(store, entryOf(showId)).data.page1_extras as { why: string[] }).why).toEqual(generated);
  });

  it("„Ułóż zdania od nowa” zostawia poprawione zdanie, wyróżnik zapisuje się w pamięci", () => {
    const { store } = setup();
    const entry = entryOf(showId);
    page1(store, entry, { why: ["Moje 1.", "", null] });
    const res = store.handle({ method: "post", url: `/api/candidates/stages/${entry}/cv/page1/results` }) as {
      status: number;
      data: { why: string[] };
    };
    expect(res.status).toBe(200);
    expect(res.data.why[0]).toBe("Moje 1.");
    expect(res.data.why[1]).toContain("Scrum i Jira");
    const custom = page1(store, entry, { highlight: { mode: "custom", label: "Atut", text: "Zdanie." } });
    expect(custom.data.page1_extras?.highlight).toMatchObject({ mode: "custom", label: "Atut" });
    expect(page1(store, entry, { highlight: { mode: "custom", label: "", text: "" } }).status).toBe(422);
  });
});
