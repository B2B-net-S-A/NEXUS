import { describe, expect, it } from "vitest";

import {
  companyCvSentence,
  companyCvStale,
  companyDraftSince,
  dockOriginalCv,
  newerProfileCv,
  originalCvSentence,
  pairCompanyCv,
  primaryProfileCv,
  withoutQuarantinedCv,
} from "@/lib/dock-cv-summary";
import { summarizeRequirements, type MoveRequirementItem } from "@/lib/api/moveRequirements";
import { nextStageHeading } from "@/components/v2/jobs/DockNextStage";

const doc = (id: number, extra: Partial<{ is_primary: boolean; filename: string; uploaded_at: string | null }> = {}) => ({
  id,
  filename: extra.filename ?? `cv-${id}.pdf`,
  is_primary: extra.is_primary ?? false,
  uploaded_at: extra.uploaded_at ?? null,
  created_at: "2026-01-05T10:00:00Z",
});

describe("dockOriginalCv", () => {
  it("kopia ze zgłoszenia wygrywa z profilem", () => {
    const state = dockOriginalCv({
      snapshot: { has_snapshot: true, original_snapshot_at: "2026-08-20T08:00:00Z" },
      snapshotLoading: false,
      profileDocs: [doc(1)],
      profileDocsFailed: false,
    });
    expect(state.kind).toBe("snapshot");
  });

  it("bez kopii — plik z profilu, nie „brak”", () => {
    const state = dockOriginalCv({
      snapshot: { has_snapshot: false },
      snapshotLoading: false,
      profileDocs: [doc(1), doc(2, { is_primary: true, uploaded_at: "2026-09-01T10:00:00Z" })],
      profileDocsFailed: false,
    });
    expect(state).toMatchObject({ kind: "profile", date: "2026-09-01T10:00:00Z" });
    expect(originalCvSentence(state)).toBe(
      "Oryginał CV: z profilu (1.09.2026) — do zgłoszenia nie dołączono pliku",
    );
  });

  it("„brak pliku” tylko przy wczytanej, pustej liście dokumentów", () => {
    expect(
      dockOriginalCv({ snapshot: { has_snapshot: false }, snapshotLoading: false, profileDocs: [], profileDocsFailed: false })
        .kind,
    ).toBe("none");
    // Nieudany odczyt profilu to nie brak pliku.
    expect(
      dockOriginalCv({ snapshot: { has_snapshot: false }, snapshotLoading: false, profileDocs: undefined, profileDocsFailed: true })
        .kind,
    ).toBe("unknown");
    // W toku — ani brak, ani obecność.
    expect(
      dockOriginalCv({ snapshot: { has_snapshot: false }, snapshotLoading: false, profileDocs: undefined, profileDocsFailed: false })
        .kind,
    ).toBe("loading");
  });

  it("główne CV profilu: oznaczone jako główne → nazwa z profilu → pierwsze", () => {
    expect(primaryProfileCv([doc(1), doc(2, { is_primary: true })])?.id).toBe(2);
    expect(primaryProfileCv([doc(1), doc(2, { filename: "moje.pdf" })], "moje.pdf")?.id).toBe(2);
    expect(primaryProfileCv([doc(1), doc(2)])?.id).toBe(1);
    expect(primaryProfileCv([])).toBeNull();
  });
});

describe("companyCvSentence", () => {
  it("brak / szkic / zatwierdzone / stary szablon — każde z datą, gdy jest", () => {
    expect(companyCvSentence({ status: "none" }).text).toBe("CV firmowe: brak");
    expect(
      companyCvSentence({ status: "draft", from_generator: true, updated_at: "2026-09-03T10:00:00Z" }).text,
    ).toBe("CV firmowe: szkic · zmienione 3.09.2026");
    expect(
      companyCvSentence({ status: "finalized", from_generator: true, finalized_at: "2026-09-04T10:00:00Z" }).text,
    ).toBe("CV firmowe: zatwierdzone 4.09.2026");
    expect(companyCvSentence({ status: "draft", from_generator: false }).text).toMatch(/stary szablon/);
  });

  it("etap bez własnego CV, a para ma CV firmowe (ramka „Następny etap” mówi ✓) — nie „brak”", () => {
    const pairOk = pairCompanyCv([
      { key: "company_cv", label: "CV firmowe", status: "ok", blocking: true },
    ]);
    expect(pairOk).toBe(true);
    const s = companyCvSentence(null, { pairHasCompanyCv: pairOk });
    expect(s.text).toBe("CV firmowe: gotowe (w plikach kandydata)");
    expect(s.tone).toBe("success");
  });

  it("etap bez CV i brak wiedzy o parze albo para bez CV — „brak”", () => {
    expect(pairCompanyCv(undefined)).toBeNull();
    expect(pairCompanyCv([{ key: "rate", label: "Stawka", status: "ok", blocking: true }])).toBeNull();
    expect(
      pairCompanyCv([{ key: "company_cv", label: "CV firmowe", status: "missing", blocking: true }]),
    ).toBe(false);
    expect(companyCvSentence(null, { pairHasCompanyCv: null }).text).toBe("CV firmowe: brak");
    expect(companyCvSentence(null, { pairHasCompanyCv: false }).text).toBe("CV firmowe: brak");
  });
});

