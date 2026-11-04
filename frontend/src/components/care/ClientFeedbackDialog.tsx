"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useClientTechMap } from "@/lib/api/care";
import {
  DEMAND_OUTCOME_LABELS,
  DEMAND_OUTCOME_TOASTS,
  jobsNewHref,
  useSaveClientFeedbackWithDemand,
  type DemandContext,
  type DemandOutcome,
  type DemandPayload,
} from "@/lib/api/care-clients";
import {
  EXTENSION_LABELS,
  FEEDBACK_CHANNEL_LABELS,
  FEEDBACK_NOTE_MAX,
  SCORE_LABELS,
  canReadClientPeople,
  scoresForPayload,
  useClientOrg,
  type ExtensionOutlook,
  type FeedbackChannel,
  type OrgConsultant,
  type ScoreField,
} from "@/lib/api/client-people";
import { useAuthStore } from "@/store/auth";

import { orgPeople } from "./client-people-format";
import { skillsMentionedIn } from "./demand-skills";

export type { DemandContext } from "@/lib/api/care-clients";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

const FIELDS: ScoreField[] = ["quality", "communication", "autonomy"];
const EXTENSIONS: ExtensionOutlook[] = ["yes", "likely", "unsure", "no"];
const OUTCOMES: DemandOutcome[] = ["confirmed", "not_now", "stale"];
const NO_MANAGER = "none";
/** Ile technologii działu podsuwa sekcja popytu do zaznaczenia. */
const DEMAND_SKILLS_MAX = 12;
/** Co dzieje się po zapisie danego wyniku (makieta R4) — podpis pod opcją. */
const OUTCOME_HINTS: Record<DemandOutcome, string> = {
  confirmed: "→ nowa rekrutacja",
  not_now: "wróci za 30 dni",
  stale: "sygnał zamknięty",
};

/**
 * Okno „Rozmowa z menedżerem” / „Zapisz opinię”. Z karty „Popyt do
 * sprawdzenia” (tablica opieki DL) otwiera się z `demand` — wtedy dochodzi
 * sekcja „Czego potrzebuje dział?”, oceny są opcjonalne, a menedżera (gdy
 * karta go nie zna) wybiera się z osób klienta.
 */
