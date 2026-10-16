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
  type EmploymentStatus,
  type EmploymentType,
  type ProfileFields,
  type WorkLocation,
} from "@/lib/api/hr";

/** Wartości formularza kartoteki (puste pole = brak wartości). */
export interface ProfileFormState {
  manager_user_id: string;
  employment_type: EmploymentType;
  employment_status: EmploymentStatus;
  work_start_date: string;
  last_working_day: string;
  default_location: WorkLocation;
  timesheet_required: boolean;
  can_log_overtime: boolean;
  job_title: string;
  department: string;
  phone: string;
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

export function profileFormToPayload(form: ProfileFormState): ProfileFields {
  const text = (value: string) => (value.trim() ? value.trim() : null);
  return {
    manager_user_id: form.manager_user_id ? Number(form.manager_user_id) : null,
    employment_type: form.employment_type,
    employment_status: form.employment_status,
    work_start_date: form.work_start_date || null,
    last_working_day: form.last_working_day || null,
    default_location: form.default_location,
    timesheet_required: form.timesheet_required,
    can_log_overtime: form.can_log_overtime,
    job_title: text(form.job_title),
    department: text(form.department),
    phone: text(form.phone),
  };
}

interface ProfileFieldsFormProps {
  form: ProfileFormState;
  onChange: (next: ProfileFormState) => void;
  managers: { user_id: number; name: string }[];
  idPrefix: string;
}

/** Pola kartoteki — wspólne dla „Dodaj osobę” i „Edytuj kartotekę”. */
export function ProfileFieldsForm({
  form,
  onChange,
  managers,
  idPrefix,
}: ProfileFieldsFormProps) {
  const set = <K extends keyof ProfileFormState>(key: K, value: ProfileFormState[K]) =>
    onChange({ ...form, [key]: value });
  const id = (name: string) => `${idPrefix}-${name}`;

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
      <FormField label="Przełożony" htmlFor={id("manager")}>
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
            <SelectItem value={NO_MANAGER}>Bez przełożonego</SelectItem>
            {managers.map((manager) => (
              <SelectItem key={manager.user_id} value={String(manager.user_id)}>
                {manager.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Forma zatrudnienia" htmlFor={id("type")}>
        <Select
          value={form.employment_type}
          onValueChange={(value) => set("employment_type", value as EmploymentType)}
        >
          <SelectTrigger id={id("type")}>
            <SelectValue />
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
      <FormField
        label="Ostatni dzień pracy"
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
            Prowadzi timesheet
            <span className="block text-xs text-muted-foreground">
              Dostaje przypomnienie 1.–5. dnia miesiąca.
            </span>
          </span>
          <Switch
            checked={form.timesheet_required}
            onCheckedChange={(checked) => set("timesheet_required", checked)}
            aria-label="Prowadzi timesheet"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm">
          <span>
            Może wpisywać nadgodziny
            <span className="block text-xs text-muted-foreground">
              Ponad 8 godzin dziennie, z uzasadnieniem.
            </span>
          </span>
          <Switch
            checked={form.can_log_overtime}
            onCheckedChange={(checked) => set("can_log_overtime", checked)}
            aria-label="Może wpisywać nadgodziny"
          />
        </label>
      </div>
    </div>
  );
}
