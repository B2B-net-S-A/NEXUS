import { describe, expect, it } from "vitest";

import type { AdFinding } from "@/lib/api/jobAd";

import {
  editorText,
  findingsByField,
  isEditKey,
  ownOfferLines,
  sameItem,
  withEdited,
  withoutExcerpt,
  withoutTech,
  withTechLevel,
  withTechNames,
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
    for (const key of [
      "title",
      "lead",
      "about",
      "start",
      "language",
      "offer",
      "requirements",
      "process",
    ]) {
      expect(isEditKey(key)).toBe(true);
    }
    for (const key of ["terms", "fixed", "tech", "tech_required", "", null, undefined]) {
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

describe("job-ad-edit — własne punkty „To oferujemy” (zgłoszenie 28.10.2026)", () => {
  const locked = ["kontrakt B2B", "praca zdalna", "prywatna opieka medyczna"];

  it("wklejona lista z karty zostawia tylko własne punkty", () => {
    const pasted = "Kontrakt  B2B\npraca zdalna\nduży projekt bankowy\nprywatna opieka medyczna\n";
    expect(ownOfferLines(pasted, locked)).toEqual({
      items: ["duży projekt bankowy"],
      skipped: 3,
    });
  });

  it("powtórzony własny punkt liczy się raz", () => {
    expect(ownOfferLines("projekt\nProjekt\n\nzespół", [])).toEqual({
      items: ["projekt", "zespół"],
      skipped: 1,
    });
  });

  it("ukryte punkty zapisują się razem z poprawką pola", () => {
    expect(withEdited(CONTENT, "offer", "a\nb").offer).toEqual(["a", "b"]);
    expect(sameItem(" Prywatna  opieka medyczna", "prywatna opieka medyczna")).toBe(true);
  });
});

describe("job-ad-edit — karta Pracuj.pl: technologie i etapy (zgłoszenie 18.11.2026)", () => {
  it("„Technologie wymagane” zachowują poziom znanych nazw, nowe są wymagane", () => {
    expect(withTechNames(TECH, "tech_required", "java\nSpring Boot\n\n")).toEqual([
      { name: "java", level: "critical" },
      { name: "Spring Boot", level: "must" },
      { name: "Kubernetes", level: "nice" },
    ]);
  });

  it("nazwa przeniesiona do drugiej listy zmienia poziom i nie zostaje w obu", () => {
    expect(withTechNames(TECH, "tech_required", "Java\nKafka\nKubernetes")).toEqual([
      { name: "Java", level: "critical" },
      { name: "Kafka", level: "must" },
      { name: "Kubernetes", level: "must" },
    ]);
    expect(withTechNames(TECH, "tech_optional", "Kubernetes\nKafka\nDocker\ndocker")).toEqual([
      { name: "Java", level: "critical" },
      { name: "Kubernetes", level: "nice" },
      { name: "Kafka", level: "nice" },
      { name: "Docker", level: "nice" },
    ]);
  });

  it("pusta lista mile widzianych usuwa tylko je", () => {
    expect(withTechNames(TECH, "tech_optional", "")).toEqual(TECH.slice(0, 2));
  });

  it("etapy bez własnej listy otwierają się z tym, co widać na karcie", () => {
    expect(editorText(CONTENT, "process", ["Rozmowa z rekruterem", "Rozmowa z klientem"])).toBe(
      "Rozmowa z rekruterem\nRozmowa z klientem",
    );
    const own = { ...CONTENT, process: ["Rozmowa z klientem"] };
    expect(editorText(own, "process", ["coś innego"])).toBe("Rozmowa z klientem");
    expect(withEdited(CONTENT, "process", "  Test online \n\nRozmowa").process).toEqual([
      "Test online",
      "Rozmowa",
    ]);
  });
});
