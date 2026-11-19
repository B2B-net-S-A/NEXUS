/**
 * Proces u klienta (18.11.2026): etapy po wysłaniu CV, termin decyzji
 * i czas zmierzony na ruchach kart u klienta. Lustro
 * `backend/app/schemas/champion.py` (`ClientProcessIn`,
 * `ChampionClientProcess`) i `services/job_client_process.py`.
 * Reguła: `docs/claude/rekrutacja-tworzenie/proces-u-klienta.md`.
 */

export type ProcessStepKind =
  | "tech_interview"
  | "manager_interview"
  | "client_interview"
  | "home_task"
  | "online_test"
  | "onsite_meeting";

export type ProcessStepFormat = "remote" | "onsite";

export interface ProcessStep {
  kind: ProcessStepKind;
  format: ProcessStepFormat;
  /** „60 min”, „ok. 3 h, 2 dni na oddanie” — wolny tekst, do 80 znaków. */
  duration: string;
}

export interface ClientProcessInput {
  steps: ProcessStep[];
  decision_workdays: number | null;
}

export interface ClientProcess extends ClientProcessInput {
  set_by_id?: number | null;
  set_by_name?: string | null;
  set_at?: string | null;
}

export interface MeasuredProcess {
  cv_to_interview_days: number | null;
  interview_to_decision_days: number | null;
  cv_to_decision_days: number;
  decisions: number;
  months: number;
}

export interface ClientProcessHints {
  client_id: number;
  suggested: (ClientProcess & { from_job_id: number }) | null;
  measured: MeasuredProcess | null;
}

export const MAX_STEPS = 6;
export const DURATION_MAX_CHARS = 80;

export const STEP_LABEL: Record<ProcessStepKind, string> = {
  tech_interview: "Rozmowa techniczna",
  manager_interview: "Rozmowa z managerem",
  client_interview: "Rozmowa z klientem",
  home_task: "Zadanie do wykonania",
  online_test: "Test online",
  onsite_meeting: "Spotkanie w biurze",
};

export const FORMAT_LABEL: Record<ProcessStepFormat, string> = {
  remote: "zdalnie",
  onsite: "na miejscu",
};

export interface ProcessPreset {
  key: string;
  label: string;
  steps: readonly ProcessStep[];
}

/** Układy z nagłówka zgłoszenia: „jedna rozmowa zdalna”, „interview + test”. */
export const PROCESS_PRESETS: readonly ProcessPreset[] = [
  {
    key: "one",
    label: "1 rozmowa",
    steps: [{ kind: "tech_interview", format: "remote", duration: "60 min" }],
  },
  {
    key: "interview_task",
    label: "Rozmowa + zadanie",
    steps: [
      { kind: "tech_interview", format: "remote", duration: "60 min" },
      { kind: "home_task", format: "remote", duration: "" },
    ],
  },
  {
    key: "two",
    label: "2 rozmowy",
    steps: [
      { kind: "tech_interview", format: "remote", duration: "60 min" },
      { kind: "manager_interview", format: "remote", duration: "30 min" },
    ],
  },
  {
    key: "test_interview",
    label: "Test online + rozmowa",
    steps: [
      { kind: "online_test", format: "remote", duration: "" },
      { kind: "tech_interview", format: "remote", duration: "60 min" },
    ],
  },
];

export const EMPTY_PROCESS: ClientProcessInput = { steps: [], decision_workdays: null };

const sameStep = (a: ProcessStep, b: ProcessStep) =>
  a.kind === b.kind && a.format === b.format && a.duration.trim() === b.duration.trim();

/** Który gotowy układ odpowiada etapom (po rodzaju i formie, bez czasu). */
export function matchingPreset(steps: readonly ProcessStep[]): string | null {
  const preset = PROCESS_PRESETS.find(
    (p) =>
      p.steps.length === steps.length &&
      p.steps.every((s, i) => s.kind === steps[i].kind && s.format === steps[i].format),
  );
  return preset?.key ?? null;
}

