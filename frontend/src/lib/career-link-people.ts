/**
 * Stan osoby ze zgłoszenia z linku — jedno zdanie dla Wyników i zakładki
 * „Z linków” w „Moich ludziach”. Makieta A i B:
 * https://claude.ai/artifact/BcevDUToiG7AGHfgY86T5P
 */

import type { LinkPerson } from "@/lib/api/careerLinks";
import { stageLabel } from "@/lib/cv-generator";
import { formatDate } from "@/components/v2/career-share/share-utils";

const SCREENING_OUTCOME_LABELS: Record<string, string> = {
  screened_out: "Odrzucony przez AI",
  failed: "Odrzucony przez AI",
  blocked: "Zablokowany: czarna lista albo weto klienta",
  job_closed: "Rekrutacja zamknięta przed przeglądem",
  already_in_job: "Był już w tej rekrutacji",
};

export function linkPersonLinkName(person: LinkPerson): string {
  if (person.kind === "recruiter") return "Mój link ogólny";
  return person.job_title || "Rekrutacja";
}

export function linkPersonNow(person: LinkPerson): string {
  if (person.current_stage) {
    const stage = stageLabel(person.current_stage);
    // Link do rekrutacji: rekrutacja stoi już w nazwie linku obok.
    return person.kind === "recruiter" && person.current_job_title
      ? `${stage}: ${person.current_job_title}`
      : stage;
  }
  if (person.screening_status === "pending") return "Czeka na przegląd AI";
  const outcome = person.screening_outcome
    ? SCREENING_OUTCOME_LABELS[person.screening_outcome]
    : undefined;
  if (outcome) return outcome;
  return person.kind === "recruiter"
    ? "W bazie, bez nowej rekrutacji"
    : "Bez karty w tej rekrutacji";
}

export function linkPersonAppliedAt(person: LinkPerson): string {
  return formatDate(person.applied_at);
}

export function linkPersonKey(person: LinkPerson): string {
  return `${person.candidate_id}-${person.kind}-${person.slug ?? person.job_id ?? ""}`;
}
