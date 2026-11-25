import { describe, expect, it } from "vitest";

import dataset from "../dataset.json";
import { createPoligonStore, type PoligonDataset } from "../store";

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

  it("zmiany strony 1 nowego CV na poligonie — odmowa (wieńca w Edukacji nie ma od 25.11.2026)", () => {
    const { store } = setup();
    expect(branded(store, tpl).data.page1_extras).not.toHaveProperty("wreath");
    expect(store.handle({ method: "patch", url: `/api/candidates/stages/${tpl}/cv/page1`, body: { result_text: "Zdanie" } })).toMatchObject({ status: 409 });
  });
});
