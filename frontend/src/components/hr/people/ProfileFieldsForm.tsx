"use client";

import { Input } from "@/components/ui/input";
import { FormField } from "@/components/ui/form-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  EMPLOYMENT_STATUS_LABELS,
  EMPLOYMENT_TYPE_LABELS,
  LOCATION_LABELS,
  type Division,
  type EmploymentStatus,
  type EmploymentType,
  type ProfileFields,
  type WorkLocation,
} from "@/lib/api/hr";
import { DIVISION_LABELS } from "@/lib/api/hr-structure";
import { capitalize, employmentTerms } from "@/lib/hr-employment-terms";

import {
  contributionsReminder,
  contributionsStart,
  dayLabel,
  statutoryEntitlement,
} from "./form-rules";

/** Wartości formularza kartoteki (puste pole = brak wartości). */
export interface ProfileFormState {
  manager_user_id: string;
  /**
   * „” = forma niewybrana: ukryta przed czytającym (Kadry bez Płac zmieniają ją
   * bez podglądu, 19.10.2026) albo „do uzupełnienia”. Wtedy zapis jej nie wysyła.
   */
  employment_type: EmploymentType | "";
  employment_status: EmploymentStatus;
  work_start_date: string;
  last_working_day: string;
  default_location: WorkLocation;
  timesheet_required: boolean;
  can_log_overtime: boolean;
  job_title: string;
  department: string;
  phone: string;
  /**
   * Pion firmy („” = bez pionu). Brak klucza = pole nie występuje w tym miejscu
   * (kreator wejścia i „Dodaj osobę” — pion ustawia się w kartotece albo w Strukturze).
   */
  division?: Division | "";
  /**
   * Pola zależne od formy (etap 2, D8, D9) — tylko w „Edytuj kartotekę”;
   * brak klucza = pola nie ma w tym miejscu. Uczeń/student na zleceniu i data
   * końca zwolnienia ze składek; staż do urlopu i zaświadczenie ZUS na UoP.
   */
  student?: boolean;
  exempt_until?: string;
  seniority?: string;
  zus_certificate?: string;
  /** Podpis pustej formy: `hidden` — ukryta przed czytającym, `pending` — do uzupełnienia. */
  employment_type_blank?: "hidden" | "pending";
}

export const EMPTY_PROFILE_FORM: ProfileFormState = {
  manager_user_id: "",
  employment_type: "b2b",
  employment_status: "active",
  work_start_date: "",
  last_working_day: "",
  default_location: "onsite",
  timesheet_required: true,
  can_log_overtime: false,
  job_title: "",
  department: "",
  phone: "",
};

const NO_MANAGER = "none";
const NO_DIVISION = "none";

export function profileFormToPayload(form: ProfileFormState): ProfileFields {
  const text = (value: string) => (value.trim() ? value.trim() : null);
  return {
    manager_user_id: form.manager_user_id ? Number(form.manager_user_id) : null,
    ...(form.employment_type ? { employment_type: form.employment_type } : {}),
    employment_status: form.employment_status,
    work_start_date: form.work_start_date || null,
    last_working_day: form.last_working_day || null,
    default_location: form.default_location,
    timesheet_required: form.timesheet_required,
    can_log_overtime: form.can_log_overtime,
    job_title: text(form.job_title),
    department: text(form.department),
    phone: text(form.phone),
    ...(form.division === undefined ? {} : { division: form.division || null }),
    // Pola formy wysyłamy tylko przy tej formie; przy zmianie formy serwer sam
    // zdejmuje znacznik studenta, a staż z UoP zostaje na powrót.
    ...(form.student === undefined || form.employment_type !== "zlecenie"
      ? {}
      : {
          student_contribution_exempt: form.student,
          contribution_exempt_until: form.student ? form.exempt_until || null : null,
        }),
    ...(form.seniority === undefined || form.employment_type !== "uop"
      ? {}
      : {
          leave_seniority_years: form.seniority.trim() ? Number(form.seniority) : null,
          zus_certificate_received_on: form.zus_certificate || null,
        }),
  };
}