describe("summarizeRequirements", () => {
  const item = (key: string, status: MoveRequirementItem["status"]): MoveRequirementItem => ({
    key,
    label: key,
    status,
    blocking: true,
  });

  it("liczy braki (także „w toku”) i oddziela bramki serwera od przypomnień", () => {
    const summary = summarizeRequirements([
      item("cv_qc", "missing"),
      item("company_cv", "missing"),
      item("client_slot", "waiting"),
      item("availability", "ok"),
    ]);
    expect(summary.missing).toBe(3);
    expect(summary.total).toBe(4);
    expect(summary.enforced.map((i) => i.key)).toEqual(["cv_qc"]);
    expect(summary.reminders.map((i) => i.key)).toEqual(["company_cv", "client_slot"]);
  });
});

describe("nextStageHeading", () => {
  it("numer i nazwa kolumny z serwera, a przed odpowiedzią nazwa etapu z karty", () => {
    expect(nextStageHeading({ to_column: "cv_qc", items: [] }, "Przepuszczony przez DZ")).toEqual({
      step: 4,
      label: "QC CV",
    });
    expect(nextStageHeading(null, "QC CV")).toEqual({ step: null, label: "QC CV" });
  });

  it("u Nordei kolumna 5 to „Wysłane do Cpro”", () => {
    const heading = nextStageHeading(
      { to_column: "cv_sent", items: [{ key: "cpro_upload", label: "x", status: "waiting", blocking: false }] },
      "CV wysłane",
    );
    expect(heading.step).toBe(5);
    expect(heading.label).toMatch(/Cpro/);
  });
});

describe("CV firmowe pary na innym etapie (D2, 14.10.2026)", () => {
  // Dok podaje stan CV z wiersza, na którym CV leży (`pair_source_stage_id`),
  // więc zdanie jest takie samo jak przy CV bieżącego etapu — bez dopisku
  // „nie podpięte do bieżącego etapu”, który Delivery Lead czytał jak „brak CV”.
  it("zatwierdzone i szkic z wiersza pary mówią o CV, nie o etapach", () => {
    const finalized = companyCvSentence({
      status: "finalized",
      from_generator: true,
      finalized_at: "2026-09-26T10:00:00Z",
    });
    expect(finalized).toEqual({ text: "CV firmowe: zatwierdzone 26.09.2026", tone: "success" });
    const draft = companyCvSentence({ status: "draft", from_generator: true, updated_at: "2026-10-14T09:00:00Z" });
    expect(draft).toEqual({ text: "CV firmowe: szkic · zmienione 14.10.2026", tone: "info" });
    expect(`${finalized.text} ${draft.text}`).not.toMatch(/podpięte|z etapu/);
  });
});

const snapshot = (date: string, source: string | null = null, filename: string | null = "cv.pdf") =>
  dockOriginalCv({
    snapshot: {
      has_snapshot: true,
      original_snapshot_at: date,
      original_cv_filename: filename,
      original_snapshot_source: source,
    },
    snapshotLoading: false,
    profileDocs: undefined,
    profileDocsFailed: false,
  });

