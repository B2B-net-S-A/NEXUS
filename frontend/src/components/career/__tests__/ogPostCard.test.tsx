import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PostCardFacts, PostCardMap, PostCarouselSlide } from "@/components/career/ogPostCard";
import type { PostData } from "@/lib/career/postGraphic";

const DATA: PostData = {
  tags: ["Python", "FastAPI"],
  word: "Python",
  title: "Programista Python",
  line: "Warszawa · hybryda · B2B",
  sub: "Prowadzi Maciej",
  map: { kind: "none" },
  host: "kariera.b2bnetwork.pl",
  duties: ["Tworzenie mikrousług w FastAPI"],
  must: ["Doświadczenie w Pythonie"],
  nice: [],
  skills: ["Python", "FastAPI"],
  steps: [],
  subtitle: null,
  office: null,
};

describe("grafika posta na LinkedIn", () => {
  it("Mapa: tytuł, linia faktów i gdzie jest link — bez udawanego przycisku", () => {
    const { container } = render(<PostCardMap d={DATA} />);
    const text = container.textContent ?? "";
    expect(text).toContain("Programista Python");
    expect(text).toContain("Warszawa · hybryda · B2B");
    expect(text).toContain("Link do aplikacji w komentarzu");
    expect(text).not.toContain("Wyślij CV");
    expect(text).toContain("kariera.b2bnetwork.pl");
  });

  it("Konkrety: wielkie słowo, obowiązki i technologie", () => {
    const text = render(<PostCardFacts d={DATA} />).container.textContent ?? "";
    expect(text).toContain("Szukamy");
    expect(text).toContain("Tworzenie mikrousług w FastAPI");
    expect(text).toContain("Czego szukamy");
  });

  it("karuzela: numer slajdu z listy slajdów; bez kroków procesu ostatni slajd mówi, jak aplikować", () => {
    const slides = ["cover", "duties", "apply"] as const;
    expect(render(<PostCarouselSlide d={DATA} slides={slides} index={1} />).container.textContent).toContain("2 / 3");
    const last = render(<PostCarouselSlide d={DATA} slides={slides} index={2} />).container.textContent ?? "";
    expect(last).toContain("Jak aplikować");
    expect(last).toContain("pierwszym komentarzu");
  });
});