export function sameProcess(a: ClientProcessInput | null, b: ClientProcessInput | null): boolean {
  const as = a?.steps ?? [];
  const bs = b?.steps ?? [];
  return (
    as.length === bs.length &&
    as.every((s, i) => sameStep(s, bs[i])) &&
    (a?.decision_workdays ?? null) === (b?.decision_workdays ?? null)
  );
}

/** Zapisany proces albo `null` — pusty wpis to brak procesu. */
export function storedProcess(value: unknown): ClientProcess | null {
  if (!value || typeof value !== "object") return null;
  const steps = (value as ClientProcess).steps;
  return Array.isArray(steps) && steps.length > 0 ? (value as ClientProcess) : null;
}

/** Ładunek do zapisu: przycięte czasy, termin tylko w zakresie 1–60. */
export function toInput(draft: ClientProcessInput): ClientProcessInput {
  const days = draft.decision_workdays;
  return {
    steps: draft.steps
      .slice(0, MAX_STEPS)
      .map((s) => ({ ...s, duration: s.duration.trim().slice(0, DURATION_MAX_CHARS) })),
    decision_workdays: days != null && days >= 1 && days <= 60 ? Math.round(days) : null,
  };
}

/** Pole „dni roboczych”: puste albo liczba 1–60; inne wpisy odrzuca. */
export function parseWorkdays(text: string): number | null | "invalid" {
  const trimmed = text.trim();
  if (!trimmed) return null;
  if (!/^\d{1,2}$/.test(trimmed)) return "invalid";
  const value = Number(trimmed);
  return value >= 1 && value <= 60 ? value : "invalid";
}

/** „< 1 dnia”, „1 dzień”, „12 dni” — mediana bywa zerem, gdy karty przesuwano razem. */
export function daysLabel(days: number): string {
  if (days < 1) return "< 1 dnia";
  return days === 1 ? "1 dzień" : `${days} dni`;
}

function etapy(count: number): string {
  if (count === 1) return "1 etap";
  if (count >= 2 && count <= 4) return `${count} etapy`;
  return `${count} etapów`;
}

function weeks(days: number): number {
  return Math.max(1, Math.round(days / 7));
}

/** „2 etapy · ~4 tyg.” do nagłówka; tygodnie tylko z czasu zmierzonego. */
export function processFactLabel(
  process: ClientProcessInput | null,
  measured: MeasuredProcess | null,
): string | null {
  const count = process?.steps.length ?? 0;
  if (!count) return null;
  return measured ? `${etapy(count)} · ~${weeks(measured.cv_to_decision_days)} tyg.` : etapy(count);
}

/** Zdanie, które rekruter mówi kandydatowi (bez nazwy klienta i liczb z historii poza tygodniami). */
export function candidateSentence(
  process: ClientProcessInput | null,
  measured: MeasuredProcess | null,
): string | null {
  if (!process?.steps.length) return null;
  const parts = process.steps.map((step) => {
    const name = STEP_LABEL[step.kind].toLowerCase();
    const duration = step.duration.trim();
    return `${name} ${FORMAT_LABEL[step.format]}${duration ? ` (${duration})` : ""}`;
  });
  const count = parts.length === 1 ? "jeden etap" : etapy(parts.length);
  let when = "";
  if (measured) {
    const w = weeks(measured.cv_to_decision_days);
    when = ` Decyzji spodziewaj się po ok. ${w} ${w === 1 ? "tygodniu" : "tygodniach"} od wysłania CV.`;
  } else if (process.decision_workdays) {
    when = ` Klient obiecuje decyzję w ciągu ${process.decision_workdays} dni roboczych od ostatniego etapu.`;
  }
  return `Proces u klienta ma ${count}: ${parts.join(", potem ")}.${when}`;
}

/**
 * Deklaracja a rzeczywistość: zmierzona decyzja po rozmowie dłuższa niż
 * deklarowane dni robocze przeliczone na kalendarzowe (×7/5) z zapasem 20%.
 */
export function decisionSlowerThanDeclared(
  process: ClientProcessInput | null,
  measured: MeasuredProcess | null,
): boolean {
  const declared = process?.decision_workdays;
  const real = measured?.interview_to_decision_days;
  if (!declared || real == null) return false;
  return real > ((declared * 7) / 5) * 1.2;
}
