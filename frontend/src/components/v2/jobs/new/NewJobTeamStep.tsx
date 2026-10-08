"use client";

/**
 * `/jobs/new` → „Kategoria i zespół” (decyzje Artura 02.10.2026).
 *
 * Delivery Lead potwierdza kategorię kompetencji — od niej zależy, kto dostanie
 * rekrutację: uczestnikami zostają WSZYSCY z kategorii, w tle, bez wybierania
 * osób. Do tego jeden rekruter prowadzący: przydziela go automat albo wskazuje
 * Delivery Lead. Head of Recruitment widzi wynik na swoim pulpicie
 * („Nowe rekrutacje — kto prowadzi”) i może go zmienić.
 *
 * Nic się tu nie zapisuje: kategoria i priorytet idą w `POST /api/jobs`,
 * prowadzący w `POST …/handoff`.
 */

import { useId, type ReactNode } from "react";
import { Check, Users } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { RecruiterAssignmentChoice } from "@/components/v2/jobs/RecruiterAssignmentChoice";
import {
  AUTOMATIC_DISABLED_TEXT,
  type AllocationMode,
  type RecruiterAssignment,
} from "@/lib/recruiter-assignment";
import {
  PRIORITY_LEVEL_OPTIONS,
  type PriorityLevel,
} from "@/lib/request-priority";
import { sectionAnchor } from "@/lib/job-request-intake";
import { cn } from "@/lib/utils";

export interface RecruiterOption {
  id: number;
  name?: string | null;
  email?: string | null;
}

/** Pozycja `POST /api/job-intake/category-suggestion` → `categories`. */
export interface CategoryOption {
  id: number;
  slug: string;
  name: string;
  /** Ile osób zostanie uczestnikami — bez nazwisk. */
  participants: number;
}

/** „1 osoba”, „3 osoby”, „7 osób”. */
export function participantsLabel(n: number): string {
  const last = n % 10;
  const lastTwo = n % 100;
  if (n === 1) return "1 osoba";
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return `${n} osoby`;
  return `${n} osób`;
}

interface Props {
  categories: CategoryOption[];
  /** Lista kategorii jeszcze się wczytuje. */
  categoriesLoading: boolean;
  categoriesFailed: boolean;
  onCategoriesRetry: () => void;
  categoryId: number | null;
  /** Podpowiedź systemu z nazwy roli — `null`, gdy system nie ma zdania. */
  suggestedCategoryId: number | null;
  categoryConfirmed: boolean;
  /** Wybór kategorii; `confirmed` = kliknięcie człowieka (wybór albo „Potwierdzam”). */
  onCategoryChange: (id: number, confirmed: boolean) => void;
  /** Brak potwierdzenia blokuje „Przekaż do searchu” — sekcja to pokazuje. */
  categoryMissing: boolean;
  /** Wybór obowiązujący (`resolveRecruiterAssignment`). */
  assignment: RecruiterAssignment;
  onAssignmentChange: (value: RecruiterAssignment) => void;
  automaticAvailable: boolean;
  /** Odczyt się udał i automat jest wyłączony — pod polem stoi powód. */
  automaticOff: boolean;
  mode: AllocationMode | undefined;
  recruiters: RecruiterOption[];
  /** Lista rekruterów się nie wczytała (i nie ma jej w pamięci podręcznej). */
  recruitersFailed: boolean;
  onRecruitersRetry: () => void;
  recruiterId: number | null;
  onRecruiterChange: (id: number | null) => void;
  priorityLevel: PriorityLevel;
  onPriorityChange: (level: PriorityLevel) => void;
  /** Pole „Delivery Lead” (`NewJobDeliveryLeadField`) — samo pyta serwer. */
  deliveryLead?: ReactNode;
  disabled?: boolean;
}

