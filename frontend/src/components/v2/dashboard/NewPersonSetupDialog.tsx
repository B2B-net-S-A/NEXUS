"use client";

// Okno „Ustaw nową osobę” (0610, decyzje Artura 28.10.2026). Head of
// Recruitment i admin decydują o koncie po pierwszym logowaniu i uzupełniają
// rekruterowi kategorie kompetencji i przełożonego — jednym zapisem
// (`POST /api/people-setup/{id}`). Rolę inną niż Rekruter nadaje admin
// w „Osoby i role”; Head of Recruitment widzi te warianty wyszarzone.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Info } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_TASKS_QUERY_KEY, type NewPersonSetupRow } from "@/lib/api/boardTasks";
import {
  applyPeopleSetup,
  usePeopleSetupOptions,
  type PeopleSetupPayload,
} from "@/lib/api/peopleSetup";
import { COMPETENCE_TEAM_QUERY_KEY, useCompetenceTeam } from "@/lib/api/requestAllocation";
import { useAuthStore } from "@/store/auth";

export const PEOPLE_SETTINGS_HREF = "/settings?item=people";

type Decision = "recruiter" | "delivery_lead" | "employee" | "other";

const DECISIONS: { id: Decision; label: string; hint: string; adminOnly?: boolean }[] = [
  {
    id: "recruiter",
    label: "Rekruter",
    hint: "Tablica, kandydaci, rekrutacje. Przy logowaniu wybierze swoje aktywne rekrutacje.",
  },
  {
    id: "delivery_lead",
    label: "Delivery Lead",
    hint: "Klienci, przegląd CV, zamówienia — nadajesz w „Osoby i role”.",
    adminOnly: true,
  },
  {
    id: "employee",
    label: "Zostaje Konsultantem/Kontraktorem",
    hint: "Konsultant albo back office: swój czas, umowa, sprzęt. Bez kandydatów.",
  },
  {
    id: "other",
    label: "Inna rola",
    hint: "Finanse, TCM, Automatyzacje… — nadajesz w „Osoby i role”.",
    adminOnly: true,
  },
];

export interface NewPersonSetupDialogProps {
  person: NewPersonSetupRow | null;
  /** Link z maila „Zostaw jako Konsultanta” — wariant zaznaczony, zapis w oknie. */
  presetKeep?: boolean;
  isAdmin: boolean;
  onClose: () => void;
}

