import { describe, expect, it } from "vitest";

import type { CvInTransit, CvTransitRow } from "@/lib/api/boardTasks";
import {
  transitAgo,
  transitCardEdit,
  transitIsEmpty,
  transitJobLabel,
  transitRemark,
  transitReturnedDetail,
  transitRowWho,
  transitSummary,
} from "@/lib/cv-in-transit";

function row(over: Partial<CvTransitRow> = {}): CvTransitRow {
  return {
    kind: "in_review",
    stage_id: 1,
    candidate_id: 2,
    candidate_name: "Adam Wrona",
    job_id: 3,
    job_title: "ZOB-1 Java Developer",
    job_working_title: "Java · Spring",
    client_name: "Bank Kappa",
    since: "2026-10-01T10:00:00Z",
    ...over,
  };
}

function transit(over: Partial<CvInTransit> = {}): CvInTransit {
  return {
    returned: [],
    in_review: [],
    sent: [],
    returned_total: 0,
    in_review_total: 0,
    sent_total: 0,
    returned_window_days: 14,
    sent_window_days: 7,
    ...over,
  };
}

describe("cv-in-transit — teksty listy „Twoje CV w drodze”", () => {
  it("pusta lista to brak CV w każdej z trzech grup (liczby z serwera, nie długości list)", () => {
    expect(transitIsEmpty(transit())).toBe(true);
    expect(transitIsEmpty(transit({ sent_total: 1 }))).toBe(false);
    expect(transitSummary(transit({ in_review_total: 3, sent_total: 2 }))).toBe(
      "W przeglądzie: 3 · Wysłane do klienta: 2",
    );
  });

  it("rekrutacja pokazuje tytuł dla rekrutera, a nazwę od klienta, gdy go nie ma", () => {
    expect(transitJobLabel(row())).toBe("Java · Spring · Bank Kappa");
    expect(transitJobLabel(row({ job_working_title: " ", client_name: null }))).toBe("ZOB-1 Java Developer");
  });

  it("osobna linia mówi, u kogo karta czeka albo kto ją wysłał", () => {
    expect(transitRowWho(row({ holder_name: "Marta Kowalczyk" }))).toBe("Przegląda: Marta Kowalczyk");
    // Rekrutacja bez Delivery Leada: przegląd idzie do portfela klienta.
    expect(transitRowWho(row())).toBe("Przegląda: Delivery Lead klienta");
    expect(transitRowWho(row({ kind: "cpro_queue", holder_name: "Adam Wzorcowy" }))).toBe(
      "Kolejka Cpro: Adam Wzorcowy",
    );
    expect(transitRowWho(row({ kind: "cpro_queue" }))).toBe("Kolejka Cpro");
    expect(transitRowWho(row({ kind: "sent", actor_name: "Jan Dąb" }))).toBe("Wysłane przez: Jan Dąb");
    expect(transitRowWho(row({ kind: "sent" }))).toBeNull();
    expect(transitRowWho(row({ kind: "sent_back", actor_name: "Jan Dąb" }))).toBeNull();
  });

  it("przy zwrocie powód wygrywa z nazwiskiem; bez obu zostaje sama plakietka", () => {
    expect(transitReturnedDetail(row({ kind: "rejected_by_dl", reason: "stawka", actor_name: "Jan Dąb" }))).toBe(
      "stawka",
    );
    expect(transitReturnedDetail(row({ kind: "sent_back", reason: " ", actor_name: "Jan Dąb" }))).toBe("Jan Dąb");
    expect(transitReturnedDetail(row({ kind: "sent_back" }))).toBeNull();
  });

  it("uwaga dla rekrutera to osobna linia; pusta nie daje nic", () => {
    expect(transitRemark(row({ kind: "sent_back", remark: " Dopisz Spring Boot " }))).toBe(
      "Uwaga: Dopisz Spring Boot",
    );
    expect(transitRemark(row({ kind: "sent", remark: "  " }))).toBeNull();
    expect(transitRemark(row({ kind: "sent" }))).toBeNull();
  });

  it("„kiedy” liczy dni kalendarzowe w Warszawie", () => {
    const now = new Date("2026-10-02T07:00:00Z");
    expect(transitAgo("2026-10-02T05:30:00Z", now)).toBe("dziś");
    // 1.10 o 21:30 UTC to już 23:30 w Warszawie tego samego dnia — „wczoraj”.
    expect(transitAgo("2026-10-01T21:30:00Z", now)).toBe("wczoraj");
    // 1.10 o 22:30 UTC to 00:30 dnia 2.10 w Warszawie — „dziś”.
    expect(transitAgo("2026-10-01T22:30:00Z", now)).toBe("dziś");
    expect(transitAgo("2026-09-28T10:00:00Z", now)).toBe("4 dni temu");
    expect(transitAgo("nie-data", now)).toBe("dziś");
  });
});


describe("transitCardEdit — ślad poprawek karty (D4, 04.10.2026)", () => {
  it("mówi, kto i które pola poprawił", () => {
    expect(
      transitCardEdit(row({ card_edited_by: "Piotr Zieliński", card_edited_fields: ["Motywacja", "Stawka"] })),
    ).toBe("Piotr Zieliński poprawił(a) w karcie: Motywacja, Stawka");
  });

  it("bez nazw pól mówi ogólnie, bez poprawek — nic", () => {
    expect(transitCardEdit(row({ card_edited_by: "Piotr Zieliński", card_edited_fields: [] }))).toBe(
      "Piotr Zieliński poprawił(a) kartę rekomendacji",
    );
    expect(transitCardEdit(row())).toBeNull();
  });
});
