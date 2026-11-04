/**
 * „Dział” i „Podlega pod” w formularzu kontaktu (22.10.2026): po zapisie
 * kontaktu idzie tylko różnica pól (`PATCH …/contacts/{id}`), „Nowy dział…”
 * wygrywa z listą, a edycja startuje od stanu z drzewa. Dane fikcyjne.
 */
import { describe, expect, it } from "vitest";

import {
  EMPTY_CONTACT_ORG,
  contactOrgDraftFor,
  contactOrgPayload,
} from "@/components/care/client/ContactOrgFields";
import { clientOrg } from "@/app/preview/hr-client-people/fixtures";

const org = clientOrg("2026-10-22");

describe("contactOrgDraftFor", () => {
  it("edycja startuje od działu i przełożonego z drzewa; nowy kontakt — pusto", () => {
    expect(contactOrgDraftFor(org, 8202)).toEqual({
      areaId: 303,
      newAreaName: "",
      addingArea: false,
      reportsToId: 8201,
    });
    expect(contactOrgDraftFor(org, null)).toEqual(EMPTY_CONTACT_ORG);
    expect(contactOrgDraftFor(null, 8202)).toEqual(EMPTY_CONTACT_ORG);
  });
});

describe("contactOrgPayload", () => {
  const initial = contactOrgDraftFor(org, 8202);

  it("bez zmian nie ma czego zapisywać", () => {
    expect(contactOrgPayload(initial, initial)).toBeNull();
    expect(contactOrgPayload(EMPTY_CONTACT_ORG, EMPTY_CONTACT_ORG)).toBeNull();
  });

  it("zmieniony dział i przełożony idą razem; „Bez działu” to null", () => {
    expect(contactOrgPayload({ ...initial, areaId: 301, reportsToId: null }, initial)).toEqual({
      client_area_id: 301,
      reports_to_contact_id: null,
    });
    expect(contactOrgPayload({ ...initial, areaId: null }, initial)).toEqual({
      client_area_id: null,
    });
  });

  it("„Nowy dział…” z nazwą wygrywa z listą; pusta nazwa niczego nie zakłada", () => {
    expect(
      contactOrgPayload({ ...initial, addingArea: true, newAreaName: "  Ryzyko  " }, initial),
    ).toEqual({ new_area_name: "Ryzyko" });
    expect(contactOrgPayload({ ...initial, addingArea: true, newAreaName: " " }, initial)).toBeNull();
  });
});
