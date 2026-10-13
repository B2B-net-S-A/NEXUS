import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  INTERVIEW_NOTIFICATION_TYPES,
  isInterviewNotificationType,
  parseInterviewLink,
  safeMeetingUrl,
} from "@/lib/interview-notifications";

// Ścieżka w cudzysłowie z `backend/`: filtr CI frontendu wylicza lustra
// backendu z takich literałów i uruchamia ten test przy zmianie tamtego pliku.
const CATEGORIES_FILE = "backend/app/services/notification_categories.py";
// Katalog repo z `process.cwd()` (vitest startuje w `frontend/`), jak w `capabilities.test.ts`.
const REPO_ROOT = resolve(process.cwd(), "..");

describe("typy kategorii „Rozmowy”", () => {
  it("są lustrem mapy typ → kategoria z backendu", () => {
    const source = readFileSync(join(REPO_ROOT, CATEGORIES_FILE), "utf8");
    const backend = [...source.matchAll(/^\s*_T\.(\w+): _C\.interviews,/gm)].map((m) => m[1]);

    expect(backend.length).toBeGreaterThan(0);
    expect([...INTERVIEW_NOTIFICATION_TYPES].sort()).toEqual([...backend].sort());
  });

  it("rozpoznaje typ po nazwie, a nie każde powiadomienie", () => {
    expect(isInterviewNotificationType("prep_attention")).toBe(true);
    expect(isInterviewNotificationType("stage_changed")).toBe(false);
    expect(isInterviewNotificationType(undefined)).toBe(false);
  });
});

describe("parseInterviewLink", () => {
  it("czyta parę i wydarzenie z parametrów adresu", () => {
    expect(parseInterviewLink("/calendar?cycle=12-34")).toEqual({
      pair: { candidateId: 12, jobId: 34 },
      eventId: null,
    });
    expect(parseInterviewLink("/calendar?cycle=12-34&debrief=7")).toEqual({
      pair: { candidateId: 12, jobId: 34 },
      eventId: 7,
    });
    expect(parseInterviewLink("/calendar?event=9&action=feedback")).toEqual({
      pair: null,
      eventId: 9,
    });
  });

  it("nie zgaduje przy braku albo zepsutych parametrach", () => {
    expect(parseInterviewLink(null)).toEqual({ pair: null, eventId: null });
    expect(parseInterviewLink("/calendar")).toEqual({ pair: null, eventId: null });
    expect(parseInterviewLink("/calendar?cycle=12-&event=abc")).toEqual({
      pair: null,
      eventId: null,
    });
  });
});

describe("safeMeetingUrl", () => {
  it("przepuszcza tylko adres https", () => {
    expect(safeMeetingUrl("https://teams.example.invalid/l/meetup")).toBe(
      "https://teams.example.invalid/l/meetup",
    );
    expect(safeMeetingUrl("javascript:alert(1)")).toBeNull();
    expect(safeMeetingUrl("http://teams.example.invalid")).toBeNull();
    expect(safeMeetingUrl(null)).toBeNull();
  });
});
