// Pakiet klienta do testów zakładki „Wejście u klienta”.
import type { ClientPack } from "@/lib/api/client-onboarding";

// Dane fikcyjne — repo jest publiczne.
export function packFixture(overrides: Partial<ClientPack> = {}): ClientPack {
  return {
    client_id: 7,
    exists: true,
    version: 3,
    updated_at: "2026-10-17T10:00:00+00:00",
    updated_by: 1,
    updated_by_name: "Kamil Przykładowy",
    equipment: {
      provider: "nasz",
      issue_template_id: null,
      return_template_id: null,
      ours: [
        { name: "Laptop 14 cali", note: null, assignee: null, offset_days: null, required: false, requires_file: false },
      ],
      client: [],
    },
    first_day: { contact_id: null, place: "ul. Przykładowa 20", time: "09:00", bring: null },
    documents: [
      {
        name: "Zaświadczenie o niekaralności",
        note: "nie starsze niż 3 miesiące",
        assignee: null,
        offset_days: -5,
        required: true,
        requires_file: true,
      },
    ],
    accesses: [
      {
        name: "Konto i VPN klienta",
        note: "zakłada klient",
        assignee: "delivery_lead",
        offset_days: -10,
        required: true,
        requires_file: false,
      },
    ],
    live_contracts: 2,
    options: {
      templates: [
        { id: 11, kind: "wydanie", name: "Z kaucją", description: null, is_active: true },
        { id: 12, kind: "zwrot", name: "Zwrot u klienta", description: null, is_active: true },
      ],
      contacts: [{ id: 5, name: "Piotr Przykładowy", position: "Kierownik zespołu" }],
      assignees: [
        { value: "care_owner", label: "Opiekun" },
        { value: "delivery_lead", label: "Delivery Lead" },
      ],
    },
    can_edit: { equipment: true, rest: true },
    ...overrides,
  };
}