export function NewPersonSetupDialog({ person, presetKeep = false, isAdmin, onClose }: NewPersonSetupDialogProps) {
  const open = person !== null;
  const me = useAuthStore((s) => s.user);
  const team = useCompetenceTeam({ enabled: open });
  const options = usePeopleSetupOptions(open);
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [decision, setDecision] = useState<Decision | null>(null);
  const [first, setFirst] = useState<number | null>(null);
  const [second, setSecond] = useState<number[]>([]);
  const [managerId, setManagerId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  // Reset tylko przy zmianie osoby — rodzic („Osoby i role”) składa obiekt
  // `person` na nowo przy każdym renderze (przegląd kodu 28.10.2026).
  const personId = person?.user_id ?? null;
  const needsDecision = person?.needs_decision ?? false;
  useEffect(() => {
    if (personId === null) return;
    setDecision(needsDecision ? (presetKeep ? "employee" : null) : "recruiter");
    setFirst(null);
    setSecond([]);
    setManagerId(me?.id ?? null);
  }, [personId, needsDecision, presetKeep, me?.id]);

  if (!person) return null;

  const recruiter = decision === "recruiter";
  const askCategories = recruiter && (person.needs_decision || person.missing.includes("categories"));
  const askManager =
    recruiter &&
    options.data?.manager_enabled === true &&
    (person.needs_decision || person.missing.includes("manager"));
  const viaPeopleSettings = decision === "delivery_lead" || decision === "other";
  const categories = team.data?.categories ?? [];
  const managers = options.data?.managers ?? [];
  const canSave = decision !== null && !viaPeopleSettings && (!askCategories || first !== null);

  const toggleSecond = (id: number) =>
    setSecond((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const save = async () => {
    if (!canSave || decision === null || viaPeopleSettings) return;
    const payload: PeopleSetupPayload =
      decision === "employee"
        ? { decision: "employee" }
        : {
            decision: "recruiter",
            first_category_id: askCategories ? first : null,
            second_category_ids: askCategories ? second.filter((id) => id !== first) : [],
            manager_user_id: askManager ? managerId : null,
          };
    setSaving(true);
    try {
      await applyPeopleSetup(person.user_id, payload);
      // Bez czekania: „Czeka na Ciebie” liczy się kilka sekund, a okno
      // wisiałoby z wyszarzonym „Zapisz” (staging 28.10.2026).
      void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: COMPETENCE_TEAM_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      showSuccess(
        decision === "employee"
          ? `${person.name} zostaje Konsultantem/Kontraktorem.`
          : `Zapisano: ${person.name} jest rekruterem.`,
      );
      onClose();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać ustawień osoby."));
    } finally {
      setSaving(false);
    }
  };

  let step = 0;
  return (
    <AppModal
      open={open}
      onOpenChange={(next) => (next ? null : onClose())}
      size="lg"
      title={`Ustaw: ${person.name}`}
      description={`${person.email} · ${person.needs_decision ? "pierwsze logowanie" : "konto od"} ${formatDay(person.since)}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Później
          </Button>
          {viaPeopleSettings ? (
            <Button asChild>
              <Link href={PEOPLE_SETTINGS_HREF}>Otwórz „Osoby i role”</Link>
            </Button>
          ) : (
            <Button onClick={() => void save()} disabled={!canSave || saving}>
              {decision === "employee" ? "Zostaw jako Konsultanta" : "Zapisz"}
            </Button>
          )}
        </>
      }
    >
      <ol className="flex flex-col gap-5">
        {person.needs_decision ? (
          <li>
            <StepTitle n={++step} done={decision !== null}>
              Kim jest ta osoba w NEXUSIE?
            </StepTitle>
            <div className="mt-2 grid gap-2 sm:grid-cols-2" role="group" aria-label="Rola">
              {DECISIONS.map((d) => {
                const locked = d.adminOnly === true && !isAdmin;
                return (
                  <button
                    key={d.id}
                    type="button"
                    disabled={locked}
                    onClick={() => setDecision(d.id)}
                    aria-pressed={decision === d.id}
                    className={`rounded-lg border px-3 py-2 text-left transition-colors disabled:opacity-50 ${
                      decision === d.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted/60"
                    }`}
                  >
                    <span className="block text-sm font-semibold">{d.label}</span>
                    <span className="block text-xs text-muted-foreground">
                      {locked ? "Nadaje admin w „Osoby i role”." : d.hint}
                    </span>
                  </button>
                );
              })}
            </div>
          </li>
        ) : null}

        {askCategories ? (
          <li>
            <StepTitle n={++step} done={first !== null}>
              Kategorie kompetencji
            </StepTitle>
            <p className="mb-2 mt-1 text-xs text-muted-foreground">
              Automat przydziela requesty najpierw 1. priorytetowi. Bez kategorii osoba nie dostaje requestów.
            </p>
            {team.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {apiErrorMessage(team.error, "Nie udało się wczytać kategorii.")}
              </p>
            ) : (
              <>
                <p className="mb-1 text-xs font-semibold text-muted-foreground">1. priorytet (jedna)</p>
                <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="1. priorytet">
                  {categories.map((c) => (
                    <Chip key={c.id} active={first === c.id} onClick={() => setFirst(c.id)}>
                      {c.name} <span className="tabular-nums opacity-70">· {c.first.length} os.</span>
                    </Chip>
                  ))}
                </div>
                <p className="mb-1 text-xs font-semibold text-muted-foreground">2. priorytet (dowolnie)</p>
                <div className="flex flex-wrap gap-1.5" role="group" aria-label="2. priorytet">
                  {categories
                    .filter((c) => c.id !== first)
                    .map((c) => (
                      <Chip key={c.id} active={second.includes(c.id)} onClick={() => toggleSecond(c.id)}>
                        {c.name}
                      </Chip>
                    ))}
                </div>
              </>
            )}
          </li>
        ) : null}

        {askManager ? (
          <li>
            <StepTitle n={++step} done={managerId !== null}>
              Przełożony
            </StepTitle>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <select
                id="new-person-manager"
                aria-label="Przełożony"
                value={managerId ?? ""}
                onChange={(e) => setManagerId(e.target.value ? Number(e.target.value) : null)}
                className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
              >
                {managers.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id === me?.id ? `${m.name} (Ty)` : m.name}
                  </option>
                ))}
              </select>
              <span className="text-xs text-muted-foreground">
                Osoba trafi do „Mój zespół” przełożonego (urlopy, czas pracy).
              </span>
            </div>
          </li>
        ) : null}

        {recruiter && person.needs_decision ? (
          <li className="flex items-start gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              Cele KPI: domyślne cele rekrutera. Liga, CloudTalk i Traffit łączą się same po adresie e-mail. Osoba
              zostanie wylogowana i przy następnym logowaniu wybierze swoje aktywne rekrutacje.
            </span>
          </li>
        ) : null}
      </ol>
    </AppModal>
  );
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", timeZone: "Europe/Warsaw" });
}

function StepTitle({ n, done, children }: { n: number; done: boolean; children: React.ReactNode }) {
  return (
    <h3 className="flex items-center gap-2 text-sm font-semibold">
      <span
        className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-xs ${
          done ? "bg-success text-success-foreground" : "bg-muted text-muted-foreground"
        }`}
      >
        {done ? <Check className="h-3 w-3" aria-hidden /> : n}
      </span>
      {children}
    </h3>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
        active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-foreground hover:bg-muted"
      }`}
    >
      {children}
    </button>
  );
}
