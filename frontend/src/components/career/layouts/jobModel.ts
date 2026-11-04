/**
 * Model ogłoszenia dla trzech układów strony rekrutacji (szablony Terminal,
 * Grafit, Jasny — decyzja Artura 28.10.2026 po feedbacku zespołu). Dane
 * wyłącznie z publicznej odpowiedzi `/api/public/career/r/<slug>` (biała lista
 * — bez klienta i stawek). Fakty z wielkiej litery i „Czym się zajmiesz” jako
 * punkty, bo jeden blok drobnego tekstu był najczęstszą uwagą zespołu.
 */
import type { CareerJobResponse } from "@/lib/career/api";
import { aboutParagraphs, remoteLabel } from "@/lib/career/format";
import { processSteps, type ProcessStep } from "../requirementItems";

export interface MockFact {
  key: "city" | "mode" | "contract" | "seniority" | "start";
  label: string;
  value: string;
}

export interface MockAboutBlock {
  /** „Czym się zajmiesz” itp. — gdy akapit zaczyna się od „Nagłówek: …”. */
  heading: string | null;
  text: string | null;
  /** Punkty, gdy treść po nagłówku to lista rozdzielona średnikami. */
  bullets: string[];
}

export interface MockJob {
  slug: string;
  title: string;
  subtitle: string | null;
  /** Fakty do pierwszego ekranu, ludzkim językiem i z wielkiej litery. */
  facts: MockFact[];
  /** Jedna linia: „Gdańsk, Gdynia, Warszawa, Łódź · Hybryda 3 dni w biurze · B2B”. */
  factsLine: string;
  about: MockAboutBlock[];
  must: { name: string; note: string | null }[];
  nice: string[];
  steps: ProcessStep[];
  recruiterFirstName: string;
}

function cap(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase("pl-PL") + text.slice(1) : text;
}

function modeValue(data: CareerJobResponse): string | null {
  const p = data.job.params;
  const mode = remoteLabel(p?.remote_policy);
  if (!p || !mode) return null;
  if (p.remote_policy !== "hybrid") return cap(mode);
  if (p.onsite_days_per_month) return `Hybryda · ${p.onsite_days_per_month} dni w biurze w miesiącu`;
  if (p.onsite_days_per_week) {
    const d = p.onsite_days_per_week;
    return `Hybryda · ${d} ${d === 1 ? "dzień" : "dni"} w biurze w tygodniu`;
  }
  return "Hybryda";
}

/** „Czym się zajmiesz: a; b; c” → nagłówek + punkty (dziś to jeden blok drobnego tekstu). */
function aboutBlock(paragraph: string): MockAboutBlock {
  const m = /^([^:.;]{3,40}):\s*([\s\S]+)$/.exec(paragraph);
  const heading = m ? m[1].trim() : null;
  const rest = (m ? m[2] : paragraph).trim();
  const parts = rest
    .split(/;\s*/)
    .map((s) => s.trim().replace(/[.;]$/, ""))
    .filter(Boolean);
  if (parts.length >= 3) return { heading, text: null, bullets: parts.map(cap) };
  return { heading, text: rest, bullets: [] };
}

export function mockJob(data: CareerJobResponse): MockJob {
  const { job, recruiter } = data;
  const show = job.show ?? { must: true, nice: true, params: true, process: true };
  const p = show.params ? job.params : null;
  const facts: MockFact[] = [];
  if (p?.city?.trim()) facts.push({ key: "city", label: "Lokalizacja", value: p.city.trim() });
  const mode = p ? modeValue(data) : null;
  if (mode) facts.push({ key: "mode", label: "Tryb pracy", value: mode });
  if (p?.contract?.trim()) facts.push({ key: "contract", label: "Umowa", value: p.contract.trim() });
  if (p?.seniority?.trim()) facts.push({ key: "seniority", label: "Poziom", value: cap(p.seniority.trim()) });
  const start = [p?.start?.trim(), p?.duration?.trim()].filter(Boolean).join(" · ");
  if (start) facts.push({ key: "start", label: "Start", value: cap(start) });
  return {
    slug: job.slug,
    title: job.title.trim(),
    subtitle: job.subtitle?.trim() || null,
    facts,
    factsLine: facts
      .filter((f) => f.key !== "start")
      .map((f) => (f.key === "mode" ? f.value.replace(" · ", " ") : f.value))
      .join(" · "),
    about: aboutParagraphs(job.about).map(aboutBlock),
    must: show.must ? job.must : [],
    nice: show.nice ? job.nice : [],
    steps: show.process ? processSteps(recruiter.first_name, job.params?.contract ?? null) : [],
    recruiterFirstName: recruiter.first_name,
  };
}
