import { describe, expect, it } from "vitest";

import { extractClientQuestions, looksLikeClientQuestions } from "@/lib/client-question-notes";

describe("looksLikeClientQuestions", () => {
  it("rozpoznaje notatkę po rozmowie u klienta", () => {
    expect(looksLikeClientQuestions("Po rozmowie z klientem. Klient pytał o Kafkę.")).toBe(true);
    expect(looksLikeClientQuestions("Na technicznej pytali o testy integracyjne")).toBe(true);
    expect(looksLikeClientQuestions("Po rozmowie: Jak testujesz? Czy znasz Kafkę?")).toBe(true);
  });

  it("zwykła notatka nie daje podpowiedzi", () => {
    expect(looksLikeClientQuestions("")).toBe(false);
    expect(looksLikeClientQuestions("Kandydat ma drugą ofertę, oddzwoni w piątek.")).toBe(false);
    // Pytanie kandydata, nie klienta — bez kontekstu rozmowy.
    expect(looksLikeClientQuestions("Pytała o urlop w grudniu.")).toBe(false);
  });
});

describe("extractClientQuestions", () => {
  it("lista po „pytał o:” w jednym zdaniu", () => {
    expect(
      extractClientQuestions(
        "Po rozmowie z klientem. Klient pytał o: różnice między Spring Boot 2 i 3, jak testuje integracje z Kafką, doświadczenie z Kubernetesem. Kandydatka zadowolona.",
      ),
    ).toEqual([
      "Różnice między Spring Boot 2 i 3",
      "Jak testuje integracje z Kafką",
      "Doświadczenie z Kubernetesem",
    ]);
  });

  it("lista w liniach z punktorami", () => {
    expect(
      extractClientQuestions("Klient pytał:\n- Spring Boot 2 vs 3\n2. testy Kafki\n• Kubernetes"),
    ).toEqual(["Spring Boot 2 vs 3", "Testy Kafki", "Kubernetes"]);
  });

  it("pytania ze znakami zapytania", () => {
    expect(
      extractClientQuestions("Rozmowa techniczna: Jak testujesz Kafkę? Czy znasz Helm? Ile lat Java?"),
    ).toEqual(["Rozmowa techniczna: Jak testujesz Kafkę", "Czy znasz Helm", "Ile lat Java?"]);
  });

  it("bez powtórzeń i krótkich śmieci", () => {
    expect(extractClientQuestions("Klient pytał o: Kafka, kafka, ok")).toEqual(["Kafka"]);
  });
});
