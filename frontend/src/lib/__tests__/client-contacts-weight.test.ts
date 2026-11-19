import { describe, expect, it } from "vitest";

import {
  OTHERS_COLLAPSE_FROM,
  contactWeight,
  contactWeightEntries,
} from "@/lib/client-contacts-weight";

const person = (name: string, extra: Partial<{ is_decision_maker: boolean; is_key_relationship: boolean; position: string | null }> = {}) => ({
  name,
  is_decision_maker: false,
  is_key_relationship: false,
  position: null as string | null,
  ...extra,
});

describe("kontakty klienta według wagi (19.11.2026)", () => {
  it("decydent i kluczowa relacja przed kierownikami, kierownicy przed resztą", () => {
    expect(contactWeight(person("A", { is_decision_maker: true }))).toBe("key");
    expect(contactWeight(person("B", { is_key_relationship: true }))).toBe("key");
    expect(contactWeight(person("C", { position: "Dyrektor Biura" }))).toBe("managers");
    expect(contactWeight(person("D", { position: "Kierownik Zespołu" }))).toBe("managers");
    expect(contactWeight(person("E", { position: "Head of Data" }))).toBe("managers");
    expect(contactWeight(person("F", { position: "Analityk" }))).toBe("others");
    expect(contactWeight(person("G"))).toBe("others");
  });

  it("długa reszta jest zwinięta za nagłówkiem z liczbą, a rozwinięta pokazuje wszystkich", () => {
    const contacts = [
      person("Robert Decydent", { is_decision_maker: true }),
      person("Agata Kierownik", { position: "Kierownik Testów" }),
      ...Array.from({ length: OTHERS_COLLAPSE_FROM + 2 }, (_, i) => person(`Osoba ${i}`)),
    ];
    const closed = contactWeightEntries(contacts, false);
    expect(closed.map((entry) => (entry.kind === "header" ? `# ${entry.label} · ${entry.count}` : entry.contact.name))).toEqual([
      "# Decydenci i kluczowe relacje · 1",
      "Robert Decydent",
      "# Kierownicy i dyrektorzy · 1",
      "Agata Kierownik",
      `# Pozostali · ${OTHERS_COLLAPSE_FROM + 2}`,
    ]);
    const open = contactWeightEntries(contacts, true);
    expect(open.filter((entry) => entry.kind === "contact")).toHaveLength(contacts.length);
  });

  it("bez decydentów i kierowników reszta się nie zwija — nie ma czego pokazać nad nią", () => {
    const contacts = Array.from({ length: 30 }, (_, i) => person(`Osoba ${i}`));
    const entries = contactWeightEntries(contacts, false);
    expect(entries.filter((entry) => entry.kind === "contact")).toHaveLength(30);
    expect(entries[0]).toMatchObject({ kind: "header", collapsible: false });
  });
});
