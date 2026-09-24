import { describe, expect, it } from "vitest";

import {
  cvToClientShouldPoll,
  resolveCvToClient,
  stageCvBadge,
  stageCvStatus,
  type StageGeneratedCvRow,
} from "@/lib/cv-to-client";

const row = (overrides: Partial<StageGeneratedCvRow> & { id: number }): StageGeneratedCvRow => ({
  status: "ready",
  ...overrides,
});

describe("stageCvStatus / stageCvBadge", () => {
  it("szkic starego szablonu to „stary szablon”, nie gotowe CV", () => {
    expect(stageCvStatus({ status: "draft", from_generator: false })).toBe("legacy");
    expect(stageCvBadge({ status: "draft", from_generator: false })?.label).toBe(
      "CV do klienta: stary szablon",
    );
  });

  it("szkic z generatora i wersja zatwierdzona to „CV do klienta”", () => {
    expect(stageCvBadge({ status: "draft", from_generator: true })?.label).toBe("CV do klienta: szkic");
    expect(stageCvBadge({ status: "finalized", from_generator: true })?.label).toBe("CV do klienta: gotowe");
    // Stara ZATWIERDZONA wersja mogła już pójść do klienta — to dokument, nie odczyt.
    expect(stageCvStatus({ status: "finalized", from_generator: false })).toBe("ready");
  });

  it("brak CV nie jest plakietką", () => {
    expect(stageCvBadge({ status: "none" })).toBeNull();
    expect(stageCvBadge(undefined)).toBeNull();
  });
});

describe("resolveCvToClient", () => {
  it("gotowe CV niesie uwagi kontroli AI, brak zgody RODO i auto-CV do przejrzenia", () => {
    const state = resolveCvToClient({
      branded: { status: "draft", from_generator: true, generated_document_id: 5 },
      rows: [
        row({
          id: 5,
          origin: "auto",
          needs_review: true,
          consent_missing: true,
          factual_review: { status: "advisory", findings: 2 },
        }),
      ],
    });
    expect(state.kind).toBe("ready");
    expect(state.findings).toBe(2);
    expect(state.consentMissing).toBe(true);
    expect(state.needsReview).toBe(true);
    expect(state.candidate).toBeNull();
  });

  it("nowsza gotowa generacja obok podpiętej = „Użyj nowej wersji”, ale nie drugi język z tego samego pakietu", () => {
    const withNewer = resolveCvToClient({
      branded: { status: "finalized", from_generator: true, generated_document_id: 5 },
      rows: [row({ id: 5, package_id: 1 }), row({ id: 9, package_id: 2 })],
    });
    expect(withNewer.candidate?.id).toBe(9);

    const sibling = resolveCvToClient({
      branded: { status: "finalized", from_generator: true, generated_document_id: 5 },
      rows: [row({ id: 5, package_id: 1, language: "pl" }), row({ id: 6, package_id: 1, language: "en" })],
    });
    expect(sibling.candidate).toBeNull();
  });

  it("generacja w toku bez CV etapu = „generuje się” i odpytywanie", () => {
    const state = resolveCvToClient({
      branded: { status: "none" },
      rows: [row({ id: 3, status: "processing", origin: "auto" })],
    });
    expect(state.kind).toBe("generating");
    expect(cvToClientShouldPoll(state, null)).toBe(true);
  });

  it("nowa generacja obok gotowego CV też jest odpytywana (pojawi się „Użyj nowej wersji”)", () => {
    const state = resolveCvToClient({
      branded: { status: "finalized", from_generator: true, generated_document_id: 5 },
      rows: [row({ id: 5 }), row({ id: 6, status: "processing" })],
    });
    expect(state.kind).toBe("ready");
    expect(state.generating?.id).toBe(6);
    expect(cvToClientShouldPoll(state, null)).toBe(true);
  });

  it("zlecona z karty generacja, która padła, to „failed” z powodem", () => {
    const state = resolveCvToClient({
      branded: { status: "none" },
      rows: [row({ id: 4, status: "failed", error_message: "Brak pliku CV." })],
      pendingGeneratedId: 4,
    });
    expect(state.kind).toBe("failed");
    expect(state.failed?.error_message).toBe("Brak pliku CV.");
    expect(cvToClientShouldPoll(state, 4)).toBe(false);
  });

  it("gotowe CV bez podpięcia = „unattached”; czekamy na serwer, dopóki zlecone z karty", () => {
    const state = resolveCvToClient({
      branded: { status: "none" },
      rows: [row({ id: 7 })],
      pendingGeneratedId: 7,
    });
    expect(state.kind).toBe("unattached");
    expect(state.candidate?.id).toBe(7);
    expect(cvToClientShouldPoll(state, 7)).toBe(true);
    expect(cvToClientShouldPoll(state, null)).toBe(false);
  });

  it("stary szablon zostaje tylko do odczytu, a gotowa generacja jest proponowana obok", () => {
    const state = resolveCvToClient({
      branded: { status: "draft", from_generator: false },
      rows: [row({ id: 8 })],
    });
    expect(state.kind).toBe("legacy");
    expect(state.candidate?.id).toBe(8);
  });

  it("nic nie ma = „none”", () => {
    expect(resolveCvToClient({ branded: { status: "none" }, rows: [] }).kind).toBe("none");
  });
});
