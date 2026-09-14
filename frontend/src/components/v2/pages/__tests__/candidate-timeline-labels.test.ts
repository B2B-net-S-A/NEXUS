import { describe, expect, it } from "vitest";

import {
  activityActionLabel,
  candidateStageLabel,
  noteTypeLabel,
  userActivityLabel,
} from "@/components/v2/pages/candidate-timeline-labels";
import { fileTypeLabel } from "@/components/v2/files/FilePreviewModal";

// UAT M01-B07 / M01-B10: profil kandydata pokazywał surowe slugi i typy MIME.
describe("candidate timeline labels", () => {
  it("translates the activity slugs seen on profiles", () => {
    expect(activityActionLabel("document_downloaded")).toBe("Pobrano plik");
    expect(activityActionLabel("cv_uploaded")).toBe("Wgrano CV");
    expect(activityActionLabel("updated")).toBe("Zaktualizowano profil");
    expect(activityActionLabel("created")).toBe("Utworzono profil kandydata");
  });

  it("never returns an unknown slug verbatim", () => {
    expect(activityActionLabel("some_future_action")).toBe("Zdarzenie systemowe");
    expect(userActivityLabel("some_future_action")).toBe("Akcja użytkownika");
    expect(noteTypeLabel("some_future_type")).toBeNull();
  });

  it("keeps Traffit event names readable without the source prefix", () => {
    expect(activityActionLabel("traffit:Email")).toBe("Email (z Traffita)");
  });

  it("translates user activity types", () => {
    expect(userActivityLabel("candidate_added")).toBe("Dodano kandydata");
  });

  it("labels pipeline stages, including keys missing from the shared map", () => {
    expect(candidateStageLabel("hired")).toBe("Zatrudniony");
    expect(candidateStageLabel("new")).toBe("Nowy");
    expect(candidateStageLabel("client_interview")).toBe("Rozmowa u klienta");
    expect(candidateStageLabel(null)).toBe("—");
  });
});

describe("fileTypeLabel", () => {
  it("shows a readable format instead of the MIME type", () => {
    expect(fileTypeLabel("application/pdf", "cv.pdf")).toBe("PDF");
    expect(
      fileTypeLabel(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "cv.docx",
      ),
    ).toBe("Dokument Word");
    expect(fileTypeLabel("application/octet-stream", "skan.xyz")).toBe("Plik XYZ");
    expect(fileTypeLabel("application/octet-stream", "bez-rozszerzenia")).toBeNull();
  });
});
