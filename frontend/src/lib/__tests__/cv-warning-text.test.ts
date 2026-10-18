import { describe, expect, it } from "vitest";

import cases from "@/lib/__fixtures__/cv-warning-cases.json";
import { classifyCvWarnings } from "@/lib/cv-generator";
import { humanizeCvWarning } from "@/lib/cv-warning-text";

describe("uwagi generatora po ludzku (18.10.2026)", () => {
  it("Kalwala, 789131: strażnik lat po angielsku → jedno zdanie po polsku, co sprawdzić", () => {
    expect(
      humanizeCvWarning(
        "NOT IN SOURCE: '32 year' (why_points) follows neither from the source nor from the dates — „32 years of experience in IT”",
      ),
    ).toBe(
      "Sprawdź „32 year” w sekcji „Dlaczego nasz kandydat”: tej liczby lat nie ma w oryginale i nie wynika ona z dat stanowisk.",
    );
    expect(
      humanizeCvWarning("BRAK POKRYCIA: '9 lat' (Java Developer) nie wynika ani ze źródła, ani z dat — „9 lat”"),
    ).toBe("Sprawdź „9 lat” w stanowisku „Java Developer”: tej liczby lat nie ma w oryginale i nie wynika ona z dat stanowisk.");
  });

  it("protokolarne odrzucenie kontroli AI bez kodu powodu", () => {
    const pl = "Kontrola AI nie dała czytelnego wyniku — przeczytaj CV obok oryginału, zanim je wyślesz.";
    expect(
      humanizeCvWarning(
        "VERIFY: the independent AI review did not confirm the document (invalid_coverage) — check it against the original by hand.",
      ),
    ).toBe(pl);
    expect(
      humanizeCvWarning(
        "WERYFIKUJ: niezależna kontrola AI treści CV nie potwierdziła dokumentu (invalid_coverage) — sprawdź CV ręcznie z oryginałem.",
      ),
    ).toBe(pl);
    expect(
      humanizeCvWarning(
        "VERIFY: the independent AI review did not run (timeout) — check the CV against the original by hand.",
      ),
    ).toBe("Kontrola AI się nie wykonała — przeczytaj CV obok oryginału, zanim je wyślesz.");
  });

  it("pozostałe angielskie szablony generatora → po polsku", () => {
    expect(
      humanizeCvWarning("NOT IN SOURCE: figure '40%' (Allegro) does not appear in the CV or notes — „cut costs by 40%”"),
    ).toBe("Sprawdź liczbę „40%” w stanowisku „Allegro”: nie ma jej w oryginale CV ani w notatkach.");
    expect(
      humanizeCvWarning("VERIFY: scale claim 'enterprise-wide' (why_points) has no basis in the source — „x”"),
    ).toBe("Sprawdź określenie „enterprise-wide” w sekcji „Dlaczego nasz kandydat”: oryginał nie mówi o takiej skali.");
    expect(humanizeCvWarning('NOT IN SOURCE (AI review): experience — "banking" (not confirmed in the CV or notes)')).toBe(
      "Kontrola AI: doświadczenie — „banking” (brak potwierdzenia w CV i notatkach).",
    );
    expect(humanizeCvWarning("VERIFY: certification 'CKA' not found in the CV or notes")).toBe(
      "Sprawdź certyfikat „CKA”: nie ma go w CV ani w notatkach.",
    );
    expect(humanizeCvWarning("VERIFY: technology 'Kafka' (Allegro) not found in the CV or notes")).toBe(
      "Sprawdź technologię „Kafka” w stanowisku „Allegro”: nie ma jej w CV ani w notatkach.",
    );
    expect(
      humanizeCvWarning("VERIFY: overlapping employment periods: 'Allegro' (01.2020 – 12.2022) and 'Freelance' (06.2021 – 03.2023)"),
    ).toBe("Nakładające się okresy zatrudnienia: „Allegro” (01.2020 – 12.2022) i „Freelance” (06.2021 – 03.2023).");
    expect(humanizeCvWarning("… and 3 more items to verify")).toBe("… i 3 kolejnych pozycji do sprawdzenia");
  });

  it("nieznana uwaga zostaje bez zmian, a klasyfikacja nadal liczy się z surowego tekstu", () => {
    expect(humanizeCvWarning("Coś zupełnie nowego z backendu")).toBe("Coś zupełnie nowego z backendu");
    expect(humanizeCvWarning("MUST-HAVE: Kubernetes")).toBe("MUST-HAVE: Kubernetes");
    // Każdy przypadek z katalogu daje niepusty tekst; wynik QC (grupy) się nie zmienia.
    for (const c of cases.cases) {
      expect(humanizeCvWarning(c.text).length).toBeGreaterThan(0);
      const { review, info } = classifyCvWarnings([c.text]);
      expect([...review, ...info][0]?.group).toBe(c.group);
    }
  });
});