describe("nowe CV w rekrutacji (13.10.2026)", () => {
  it("zdanie mówi, skąd jest kopia CV tej rekrutacji", () => {
    expect(originalCvSentence(snapshot("2026-10-13T13:10:00Z", "manual_upload", "Anna_CV.pdf"))).toBe(
      "Oryginał CV: wgrane w rekrutacji · Anna_CV.pdf · 13.10.2026",
    );
    expect(originalCvSentence(snapshot("2026-10-13T13:10:00Z", "manual_refresh"))).toBe(
      "Oryginał CV: z profilu · cv.pdf · podmienione 13.10.2026",
    );
    expect(originalCvSentence(snapshot("2026-10-13T13:10:00Z", "stage_create"))).toBe(
      "Oryginał CV: dołączony do zgłoszenia · 13.10.2026",
    );
    // Bramka tożsamości: wgrane CV było cudze, kopia wróciła do CV osoby.
    expect(originalCvSentence(snapshot("2026-10-13T13:12:00Z", "quarantine_restore", "wlasne.pdf"))).toBe(
      "Oryginał CV: poprzednie CV · wlasne.pdf — wgrane nie pasowało do tej osoby",
    );
  });

  it("nowsze CV w profilu: główne CV młodsze od kopii o co najmniej minutę", () => {
    const original = snapshot("2026-10-08T10:00:00Z");
    const newer = doc(7, { is_primary: true, uploaded_at: "2026-10-13T09:00:00Z" });
    expect(newerProfileCv(original, [doc(1), newer])?.id).toBe(7);
    // Upload z rekrutacji: dokument chwilę przed kopią — bez ramki.
    expect(
      newerProfileCv(snapshot("2026-10-13T09:00:05Z"), [
        doc(8, { is_primary: true, uploaded_at: "2026-10-13T09:00:00Z" }),
      ]),
    ).toBeNull();
    expect(newerProfileCv(original, [doc(9, { is_primary: true, uploaded_at: "2026-10-01T09:00:00Z" })])).toBeNull();
  });

  it("nowsze CV w profilu: liczy się plik, który skopiuje serwer — nie główne CV w TXT", () => {
    const original = snapshot("2026-10-08T10:00:00Z");
    const txt = doc(11, { is_primary: true, filename: "cv.txt", uploaded_at: "2026-10-13T09:00:00Z" });
    const oldPdf = doc(12, { filename: "stare.pdf", uploaded_at: "2026-10-01T09:00:00Z" });
    expect(newerProfileCv(original, [txt, oldPdf])).toBeNull();
    const newPdf = doc(13, { filename: "nowe.pdf", uploaded_at: "2026-10-12T09:00:00Z" });
    expect(newerProfileCv(original, [txt, oldPdf, newPdf])?.id).toBe(13);
  });

  it("nowsze CV w profilu: plik „nieaktualny” nie jest CV do skopiowania (audyt 13.10.2026)", () => {
    const original = snapshot("2026-10-08T10:00:00Z");
    const outdated = {
      ...doc(14, { filename: "cv_2024.pdf", uploaded_at: "2026-10-13T09:00:00Z" }),
      outdated_at: "2026-10-13T09:30:00Z",
    };
    expect(newerProfileCv(original, [outdated])).toBeNull();
  });

  it("nowsze CV w profilu: bez kopii i bez listy plików nie ma czego porównać", () => {
    const profileOnly = dockOriginalCv({
      snapshot: { has_snapshot: false },
      snapshotLoading: false,
      profileDocs: [doc(1, { is_primary: true, uploaded_at: "2026-10-13T09:00:00Z" })],
      profileDocsFailed: false,
    });
    expect(newerProfileCv(profileOnly, [doc(1, { is_primary: true, uploaded_at: "2026-10-13T09:00:00Z" })])).toBeNull();
    expect(newerProfileCv(snapshot("2026-10-08T10:00:00Z"), undefined)).toBeNull();
  });

  it("początek szkicu: dokument generatora, potem wybór gotowego CV, potem ostatnia zmiana", () => {
    const rows = [{ id: 5, created_at: "2026-10-10T08:00:00Z" }];
    expect(companyDraftSince({ status: "draft", generated_document_id: 5, updated_at: "2026-10-12T08:00:00Z" }, rows)).toBe(
      "2026-10-10T08:00:00Z",
    );
    expect(
      companyDraftSince(
        { status: "draft", origin: { kind: "upload", label: "x", selected_at: "2026-10-11T08:00:00Z" }, updated_at: "2026-10-12T08:00:00Z" },
        rows,
      ),
    ).toBe("2026-10-11T08:00:00Z");
    expect(companyDraftSince({ status: "draft", updated_at: "2026-10-12T08:00:00Z" }, undefined)).toBe("2026-10-12T08:00:00Z");
    expect(companyDraftSince(null, rows)).toBeNull();
  });

  it("szkic CV firmowego starszy niż podmienione CV — tylko szkic i tylko kopia podmieniona ręcznie", () => {
    const uploaded = snapshot("2026-10-13T13:10:00Z", "manual_upload");
    expect(companyCvStale({ brandedStatus: "draft", original: uploaded, draftSince: "2026-10-13T11:20:00Z" })).toBe(true);
    expect(companyCvStale({ brandedStatus: "finalized", original: uploaded, draftSince: "2026-10-13T11:20:00Z" })).toBe(false);
    expect(companyCvStale({ brandedStatus: "draft", original: uploaded, draftSince: "2026-10-13T14:00:00Z" })).toBe(false);
    expect(
      companyCvStale({
        brandedStatus: "draft",
        original: snapshot("2026-10-13T13:10:00Z", "stage_create"),
        draftSince: "2026-10-10T11:20:00Z",
      }),
    ).toBe(false);
    expect(companyCvStale({ brandedStatus: "draft", original: uploaded, draftSince: null })).toBe(false);
  });
});