export function NewJobTeamStep({
  categories,
  categoriesLoading,
  categoriesFailed,
  onCategoriesRetry,
  categoryId,
  suggestedCategoryId,
  categoryConfirmed,
  onCategoryChange,
  categoryMissing,
  assignment,
  onAssignmentChange,
  automaticAvailable,
  automaticOff,
  mode,
  recruiters,
  recruitersFailed,
  onRecruitersRetry,
  recruiterId,
  onRecruiterChange,
  priorityLevel,
  onPriorityChange,
  deliveryLead,
  disabled = false,
}: Props) {
  const id = useId();
  const automatic = assignment === "automatic";
  const chosen = categories.find((category) => category.id === categoryId) ?? null;

  return (
    <section
      id={sectionAnchor("team")}
      aria-labelledby={`${id}-title`}
      className={cn(
        "flex scroll-mt-28 flex-col gap-5 rounded-xl border border-border bg-card p-4 sm:p-6",
        categoryMissing && "border-warning",
      )}
    >
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Users className="h-4 w-4" aria-hidden />
        </span>
        <div>
          <h2 id={`${id}-title`} className="text-base font-semibold text-foreground">
            6 · Kategoria i zespół
          </h2>
          <p className="text-xs text-muted-foreground">
            Kto dostanie rekrutację po przekazaniu do searchu i jak jest pilna.
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span id={`${id}-category`} className="text-sm font-medium text-foreground">
          Kategoria kompetencji
        </span>
        {categoriesFailed ? (
          <p role="alert" className="text-sm text-destructive">
            Nie udało się wczytać kategorii.{" "}
            <button type="button" className="font-medium underline" onClick={onCategoriesRetry}>
              Ponów
            </button>
          </p>
        ) : categoriesLoading && categories.length === 0 ? (
          <p className="text-sm text-muted-foreground">Wczytuję kategorie…</p>
        ) : (
          <>
            <div
              role="radiogroup"
              aria-labelledby={`${id}-category`}
              className="flex flex-wrap gap-2"
            >
              {categories.map((category) => {
                const checked = category.id === categoryId;
                const suggested = category.id === suggestedCategoryId;
                return (
                  <button
                    key={category.id}
                    type="button"
                    role="radio"
                    aria-checked={checked}
                    disabled={disabled}
                    // Kliknięcie kategorii to decyzja człowieka — potwierdza ją.
                    onClick={() => onCategoryChange(category.id, true)}
                    className={cn(
                      "inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-60",
                      checked
                        ? "border-primary bg-primary/10 font-semibold text-foreground"
                        : "border-border bg-card text-foreground hover:bg-accent",
                    )}
                  >
                    {checked && categoryConfirmed ? (
                      <Check className="h-3.5 w-3.5 text-primary" aria-hidden />
                    ) : null}
                    {category.name}
                    {suggested ? (
                      <span className="rounded-full border border-dashed border-primary/50 px-1.5 text-[11px] font-medium text-primary">
                        propozycja
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
            {chosen == null ? (
              <p
                className={cn(
                  "text-xs leading-snug",
                  categoryMissing
                    ? "font-medium text-warning-muted-foreground"
                    : "text-muted-foreground",
                )}
              >
                {suggestedCategoryId == null
                  ? "System nie rozpoznał kategorii z nazwy roli — wybierz ją. Rekrutacja trafi do wszystkich osób z tej kategorii."
                  : "Wybierz kategorię. Rekrutacja trafi do wszystkich osób z tej kategorii."}
              </p>
            ) : categoryConfirmed ? (
              <p className="text-xs leading-snug text-success-muted-foreground">
                Kategoria potwierdzona: {chosen.name}. Uczestnikami zostaną wszyscy z tej
                kategorii ({participantsLabel(chosen.participants)}) — dzieje się to samo,
                nic nie wybierasz.
              </p>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  size="sm"
                  disabled={disabled}
                  onClick={() => onCategoryChange(chosen.id, true)}
                >
                  Potwierdzam: {chosen.name}
                </Button>
                <p
                  className={cn(
                    "min-w-0 flex-1 text-xs leading-snug",
                    categoryMissing
                      ? "font-medium text-warning-muted-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  Propozycja systemu z nazwy roli. Rekrutacja trafi do wszystkich osób z tej
                  kategorii ({participantsLabel(chosen.participants)}). Potwierdź albo wybierz
                  inną.
                </p>
              </div>
            )}
            {chosen != null && chosen.participants === 0 ? (
              <p className="text-xs font-medium text-warning-muted-foreground">
                W tej kategorii nie ma nikogo — rekrutacja nie będzie miała uczestników,
                a automat nie znajdzie prowadzącego. Kategorie osób ustawia się
                w Ustawieniach → Zespół i dostęp.
              </p>
            ) : null}
          </>
        )}
      </div>

      {deliveryLead}

      <div className="flex flex-col gap-2">
        <span id={`${id}-recruiter`} className="text-sm font-medium text-foreground">
          Rekruter prowadzący
        </span>
        <RecruiterAssignmentChoice
          labelledBy={`${id}-recruiter`}
          value={assignment}
          onChange={onAssignmentChange}
          automaticAvailable={automaticAvailable}
          unavailableReason={automaticOff ? AUTOMATIC_DISABLED_TEXT : null}
          mode={mode}
          passive={priorityLevel === "accepting"}
          manualLabel="Wskażę sam"
          disabled={disabled}
        />
        {!automatic && (
          <div className="flex min-w-0 flex-col gap-1 sm:max-w-sm">
            <select
              aria-label="Wybierz rekrutera prowadzącego"
              className="h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm text-foreground"
              value={recruiterId ?? ""}
              disabled={disabled}
              onChange={(e) =>
                onRecruiterChange(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">Wybierz rekrutera…</option>
              {recruiters.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name || r.email || `#${r.id}`}
                </option>
              ))}
            </select>
            {/* Runda 8 (R8-N14-6): pusta lista przy awarii blokowała
                przekazanie bez słowa wyjaśnienia. */}
            {recruitersFailed ? (
              <span role="alert" className="text-xs text-destructive">
                Nie udało się wczytać listy rekruterów.{" "}
                <button
                  type="button"
                  className="font-medium underline"
                  onClick={onRecruitersRetry}
                >
                  Ponów
                </button>
              </span>
            ) : null}
            <p className="text-xs leading-snug text-muted-foreground">
              Wskazana osoba prowadzi rekrutację od razu, bez akceptacji.
            </p>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span id={`${id}-priority`} className="text-sm font-medium text-foreground">
          Priorytet
        </span>
        <SegmentedRadio<PriorityLevel>
          labelledBy={`${id}-priority`}
          // Kolumna flex rozciąga dzieci — przełącznik ma mieć szerokość opcji.
          className="self-start"
          value={priorityLevel}
          onChange={onPriorityChange}
          options={PRIORITY_LEVEL_OPTIONS}
          disabled={disabled}
        />
        <p className="text-xs leading-snug text-muted-foreground">
          Nowa rekrutacja zaczyna od P1 — idzie pierwsza w kolejce automatu.
          „Przyjmujemy kandydatów” znaczy, że nie szukamy aktywnie.
        </p>
      </div>
    </section>
  );
}
