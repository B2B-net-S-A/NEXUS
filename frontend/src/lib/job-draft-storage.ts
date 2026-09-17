/**
 * Szkic „Dodaj rekrutację" w `localStorage` — jedno źródło prawdy dla klucza
 * i kształtu zapisu, jak `lib/onboarding-storage.ts`.
 *
 * Klucz jest per użytkownik (`nexus:jobDraft:v1:<userId>`), żeby dwie osoby
 * na tej samej przeglądarce (rzadkie, ale zdarza się na wspólnym laptopie
 * demo) nie nadpisywały sobie nawzajem niedokończonego formularza.
 *
 * Każdy dostęp do `localStorage` jest w `try/catch` — przeglądarka potrafi go
 * zablokować (tryb prywatny, polityka witryny), a wtedy szkic po prostu nie
 * przetrwa zamknięcia karty, zamiast wywalać formularz wyjątkiem.
 */

export interface JobDraftFormState {
  title: string;
  clientId: number | null;
  clientName: string | null;
  recruitmentType: string;
  description: string;
  mustHaveInput: string;
  location: string;
  remotePolicy: string;
  onsiteDaysPerWeek: string;
  rateBudgetHourly: string;
  salaryMin: string;
  salaryMax: string;
}

export interface RestorableJobDraft {
  form: JobDraftFormState;
  savedAt: string;
}

interface StoredJobDraft {
  version: number;
  savedAt: string;
  form: JobDraftFormState;
}

const DRAFT_VERSION = 1;

function draftKey(userId: number | string): string {
  return `nexus:jobDraft:v1:${userId}`;
}

/** Formularz bez żadnej treści wpisanej przez użytkownika — nic do zapisania. */
export function isJobFormEmpty(form: JobDraftFormState): boolean {
  return (
    form.title.trim() === "" &&
    form.clientId === null &&
    form.recruitmentType === "body_leasing" &&
    form.description.trim() === "" &&
    form.mustHaveInput.trim() === "" &&
    form.location.trim() === "" &&
    form.remotePolicy === "" &&
    form.onsiteDaysPerWeek.trim() === "" &&
    form.rateBudgetHourly.trim() === "" &&
    form.salaryMin.trim() === "" &&
    form.salaryMax.trim() === ""
  );
}

function isValidStoredDraft(value: unknown): value is StoredJobDraft {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<StoredJobDraft>;
  return (
    v.version === DRAFT_VERSION &&
    typeof v.savedAt === "string" &&
    !!v.savedAt &&
    !!v.form &&
    typeof v.form === "object"
  );
}

/**
 * Zapisany szkic, albo `null` — gdy nic nie ma, dane są uszkodzone (nie da
 * się sparsować JSON-a), zapisane inną wersją kontraktu, albo formularz był
 * pusty w chwili zapisu (nic wartego przywrócenia).
 */
export function readJobDraft(userId: number | string): RestorableJobDraft | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(draftKey(userId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isValidStoredDraft(parsed)) return null;
    if (isJobFormEmpty(parsed.form)) return null;
    return { form: parsed.form, savedAt: parsed.savedAt };
  } catch {
    return null;
  }
}

/** Zapisuje szkic; formularz pusty kasuje zamiast zapisywać puste dane. */
export function writeJobDraft(
  userId: number | string,
  form: JobDraftFormState,
): void {
  if (typeof window === "undefined") return;
  if (isJobFormEmpty(form)) {
    clearJobDraft(userId);
    return;
  }
  try {
    const payload: StoredJobDraft = {
      version: DRAFT_VERSION,
      savedAt: new Date().toISOString(),
      form,
    };
    window.localStorage.setItem(draftKey(userId), JSON.stringify(payload));
  } catch {
    /* storage wyłączony — trudno, szkic po prostu nie przetrwa */
  }
}

/** Kasuje zapisany szkic (po „Odrzuć" i po udanym zapisie rekrutacji). */
export function clearJobDraft(userId: number | string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(draftKey(userId));
  } catch {
    /* storage wyłączony */
  }
}