// 15.10.2026: gotowe CV do klienta („B2B_…docx”) z kafelka „Wgraj nowe CV”
// idzie do CV do klienta, a w profilu zostaje obok CV kandydata.
describe("CV do klienta z kafelka (15.10.2026)", () => {
  it("naprawa kopii z CV do klienta: oryginał z profilu z nazwą pliku i datą", () => {
    expect(originalCvSentence(snapshot("2026-10-15T18:00:00Z", "client_cv_repair", "Jan_Testowy_CV.pdf"))).toBe(
      "Oryginał CV: z profilu · Jan_Testowy_CV.pdf · 15.10.2026",
    );
    expect(originalCvSentence({ kind: "snapshot", date: null, filename: null, source: "client_cv_repair" })).toBe(
      "Oryginał CV: z profilu",
    );
  });

  it("naprawa kopii umowy: oryginał z profilu, nie „dołączony do zgłoszenia”", () => {
    expect(originalCvSentence(snapshot("2026-10-30T18:00:00Z", "contract_repair", "Jan_Testowy_CV.pdf"))).toBe(
      "Oryginał CV: z profilu · Jan_Testowy_CV.pdf · 30.10.2026",
    );
    expect(
      companyCvStale({
        brandedStatus: "draft",
        original: snapshot("2026-10-30T18:00:00Z", "contract_repair"),
        draftSince: "2026-10-14T10:00:00Z",
      }),
    ).toBe(false);
  });

  it("naprawa kopii nie każe generować CV firmowego od nowa", () => {
    expect(
      companyCvStale({
        brandedStatus: "draft",
        original: snapshot("2026-10-15T18:00:00Z", "client_cv_repair"),
        draftSince: "2026-10-14T10:00:00Z",
      }),
    ).toBe(false);
  });

  it("plik „B2B_…” w profilu nie jest „nowszym CV” do skopiowania jako oryginał", () => {
    const original = snapshot("2026-10-08T10:00:00Z");
    const own = doc(21, { is_primary: true, filename: "Jan_Testowy_CV.pdf", uploaded_at: "2026-10-01T09:00:00Z" });
    const clientCv = doc(22, { filename: "B2B_Tester_Jan_Testowy.docx", uploaded_at: "2026-10-15T09:00:00Z" });
    expect(newerProfileCv(original, [own, clientCv])).toBeNull();
    // Stary import bez głównego CV: najnowszym plikiem jest CV do klienta — też bez ramki.
    expect(newerProfileCv(original, [{ ...own, is_primary: false }, clientCv])).toBeNull();
    // Nowe CV kandydata dalej wywołuje ramkę.
    const newOwn = doc(23, { is_primary: true, filename: "Jan_Testowy_CV_2026.pdf", uploaded_at: "2026-10-15T10:00:00Z" });
    expect(newerProfileCv(original, [newOwn, clientCv])?.id).toBe(23);
  });
});

describe("withoutQuarantinedCv", () => {
  const marker = (id: number) => ({ _identity_quarantine_source: { kind: "document", id } });

  it("zdejmuje plik z kwarantanny tożsamości (CV innej osoby)", () => {
    expect(withoutQuarantinedCv([doc(1), doc(9)], marker(9))?.map((d) => d.id)).toEqual([1]);
  });

  it("plik ponownie ustawiony jako główny zostaje", () => {
    expect(withoutQuarantinedCv([doc(9, { is_primary: true })], marker(9))?.map((d) => d.id)).toEqual([9]);
  });

  it("bez znacznika albo z innym rodzajem źródła lista bez zmian", () => {
    const docs = [doc(1), doc(9)];
    expect(withoutQuarantinedCv(docs, null)).toBe(docs);
    expect(withoutQuarantinedCv(docs, { _identity_quarantine_source: { kind: "legacy_cv", id: 9 } })).toBe(docs);
    expect(withoutQuarantinedCv(undefined, marker(9))).toBeUndefined();
  });
});