/** Sekcja „Forma decyduje o reszcie” — pola i podpowiedzi zależne od formy. */
export function FormSpecificFields({
  form,
  set,
  id,
}: {
  form: ProfileFormState;
  set: <K extends keyof ProfileFormState>(key: K, value: ProfileFormState[K]) => void;
  id: (name: string) => string;
}) {
  if (form.employment_type === "zlecenie" && form.student !== undefined) {
    const start = form.student ? contributionsStart(form.exempt_until) : null;
    const reminder = form.student ? contributionsReminder(form.exempt_until) : null;
    return (
      <div className="grid gap-3 rounded-lg border border-border bg-muted/40 p-3 sm:col-span-2 sm:grid-cols-2">
        <label className="flex items-center justify-between gap-3 text-sm sm:col-span-2">
          <span>
            Uczeń lub student do 26 lat
            <span className="block text-xs text-muted-foreground">
              Bez składek ZUS z tej umowy do końca statusu albo do dnia przed 26. urodzinami.
            </span>
          </span>
          <Switch
            checked={form.student}
            onCheckedChange={(checked) => set("student", checked)}
            aria-label="Uczeń lub student do 26 lat"
          />
        </label>
        {form.student ? (
          <FormField
            label="Zwolnienie ze składek do"
            htmlFor={id("exempt-until")}
            description="Wcześniejsza z dat: koniec statusu (obrona, skreślenie) albo dzień przed 26. urodzinami. Daty urodzenia NEXUS nie przechowuje."
          >
            <Input
              id={id("exempt-until")}
              type="date"
              value={form.exempt_until ?? ""}
              onChange={(event) => set("exempt_until", event.target.value)}
            />
          </FormField>
        ) : null}
        <p className="text-xs text-muted-foreground sm:col-span-2">
          {start && reminder
            ? `${dayLabel(reminder)} Płace dostaną przypomnienie: od ${dayLabel(start)} naliczamy składki. `
            : ""}
          Godziny: co miesiąc „Potwierdzenie godzin” z umowy zlecenia (art. 8b). NEXUS trzyma
          je 3 lata od dnia wypłaty.
        </p>
      </div>
    );
  }
  if (form.employment_type === "uop" && form.seniority !== undefined) {
    const years = form.seniority.trim() ? Number(form.seniority) : null;
    const days = statutoryEntitlement("uop", years);
    return (
      <div className="grid gap-3 rounded-lg border border-border bg-muted/40 p-3 sm:col-span-2 sm:grid-cols-2">
        <FormField
          label="Staż do urlopu (lata)"
          htmlFor={id("seniority")}
          description={
            days
              ? `Wymiar urlopu: ${days} dni (podpowiedź przy ustawianiu puli).`
              : "Poniżej 10 lat — 20 dni, od 10 lat — 26 dni."
          }
        >
          <Input
            id={id("seniority")}
            type="number"
            min={0}
            max={60}
            inputMode="numeric"
            value={form.seniority}
            onChange={(event) => set("seniority", event.target.value)}
          />
        </FormField>
        <FormField
          label="Zaświadczenie z ZUS otrzymane"
          htmlFor={id("zus")}
          description="Od 1 maja 2026 lata na zleceniu i działalności liczą się do stażu po przedstawieniu zaświadczenia."
        >
          <Input
            id={id("zus")}
            type="date"
            value={form.zus_certificate ?? ""}
            onChange={(event) => set("zus_certificate", event.target.value)}
          />
        </FormField>
      </div>
    );
  }
  if (form.employment_type === "b2b" && form.student !== undefined) {
    return (
      <p className="text-xs text-muted-foreground sm:col-span-2">
        Przy B2B: umowna pula płatnych dni przerwy (opcjonalnie) — ustawiasz ją w kartotece,
        jeśli jest w umowie. Godziny: „Raport godzin” do faktury.
      </p>
    );
  }
  return null;
}

interface ProfileFieldsFormProps {
  form: ProfileFormState;
  onChange: (next: ProfileFormState) => void;
  managers: { user_id: number; name: string }[];
  idPrefix: string;
  /** Pola ukryte w danym miejscu (np. kreator wejścia: status ustawia sprawa). */
  hide?: readonly ("employment_status" | "last_working_day")[];
}

