import { describe, expect, it } from "vitest";

import type { CareerBoardJob, CareerJobResponse } from "@/lib/career/api";
import {
  buildPostData,
  carouselSlides,
  hashtag,
  isPostVariant,
  postComment,
  postDuties,
  postGraphicPath,
  postHashtags,
  postText,
} from "@/lib/career/postGraphic";

function response(overrides: Partial<CareerJobResponse["job"]> = {}, status: "open" | "closed" = "open"): CareerJobResponse {
  return {
    status,
    recruiter: { first_name: "Maciej", slug: null },
    canonical_slug: "programista-python-zeh1",
    job: {
      slug: "programista-python-zeh1",
      title: "Programista Python",
      subtitle: "Szukamy Programisty Python do rozwoju backendu aplikacji bankowości elektronicznej",
      about:
        "Projekt obejmuje mikrousługi.\n\nCzym się zajmiesz: Tworzenie mikrousług w FastAPI; Budowa BFF (Backend for Frontend); Udział w code review.",
      must: [{ name: "Doświadczenie w programowaniu w Pythonie", note: null }],
      nice: ["Doświadczenie z CI/CD"],
      params: {
        city: "Warszawa",
        remote_policy: "hybrid",
        onsite_days_per_week: 1,
        onsite_days_per_month: 4,
        seniority: null,
        contract: "B2B",
        start: null,
        duration: null,
      },
      show: { must: true, nice: true, params: true, process: true },
      ...overrides,
    },
  };
}

const BOARD: CareerBoardJob[] = [
  {
    slug: "programista-python-zeh1",
    title: "Programista Python",
    subtitle: null,
    city: "Warszawa",
    remote_policy: "hybrid",
    category: "development",
    theme: "terminal",
    recruiter_first_name: "Maciej",
    must: ["Python", "FastAPI", "REST API", "Code review", "Git"],
  },
];

describe("grafika i treść posta na LinkedIn", () => {
  it("dane z publicznej odpowiedzi i tablicy: technologie, linia faktów, mapa z miastem", () => {
    const d = buildPostData(response(), BOARD, "kariera.b2bnetwork.pl");
    expect(d).not.toBeNull();
    expect(d?.tags).toEqual(["Python", "FastAPI", "REST API"]);
    expect(d?.word).toBe("Python");
    expect(d?.line).toBe("Warszawa · hybryda · B2B");
    expect(d?.office).toBe("biuro 4 dni w miesiącu");
    expect(d?.map.kind).toBe("focus");
    expect(d?.duties).toEqual(["Tworzenie mikrousług w FastAPI", "Budowa BFF (Backend for Frontend)", "Udział w code review"]);
    expect(d?.steps).toHaveLength(4);
    expect(d?.host).toBe("kariera.b2bnetwork.pl");
  });

  it("zamknięta rekrutacja nie dostaje posta", () => {
    expect(buildPostData(response({}, "closed"), BOARD, "kariera.b2bnetwork.pl")).toBeNull();
  });

  it("sekcje ukryte przełącznikiem „pokaż” nie trafiają do grafiki ani karuzeli", () => {
    const d = buildPostData(
      response({ show: { must: false, nice: false, params: false, process: false } }),
      BOARD,
      "kariera.b2bnetwork.pl",
    );
    expect(d?.must).toEqual([]);
    expect(d?.nice).toEqual([]);
    expect(d?.steps).toEqual([]);
    expect(d?.line).toBeNull();
    expect(d?.map.kind).toBe("none");
    expect(carouselSlides(d!)).toEqual(["cover", "duties", "apply"]);
  });

  it("praca zdalna = cała mapa, bez podpisu biura", () => {
    const d = buildPostData(
      response({ params: { ...response().job.params!, city: null, remote_policy: "remote" } }),
      BOARD,
      "kariera.b2bnetwork.pl",
    );
    expect(d?.map.kind).toBe("remote");
    expect(d?.office).toBeNull();
    expect(d?.line).toBe("Zdalnie z całej Polski · B2B");
  });

  it("karuzela ma tylko slajdy z treścią; okładka i zakończenie zawsze", () => {
    const full = buildPostData(response(), BOARD, "h")!;
    expect(carouselSlides(full)).toEqual(["cover", "duties", "must", "apply"]);
    const bare = buildPostData(response({ about: "Sam opis.", must: [] }), BOARD, "h")!;
    expect(carouselSlides(bare)).toEqual(["cover", "apply"]);
  });

  it("obowiązki z opisu: punkty po średniku, długie ucięte na granicy słowa", () => {
    expect(postDuties(null)).toEqual([]);
    expect(postDuties("Bez listy obowiązków.")).toEqual([]);
    const [long] = postDuties(`Czym się zajmiesz: ${"słowo ".repeat(30)}koniec`);
    expect(long.length).toBeLessThanOrEqual(81);
    expect(long.endsWith("słowo…")).toBe(true);
  });

  it("hashtagi: znane technologie po ludzku, śmieci odpadają, na końcu #praca #b2b", () => {
    expect(hashtag("C#")).toBe("#csharp");
    expect(hashtag(".NET")).toBe("#dotnet");
    expect(hashtag("REST API")).toBe("#restapi");
    expect(hashtag("Zarządzanie projektami")).toBe("#zarządzanieprojektami");
    expect(hashtag("8")).toBeNull();
    expect(postHashtags(["Python", "python", "FastAPI"])).toEqual(["#python", "#fastapi", "#praca", "#b2b"]);
  });

  it("treść posta: tytuł, miejsce, zdanie o projekcie, technologie i gdzie jest link — bez adresu", () => {
    const text = postText(buildPostData(response(), BOARD, "kariera.b2bnetwork.pl")!);
    expect(text.split("\n")[0]).toBe("Nowa rekrutacja: Programista Python");
    expect(text).toContain("Warszawa · hybryda · B2B (biuro 4 dni w miesiącu)");
    expect(text).toContain("Czego szukamy: Python, FastAPI, REST API, Code review, Git.");
    expect(text).toContain("Link do aplikacji w pierwszym komentarzu ↓");
    expect(text).not.toMatch(/https?:\/\//);
    expect(text.trim().split("\n").pop()).toBe("#python #fastapi #restapi #codereview #praca #b2b");
  });

  it("komentarz i adresy grafik", () => {
    expect(postComment("https://kariera.b2bnetwork.pl/r/x-1abc")).toBe("Aplikuj tutaj: https://kariera.b2bnetwork.pl/r/x-1abc");
    expect(postGraphicPath("x-1abc", "mapa")).toBe("/kariera/r/x-1abc/grafika-posta?v=mapa");
    expect(postGraphicPath("x-1abc", "karuzela", 3)).toBe("/kariera/r/x-1abc/grafika-posta?v=karuzela&s=3");
    expect(isPostVariant("konkrety")).toBe(true);
    expect(isPostVariant("grafit")).toBe(false);
  });
});
