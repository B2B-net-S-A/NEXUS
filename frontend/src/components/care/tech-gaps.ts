// „Luki do dopytania” mapy technologii (D16) jako pytania — te same zdania
// stoją na zakładce „Technologie” klienta i w oknie zapisu rozmowy opieki.
// Czyste funkcje (bez Reacta).

import { serializeSkillBuckets } from "@/lib/skill-expression";
import type { TechGap, TechSource } from "@/lib/api/care";

export interface GapQuestion {
  key: string;
  /** Krótko, jak w makiecie: „CI/CD i chmura”, „Databricks”, „QA”. */
  subject: string;
  detail: string;
  question: string;
}

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

function monthYear(iso: string | null): string | null {
  const match = iso ? ISO.exec(iso) : null;
  return match ? `${match[2]}.${match[1]}` : null;
}

const SOURCE_ONLY: Record<TechSource, [string, string]> = {
  jobs: ["z rekrutacji", "z rekrutacji"],
  cards: ["z rozmowy z konsultantem", "z rozmów z konsultantami"],
  notes: ["z notatki o stacku", "z notatek o stacku"],
  consultants: ["z CV konsultanta", "z CV konsultantów"],
};

/** Imię i inicjał nazwiska („Michał R.”) — tak mówi się o osobie w pytaniu. */
function shortName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) return name.trim();
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

export function gapQuestion(gap: TechGap): GapQuestion {
  if (gap.kind === "area_no_source") {
    return {
      key: `area-${gap.area.id}`,
      subject: gap.area.name,
      detail: "brak źródła od 18 miesięcy",
      question: `Jakich technologii używa teraz dział ${gap.area.name}?`,
    };
  }
  if (gap.kind === "manager_unplaced") {
    const who = shortName(gap.contact.name);
    return {
      key: `manager-${gap.contact.id}`,
      subject: gap.area?.name ?? gap.contact.name,
      detail: `nie wiemy, komu podlega ${who}`,
      question: `Komu podlega ${gap.contact.name}${gap.area ? ` (${gap.area.name})` : ""}?`,
    };
  }
  const [one, many] = SOURCE_ONLY[gap.source];
  const when = monthYear(gap.last_seen);
  const detail =
    gap.refs > 1
      ? `znane tylko ${many} (${gap.refs})`
      : `znane tylko ${one}${when ? ` z ${when}` : ""}`;
  const where = gap.areas.length ? ` w dziale ${gap.areas.join(", ")}` : "";
  return {
    key: `skill-${gap.skill_id}`,
    subject: gap.name,
    detail,
    question: `Czy ${gap.name} jest naprawdę używany${where}?`,
  };
}

/** Adres listy kandydatów z filtrem „musi mieć” wszystkie umiejętności działu. */
export function candidatesHref(skills: string[]): string | null {
  const names = skills.map((name) => name.trim()).filter(Boolean);
  if (!names.length) return null;
  const params = new URLSearchParams({
    skills_q: serializeSkillBuckets({ must: names, anyGroups: [], none: [] }),
  });
  return `/candidates?${params.toString()}`;
}