/** Pola kartoteki — wspólne dla „Dodaj osobę” i „Edytuj kartotekę”. */
export function ProfileFieldsForm({
  form,
  onChange,
  managers,
  idPrefix,
  hide = [],
}: ProfileFieldsFormProps) {
  const set = <K extends keyof ProfileFormState>(key: K, value: ProfileFormState[K]) =>
    onChange({ ...form, [key]: value });
  const id = (name: string) => `${idPrefix}-${name}`;
  // Słowa formy (D4): na B2B i zleceniu „koordynator”, na umowie o pracę „przełożony”.
  const words = employmentTerms(form.employment_type || null);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FormField label="Stanowisko" htmlFor={id("title")}>
        <Input
          id={id("title")}
          value={form.job_title}
          maxLength={200}
          onChange={(event) => set("job_title", event.target.value)}
        />
      </FormField>
      <FormField label="Dział" htmlFor={id("department")}>
        <Input
          id={id("department")}
          value={form.department}
          maxLength={200}
          onChange={(event) => set("department", event.target.value)}
        />
      </FormField>
      <FormField
        label={capitalize(words.coordinator)}
        htmlFor={id("manager")}
        description={
          form.student !== undefined
            ? "Na B2B i zleceniu „koordynator”, na umowie o pracę „przełożony”."
            : undefined
        }
      >
        <Select
          value={form.manager_user_id || NO_MANAGER}
          onValueChange={(value) =>
            set("manager_user_id", value === NO_MANAGER ? "" : value)
          }
        >
          <SelectTrigger id={id("manager")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_MANAGER}>Bez {words.coordinator_genitive}</SelectItem>
            {managers.map((manager) => (
              <SelectItem key={manager.user_id} value={String(manager.user_id)}>
                {manager.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      {form.division === undefined ? null : (
        <FormField label="Pion" htmlFor={id("division")}>
          <Select
            value={form.division || NO_DIVISION}
            onValueChange={(value) =>
              set("division", value === NO_DIVISION ? "" : (value as Division))
            }
          >
            <SelectTrigger id={id("division")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_DIVISION}>Bez pionu</SelectItem>
              {(Object.keys(DIVISION_LABELS) as Division[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {DIVISION_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      )}
      <FormField
        label="Forma współpracy"
        htmlFor={id("type")}
        description={
          form.employment_type_blank === "hidden" && !form.employment_type
            ? "Formę widzą ta osoba, jej koordynator, admin i Finanse. Możesz ją zmienić — obecnej nie pokazujemy."
            : undefined
        }
      >
        <Select
          value={form.employment_type}
          onValueChange={(value) => set("employment_type", value as EmploymentType)}
        >
          <SelectTrigger id={id("type")}>
            <SelectValue
              placeholder={
                form.employment_type_blank === "pending"
                  ? "Do uzupełnienia — wybierz"
                  : "Bez zmian (forma ukryta)"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(EMPLOYMENT_TYPE_LABELS) as EmploymentType[]).map((key) => (
              <SelectItem key={key} value={key}>
                {EMPLOYMENT_TYPE_LABELS[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormSpecificFields form={form} set={set} id={id} />
      {hide.includes("employment_status") ? null : (
        <FormField label="Status" htmlFor={id("status")}>
          <Select
            value={form.employment_status}
            onValueChange={(value) =>
              set("employment_status", value as EmploymentStatus)
            }
          >
            <SelectTrigger id={id("status")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(EMPLOYMENT_STATUS_LABELS) as EmploymentStatus[]).map(
                (key) => (
                  <SelectItem key={key} value={key}>
                    {EMPLOYMENT_STATUS_LABELS[key]}
                  </SelectItem>
                ),
              )}
            </SelectContent>
          </Select>
        </FormField>
      )}
      <FormField label="Domyślnie pracuje" htmlFor={id("location")}>
        <Select
          value={form.default_location}
          onValueChange={(value) => set("default_location", value as WorkLocation)}
        >
          <SelectTrigger id={id("location")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(LOCATION_LABELS) as WorkLocation[]).map((key) => (
              <SelectItem key={key} value={key}>
                {LOCATION_LABELS[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Start pracy" htmlFor={id("start")}>
        <Input
          id={id("start")}
          type="date"
          value={form.work_start_date}
          onChange={(event) => set("work_start_date", event.target.value)}
        />
      </FormField>
      {hide.includes("last_working_day") ? null : (
        <FormField
          label="Ostatni dzień współpracy"
          htmlFor={id("last")}
          description="Puste, dopóki osoba nie odchodzi."
        >
          <Input
            id={id("last")}
            type="date"
            value={form.last_working_day}
            onChange={(event) => set("last_working_day", event.target.value)}
          />
        </FormField>
      )}
      <FormField label="Telefon służbowy" htmlFor={id("phone")}>
        <Input
          id={id("phone")}
          value={form.phone}
          maxLength={64}
          onChange={(event) => set("phone", event.target.value)}
        />
      </FormField>
      <div className="flex flex-col gap-3 sm:col-span-2">
        <label className="flex items-center justify-between gap-3 text-sm">
          <span>
            Prowadzi {words.timesheet_accusative}
            <span className="block text-xs text-muted-foreground">
              Dostaje przypomnienie 1.–5. dnia miesiąca.
            </span>
          </span>
          <Switch
            checked={form.timesheet_required}
            onCheckedChange={(checked) => set("timesheet_required", checked)}
            aria-label={`Prowadzi ${words.timesheet_accusative}`}
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm">
          <span>
            Może wpisywać {words.overtime}
            <span className="block text-xs text-muted-foreground">
              {words.flow === "request"
                ? "Ponad 8 godzin dziennie, z uzasadnieniem."
                : "Ponad 8 godzin dziennie, z krótkim opisem."}
            </span>
          </span>
          <Switch
            checked={form.can_log_overtime}
            onCheckedChange={(checked) => set("can_log_overtime", checked)}
            aria-label={`Może wpisywać ${words.overtime}`}
          />
        </label>
      </div>
    </div>
  );
}
