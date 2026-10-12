import { describe, expect, it } from "vitest";

import type { AdFinding } from "@/lib/api/jobAd";

import {
  editorText,
  findingsByField,
  isEditKey,
  withEdited,
  withoutExcerpt,
  withoutTech,
  withTechLevel,
} from "../job-ad-edit";
import { CONTENT, TECH } from "./job-ad-fixtures";

const finding = (patch: Partial<AdFinding>): AdFinding => ({
  code: "client_name",
  severity: "block",
  message: "…",
  excerpt: null,
  field: null,
  ...patch,
});

describe("job-ad-edit — pole ogłoszenia ↔ tekst w edytorze", () => {
  it("lista to jedna pozycja w wierszu, w obie strony", () => {
    expect(editorText(CONTENT, "requirements")).toBe(
      "min. 5 lat doświadczenia w Javie\npraktyka z Apache Kafka",
    );
    expect(withEdited(CONTENT, "requirements", " Java 21 \n\nKafka\n").requirements).toEqual([
      "Java 21",
      "Kafka",
    ]);
  });

  it("opis zachowuje akapity, pozostałe pola to jedna linia", () => {
    expect(withEdited(CONTENT, "about", " Akapit 1.\n\nAkapit 2. ").about).toBe(
      "Akapit 1.\n\nAkapit 2.",
    );
    expect(withEdited(CONTENT, "title", " Senior\n Java   Developer ").title).toBe(
      "Senior Java Developer",
    );
  });

  it("nie zmienia pozostałych pól ani oryginału", () => {
    const next = withEdited(CONTENT, "lead", "Nowy wstęp.");
    expect(next).not.toBe(CONTENT);
    expect(next.requirements).toBe(CONTENT.requirements);
    expect(CONTENT.lead).toBe("Szukamy osoby do zespołu płatności.");
  });

  it("rozpoznaje pola, które rekruter poprawia w oknie", () => {
    for (const key of ["title", "lead", "about", "start", "language", "offer", "requirements"]) {
      expect(isEditKey(key)).toBe(true);
    }
    for (const key of ["terms", "fixed", "tech", "process", "", null, undefined]) {
      expect(isEditKey(key)).toBe(false);
    }
  });
});

describe("job-ad-edit — „Usuń fragment”", () => {
  it("wycina fragment z pola tekstowego", () => {
    const content = { ...CONTENT, about: "Platforma dla klienta Bank Przykładowy. Scrum." };
    const next = withoutExcerpt(
      content,
      finding({ field: "about", excerpt: "dla klienta Bank Przykładowy" }),
    );
    expect(next?.about).toBe("Platforma. Scrum.");
  });

  it("pozycja listy, z której nic nie zostało, znika", () => {
    const content = { ...CONTENT, offer: ["stawka do 150 zł/h", "projekt na lata"] };
    const next = withoutExcerpt(
      content,
      finding({ code: "money", field: "offer", excerpt: "stawka do 150 zł/h" }),
    );
    expect(next?.offer).toEqual(["projekt na lata"]);
  });

  it("zwraca null, gdy fragmentu nie ma albo pole nie należy do treści", () => {
    expect(withoutExcerpt(CONTENT, finding({ field: "about", excerpt: "nie ma" }))).toBeNull();
    expect(withoutExcerpt(CONTENT, finding({ field: "about", excerpt: null }))).toBeNull();
    expect(withoutExcerpt(CONTENT, finding({ field: "fixed", excerpt: "Kubernetes" }))).toBeNull();
    expect(withoutExcerpt(CONTENT, finding({ field: "terms", excerpt: "Warszawa" }))).toBeNull();
  });
});

describe("job-ad-edit — technologie i znaleziska", () => {
  it("zmienia poziom i usuwa technologię po nazwie", () => {
    expect(withTechLevel(TECH, "Kafka", "critical")[1]).toEqual({
      name: "Kafka",
      level: "critical",
    });
    expect(withoutTech(TECH, "Java").map((t) => t.name)).toEqual(["Kafka", "Kubernetes"]);
    expect(TECH).toHaveLength(3);
  });

  it("grupuje znaleziska po polu, pomijając te bez pola", () => {
    const map = findingsByField([
      finding({ field: "about" }),
      finding({ field: "about", code: "money" }),
      finding({ field: null }),
    ]);
    expect(map.get("about")).toHaveLength(2);
    expect(map.size).toBe(1);
  });
});