export interface ClientFeedbackDialogProps {
  clientId: number;
  clientName: string;
  /** Menedżer u klienta; przy popycie bez menedżera — `null` (wybór w oknie). */
  manager?: { id: number; name: string } | null;
  consultants?: OrgConsultant[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Karta popytu z tablicy — sekcja „Czego potrzebuje dział?”. */
  demand?: DemandContext | null;
}

function ScorePicker({
  label,
  groupLabel,
  value,
  disabled,
  onChange,
}: {
  label: string;
  /** Nazwa grupy dla czytnika ekranu — z osobą, bo grup jest kilka. */
  groupLabel: string;
  value: number | null;
  disabled: boolean;
  onChange: (value: number | null) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <div role="group" aria-label={groupLabel} className="inline-flex gap-1">
        {[1, 2, 3, 4, 5].map((score) => (
          <button
            key={score}
            type="button"
            disabled={disabled}
            aria-pressed={value === score}
            aria-label={`${groupLabel}: ${score}`}
            onClick={() => onChange(value === score ? null : score)}
            className={cn(
              "inline-flex size-7 items-center justify-center rounded-md border text-xs tabular-nums transition-colors disabled:opacity-50",
              value === score
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-foreground hover:bg-muted",
            )}
          >
            {score}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * „Zapisz opinię” — rozmowa z menedżerem u klienta o jego konsultantach (D9–D11).
 *
 * Zapisuje ją opiekun albo Delivery Lead po rozmowie; formularza wysyłanego do
 * klienta nie ma (D10). Konsultant bez ani jednej oceny („pomiń”) nie dostaje
 * wiersza opinii.
 */
export function ClientFeedbackDialog(props: ClientFeedbackDialogProps) {
  return props.demand ? <DemandFeedbackDialog {...props} /> : <FeedbackDialogBody {...props} />;
}

/** Popyt potwierdzony kończy się przejściem na `/jobs/new` — router tylko tutaj. */
function DemandFeedbackDialog(props: ClientFeedbackDialogProps) {
  const router = useRouter();
  return <FeedbackDialogBody {...props} navigate={(href) => router.push(href)} />;
}

function FeedbackDialogBody({
  clientId,
  clientName,
  manager: givenManager = null,
  consultants: givenConsultants,
  open,
  onOpenChange,
  demand = null,
  navigate,
}: ClientFeedbackDialogProps & { navigate?: (href: string) => void }) {
  const { showToast } = useToast();
  const save = useSaveClientFeedbackWithDemand(clientId);
  const today = warsawToday();
  const ids = {
    date: useId(),
    channel: useId(),
    note: useId(),
    extension: useId(),
    outcome: useId(),
    role: useId(),
    headcount: useId(),
    start: useId(),
    manager: useId(),
    outcomeHint: useId(),
  };
  // Popyt bez menedżera na karcie: osoby klienta z drzewa (krąg D11) do wyboru.
  const canReadPeople = useAuthStore((s) => canReadClientPeople(s.user));
  const needsManager = demand !== null && givenManager === null;
  const orgQuery = useClientOrg(clientId, open && needsManager && canReadPeople);
  const people = useMemo(
    () => (orgQuery.data ? orgPeople(orgQuery.data) : []),
    [orgQuery.data],
  );
  const [pickedManagerId, setPickedManagerId] = useState<number | null>(null);
  const pickedPerson = people.find((person) => person.id === pickedManagerId) ?? null;
  const manager =
    givenManager ?? (pickedPerson ? { id: pickedPerson.id, name: pickedPerson.name } : null);
  const consultants = givenConsultants ?? pickedPerson?.consultants ?? [];
  // Technologie działu z mapy klienta — do zaznaczenia przy potwierdzonej potrzebie.
  const mapQuery = useClientTechMap(clientId, open && demand !== null);
  const demandSkills = useMemo(() => {
    const map = mapQuery.data;
    if (!map || !demand) return [];
    const department = demand.area
      ? map.departments.find((d) => d.area.id === demand.area?.id)
      : null;
    const source = department ? department.technologies : map.technologies;
    const all = source.map((tech) => ({ id: tech.skill_id, name: tech.name, count: tech.source_count }));
    // Technologie z ról sygnału stoją pierwsze — nie mogą wypaść za limit.
    const mentioned = new Set(skillsMentionedIn(demand.roles, all));
    return [...all]
      .sort(
        (a, b) =>
          Number(mentioned.has(b.id)) - Number(mentioned.has(a.id)) ||
          b.count - a.count ||
          a.name.localeCompare(b.name, "pl"),
      )
      .slice(0, DEMAND_SKILLS_MAX)
      .map(({ id, name }) => ({ id, name, mentioned: mentioned.has(id) }));
  }, [mapQuery.data, demand]);
  const [outcome, setOutcome] = useState<DemandOutcome | null>(null);
  const [role, setRole] = useState(demand?.roles[0] ?? "");
  const [headcount, setHeadcount] = useState("1");
  const [startMonth, setStartMonth] = useState("");
  const [skillIds, setSkillIds] = useState<Set<number>>(new Set());
  // Raz, gdy mapa działu przyjdzie: zaznacz technologie, które padły w rolach
  // sygnału (R4: „Technologie (z mapy działu — zaznacz)” z ✓ przy Java i Kafka).
  const [prechecked, setPrechecked] = useState(false);
  useEffect(() => {
    if (prechecked || demandSkills.length === 0) return;
    setPrechecked(true);
    setSkillIds(new Set(demandSkills.filter((skill) => skill.mentioned).map((skill) => skill.id)));
  }, [demandSkills, prechecked]);
  const [heldOn, setHeldOn] = useState(today);
  const [channel, setChannel] = useState<FeedbackChannel>("phone");
  const [scores, setScores] = useState<
    Record<number, Partial<Record<ScoreField, number | null>>>
  >({});
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [extension, setExtension] = useState<ExtensionOutlook | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const nearestEnd = consultants
    .map((c) => c.end_date)
    .filter((value): value is string => Boolean(value))
    .sort()[0];

  const setScore = (contractId: number, field: ScoreField, value: number | null) =>
    setScores((current) => ({
      ...current,
      [contractId]: { ...current[contractId], [field]: value },
    }));
  const toggleSkip = (contractId: number) =>
    setSkipped((current) => {
      const next = new Set(current);
      if (next.has(contractId)) next.delete(contractId);
      else next.add(contractId);
      return next;
    });

  const toggleSkill = (skillId: number) =>
    setSkillIds((current) => {
      const next = new Set(current);
      if (next.has(skillId)) next.delete(skillId);
      else next.add(skillId);
      return next;
    });

  const demandPayload = (): DemandPayload | null | string => {
    if (!demand) return null;
    if (!outcome) return "Zaznacz, co z potrzebą działu.";
    if (outcome !== "confirmed") return { key: demand.key, outcome };
    const count = Number(headcount);
    if (!role.trim()) return "Wpisz rolę, której szuka dział.";
    if (!Number.isInteger(count) || count < 1 || count > 50) {
      return "Liczba osób to od 1 do 50.";
    }
    return {
      key: demand.key,
      outcome,
      role: role.trim(),
      headcount: count,
      start_month: startMonth || null,
      skill_ids: [...skillIds],
    };
  };

  const submit = () => {
    setError(null);
    // Przy popycie menedżer jest opcjonalny (serwer przyjmuje sam `demand`).
    if (!manager && !demand) {
      setError("Wybierz menedżera, z którym była rozmowa.");
      return;
    }
    if (!heldOn || heldOn > today) {
      setError("Podaj datę rozmowy (najpóźniej dzisiejszą).");
      return;
    }
    const demandBody = demandPayload();
    if (typeof demandBody === "string") {
      setError(demandBody);
      return;
    }
    save.mutate(
      {
        ...(manager
          ? {
              contact_id: manager.id,
              extension_outlook: extension,
              note: note.trim() || null,
              scores: scoresForPayload(scores, skipped),
            }
          : {}),
        held_on: heldOn,
        channel,
        ...(demandBody ? { demand: demandBody } : {}),
      },
      {
        onSuccess: (saved) => {
          onOpenChange(false);
          if (!demandBody) {
            showToast("Opinia zapisana", "success");
            return;
          }
          showToast(DEMAND_OUTCOME_TOASTS[demandBody.outcome], "success");
          if (demandBody.outcome === "confirmed") {
            // Serwer składa adres z klientem, menedżerem i technologiami; starszy
            // serwer bez `jobs_new_url` — ten sam adres z okna.
            navigate?.(
              saved.jobs_new_url ||
                jobsNewHref({
                  clientId,
                  hmId: manager?.id ?? null,
                  skillIds: demandBody.skill_ids,
                  title: demandBody.role,
                  department: demand?.area?.name ?? null,
                  headcount: demandBody.headcount ?? null,
                  startMonth: demandBody.start_month ?? null,
                }),
            );
          }
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać opinii.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={
        demand
          ? [manager?.name ?? "Rozmowa z menedżerem", clientName, demand.area?.name]
              .filter(Boolean)
              .join(" · ")
          : `Opinia od: ${manager?.name ?? ""} · ${clientName}`
      }
      description={
        demand
          ? "Rozmowa z menedżerem: czego potrzebuje dział i jak pracują nasi konsultanci. Oceny są tym razem opcjonalne."
          : "Rozmowa z menedżerem u klienta o pracy naszych konsultantów."
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending
              ? "Zapisywanie…"
              : demand && outcome === "confirmed"
                ? "Zapisz i utwórz rekrutację"
                : demand
                  ? "Zapisz rozmowę"
                  : "Zapisz opinię"}
          </Button>
        </>
      }
    >
      {demand ? (
        <section
          aria-labelledby={ids.outcome}
          className="mb-3 space-y-3 rounded-md border border-border bg-muted/40 p-3"
          data-demand-section
        >
          <div className="space-y-1">
            <h3 id={ids.outcome} className="text-sm font-semibold">
              Czego potrzebuje dział{demand.area ? ` ${demand.area.name}` : ""}?
            </h3>
            {demand.roles.length ? (
              <p className="text-xs text-muted-foreground">
                Opiekun usłyszał: {demand.roles.join(", ")}
                {demand.source ? ` (${demand.source})` : ""}.
              </p>
            ) : null}
            <SegmentedRadio
              labelledBy={ids.outcome}
              size="sm"
              value={outcome}
              onChange={setOutcome}
              options={OUTCOMES.map((value) => ({
                value,
                // Podpis jest ozdobą (aria-hidden), czytnik dostaje go jako opis opcji.
                label: (
                  <span className="flex flex-col items-start leading-tight">
                    <span>{DEMAND_OUTCOME_LABELS[value]}</span>
                    <span aria-hidden className="text-[11px] font-normal opacity-75">
                      {OUTCOME_HINTS[value]}
                    </span>
                  </span>
                ),
                describedBy: `${ids.outcomeHint}-${value}`,
              }))}
            />
            {OUTCOMES.map((value) => (
              <span key={value} id={`${ids.outcomeHint}-${value}`} className="sr-only">
                {OUTCOME_HINTS[value]}
              </span>
            ))}
            {outcome === "not_now" ? (
              <p className="text-xs text-muted-foreground">Karta wróci na tablicę za 30 dni.</p>
            ) : null}
          </div>
          {outcome === "confirmed" ? (
            <>
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem_10rem]">
                <FormField label="Rola" htmlFor={ids.role} required>
                  <Input
                    id={ids.role}
                    value={role}
                    maxLength={200}
                    placeholder="np. Java Developer"
                    onChange={(event) => setRole(event.target.value)}
                  />
                </FormField>
                <FormField label="Ile osób" htmlFor={ids.headcount}>
                  <Input
                    id={ids.headcount}
                    type="number"
                    min={1}
                    max={50}
                    value={headcount}
                    onChange={(event) => setHeadcount(event.target.value)}
                  />
                </FormField>
                <FormField label="Od kiedy" htmlFor={ids.start}>
                  <Input
                    id={ids.start}
                    type="month"
                    value={startMonth}
                    onChange={(event) => setStartMonth(event.target.value)}
                  />
                </FormField>
              </div>
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">
                  Technologie (z mapy {demand.area ? "działu" : "klienta"} — zaznacz)
                </p>
                {demandSkills.length ? (
                  <div role="group" aria-label="Technologie do rekrutacji" className="flex flex-wrap gap-1.5">
                    {demandSkills.map((skill) => (
                      <button
                        key={skill.id}
                        type="button"
                        aria-pressed={skillIds.has(skill.id)}
                        onClick={() => toggleSkill(skill.id)}
                        className={cn(
                          "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                          skillIds.has(skill.id)
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-card text-foreground hover:bg-muted",
                        )}
                      >
                        {skill.name}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {mapQuery.isLoading
                      ? "Wczytywanie mapy technologii…"
                      : mapQuery.isError
                        ? "Mapy technologii nie udało się wczytać — technologie dopiszesz w rekrutacji."
                        : "Mapa nie zna jeszcze technologii tego działu."}
                  </p>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Zapisze rozmowę z menedżerem (opinia opcjonalnie) i otworzy nową rekrutację
                z klientem, działem, hiring managerem i zaznaczonymi technologiami — wypełnią się
                tylko puste pola.
              </p>
            </>
          ) : null}
        </section>
      ) : null}
      {needsManager ? (
        <FormField label="Menedżer u klienta (opcjonalnie)" htmlFor={ids.manager} className="mb-3">
          <Select
            value={pickedManagerId != null ? String(pickedManagerId) : NO_MANAGER}
            onValueChange={(value) =>
              setPickedManagerId(value === NO_MANAGER ? null : Number(value))
            }
          >
            <SelectTrigger id={ids.manager}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_MANAGER}>
                {orgQuery.isLoading ? "Wczytywanie osób klienta…" : "Wybierz osobę klienta"}
              </SelectItem>
              {[...people]
                .sort(
                  (a, b) =>
                    Number(b.area_id === demand?.area?.id) - Number(a.area_id === demand?.area?.id) ||
                    a.name.localeCompare(b.name, "pl"),
                )
                .map((person) => (
                  <SelectItem key={person.id} value={String(person.id)}>
                    {[person.name, person.position].filter(Boolean).join(" · ")}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </FormField>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label={demand ? "Forma" : "Rozmowa"} htmlFor={ids.channel}>
          <Select value={channel} onValueChange={(value) => setChannel(value as FeedbackChannel)}>
            <SelectTrigger id={ids.channel}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(FEEDBACK_CHANNEL_LABELS) as FeedbackChannel[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {FEEDBACK_CHANNEL_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Data" htmlFor={ids.date} required>
          <Input
            id={ids.date}
            type="date"
            value={heldOn}
            max={today}
            onChange={(event) => setHeldOn(event.target.value)}
          />
        </FormField>
      </div>

      {manager ? (
        <>
          <div className="mt-3 space-y-2">
            {consultants.length === 0 && manager ? (
              <p className="text-sm text-muted-foreground">
                Ta osoba nie jest menedżerem żadnego z naszych konsultantów — opinia zapisze
                samą rozmowę.
              </p>
            ) : null}
            {consultants.map((consultant) => {
              const isSkipped = skipped.has(consultant.contract_id);
              const values = scores[consultant.contract_id] ?? {};
              const name = consultant.candidate_name ?? `Kontrakt #${consultant.contract_id}`;
              return (
                <div
                  key={consultant.contract_id}
                  className="flex flex-wrap items-end justify-between gap-3 rounded-md border border-border/60 p-3"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{name}</p>
                    <p className="text-xs text-muted-foreground">
                      {[
                        consultant.role,
                        consultant.end_date
                          ? `${consultant.end_source === "contract" ? "umowa" : "zamówienie"} do ${formatIsoDatePl(consultant.end_date)}`
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                    </p>
                    {isSkipped ? (
                      <p className="text-xs text-muted-foreground">bez opinii w tej rozmowie</p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-end gap-3">
                    {FIELDS.map((field) => (
                      <ScorePicker
                        key={field}
                        label={SCORE_LABELS[field]}
                        groupLabel={`${SCORE_LABELS[field]} — ${name}`}
                        value={values[field] ?? null}
                        disabled={isSkipped}
                        onChange={(value) => setScore(consultant.contract_id, field, value)}
                      />
                    ))}
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-pressed={isSkipped}
                      aria-label={isSkipped ? `Oceń: ${name}` : `Pomiń: ${name}`}
                      onClick={() => toggleSkip(consultant.contract_id)}
                    >
                      {isSkipped ? "oceń" : "pomiń"}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span id={ids.extension} className="text-sm">
              Przedłużenie{nearestEnd ? ` zamówień do ${formatIsoDatePl(nearestEnd)}` : ""}
            </span>
            <SegmentedRadio
              labelledBy={ids.extension}
              size="sm"
              value={extension}
              onChange={(value) => setExtension(value === extension ? null : value)}
              options={EXTENSIONS.map((value) => ({ value, label: EXTENSION_LABELS[value] }))}
            />
          </div>

          <FormField label="Co mówi klient" htmlFor={ids.note} className="mt-3">
            <Textarea
              id={ids.note}
              rows={3}
              maxLength={FEEDBACK_NOTE_MAX}
              value={note}
              placeholder="np. Zespół chce zostać w tym składzie. Więcej inicjatywy na planowaniu."
              onChange={(event) => setNote(event.target.value)}
            />
          </FormField>
        </>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">
          Bez menedżera zapisze się tylko decyzja o popycie. Opinię o konsultantach, przedłużenie
          i notatkę zapiszesz, gdy wybierzesz menedżera.
        </p>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        Konsultant tej opinii nie widzi. Bez danych o zdrowiu i bez stawek. Opinia trafia
        do kontraktów ocenionych osób.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
