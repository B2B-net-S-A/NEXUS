"use client";

import { useState, type ChangeEvent, type ReactNode } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  subjectKey,
  usePersonData,
  useSavePersonData,
  type AddressKey,
  type PersonData,
  type PersonSubject,
} from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

import { errorDetail } from "./payroll-model";
import {
  ADDRESS_FIELDS,
  PIT2_OPTIONS,
  RELIEFS,
  personForm,
  personFormProblems,
  personUpdate,
  type Pit2Value,
  type PersonForm,
} from "./person-data-model";

const CONTROL =
  "h-8 w-full min-w-0 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10 disabled:cursor-not-allowed disabled:opacity-60";
const OWN_DATA =
  "Swoich danych płacowych nie zmieniasz sam — zrobi to druga osoba z Administracji współpracy albo Rozliczeń, albo administrator.";

/** Pola formularza typu `string` (bez list wyboru i przełączników). */
type TextKey = {
  [K in keyof PersonForm]: string extends PersonForm[K] ? (PersonForm[K] extends string ? K : never) : never;
}[keyof PersonForm];

export interface PersonDataDialogProps {
  subject: PersonSubject | null;
  /** Forma umowy, gdy wiadomo (pozycja listy, wiersz osoby) — przy UoP chowa pola zlecenia. */
  kind?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Dane kadrowo-płacowe osoby (tożsamość, adres, urząd, ZUS, PIT-2, ulgi,
 * PPK, rachunek) — okno do użycia także poza Księgowością (Administracja
 * współpracy, Rozliczenia, administrator). API nie zwraca pełnych numerów: pola PESEL-u, dokumentu
 * i rachunku są puste, a wpisana wartość zastępuje zapisaną. Zapis wysyła
 * tylko zmiany z wersją — gdy ktoś zmienił dane w międzyczasie, serwer
 * odmawia (409) i trzeba odświeżyć.
 */
export function PersonDataDialog({ subject, kind, open, onOpenChange }: PersonDataDialogProps) {
  return (
    <Dialog open={open && subject != null} onOpenChange={onOpenChange}>
      <DialogContent size="xl">
        {open && subject ? (
          <PersonDataBody
            key={subjectKey(subject)}
            subject={subject}
            kind={kind ?? null}
            onClose={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function PersonDataBody({
  subject,
  kind,
  onClose,
}: {
  subject: PersonSubject;
  kind: string | null;
  onClose: () => void;
}) {
  const person = usePersonData(subject);
  if (!person.isSuccess) {
    return (
      <>
        <DialogHeader>
          <DialogTitle className="text-lg">Dane płacowe</DialogTitle>
        </DialogHeader>
        <DialogBody>
          {person.isError ? (
            <QueryStateNotice
              state="error"
              description={apiErrorMessage(person.error, "Nie udało się wczytać danych płacowych.")}
              onRetry={() => person.refetch()}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Wczytywanie danych płacowych…</p>
          )}
        </DialogBody>
      </>
    );
  }
  return (
    <PersonDataForm
      key={person.data.version}
      subject={subject}
      data={person.data}
      kind={kind}
      onClose={onClose}
      onRefresh={() => void person.refetch()}
    />
  );
}

function PersonDataForm({
  subject,
  data,
  kind,
  onClose,
  onRefresh,
}: {
  subject: PersonSubject;
  data: PersonData;
  kind: string | null;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const { showToast } = useToast();
  const save = useSavePersonData(subject);
  const [form, setForm] = useState<PersonForm>(() => personForm(data));
  const [stale, setStale] = useState<string | null>(null);
  const body = personUpdate(data, form);
  const problems = personFormProblems(form, data);
  const contractor = data.candidate_id != null;
  const team = data.user_id != null;
  const mandate = contractor || kind !== "uop";
  const byDocument = !data.pesel_masked && !form.pesel.trim();
  const labels = Object.fromEntries(data.missing.map((code, index) => [code, data.missing_labels[index] ?? code]));
  const blocking = data.blocks_calculation.map((code) => labels[code] ?? code);

  const set = <K extends keyof PersonForm>(key: K, value: PersonForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const setAddress = (key: AddressKey, value: string) =>
    setForm((current) => ({ ...current, address: { ...current.address, [key]: value } }));
  /** Zwykłe pole tekstowe formularza (wartość i zmiana). */
  const text = (key: TextKey) => ({
    value: form[key],
    onChange: (event: ChangeEvent<HTMLInputElement>) => set(key, event.target.value),
  });

  const submit = () => {
    if (!body || problems.length) return;
    save.mutate(body, {
      onSuccess: (saved) => {
        showToast(
          saved.missing_labels.length
            ? `Zapisano dane płacowe — brakuje jeszcze: ${saved.missing_labels.join(", ")}.`
            : "Zapisano dane płacowe.",
        );
        onClose();
      },
      onError: (error) => {
        const message = apiErrorMessage(error, "Nie udało się zapisać danych płacowych.");
        if (errorDetail(error).code === "stale_person_data") setStale(message);
        else showToast(message, "error");
      },
    });
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle className="truncate text-lg">Dane płacowe — {data.name}</DialogTitle>
        <DialogDescription>
          {contractor ? "Kontraktor u klienta (zlecenie)" : "Osoba z zespołu"} ·{" "}
          {data.exists && data.updated_at
            ? `zmienione ${data.updated_at.slice(0, 10).split("-").reverse().join(".")}`
            : "jeszcze bez danych płacowych"}
          . Widzą je Administracja współpracy, Rozliczenia i administrator.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="space-y-4">
        {!data.can_edit ? <Note tone="info">{OWN_DATA}</Note> : null}
        {stale ? (
          <Note tone="danger">
            {stale}{" "}
            <button
              type="button"
              className="font-medium text-primary hover:underline"
              onClick={() => {
                setStale(null);
                onRefresh();
              }}
            >
              Odśwież
            </button>
          </Note>
        ) : null}
        {data.missing_labels.length ? (
          <Note tone={blocking.length ? "danger" : "warning"}>
            Brakuje: {data.missing_labels.join(", ")}.
            {blocking.length ? ` Bez tego lista płac się nie policzy: ${blocking.join(", ")}.` : " To blokuje tylko pliki ZUS i PIT."}
          </Note>
        ) : null}

        <fieldset disabled={!data.can_edit} className="min-w-0">
          <div className="grid gap-x-6 gap-y-5 md:grid-cols-2">
            <div className="min-w-0 space-y-5">
              <Section title="Osoba">
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field
                    wide
                    label="PESEL"
                    hint={
                      data.pesel_masked
                        ? `Zapisany: ${data.pesel_masked}. Pełnego numeru nie pokazujemy — wpisz nowy, żeby go zmienić.`
                        : "Brak PESEL-u — wpisz go albo dokument z datą urodzenia i płcią."
                    }
                  >
                    <input
                      aria-label="Nowy PESEL"
                      autoComplete="off"
                      inputMode="numeric"
                      maxLength={14}
                      placeholder={data.pesel_masked ? "nowy PESEL" : "11 cyfr"}
                      className={cn(CONTROL, "tabular-nums")}
                      {...text("pesel")}
                    />
                  </Field>
                  {byDocument ? (
                    <>
                      <Field label="Dokument tożsamości">
                        <select
                          aria-label="Rodzaj dokumentu"
                          className={CONTROL}
                          value={form.document_type}
                          onChange={(event) => set("document_type", event.target.value as PersonForm["document_type"])}
                        >
                          <option value="">—</option>
                          <option value="id_card">dowód osobisty</option>
                          <option value="passport">paszport</option>
                        </select>
                      </Field>
                      <Field
                        label="Numer dokumentu"
                        hint={data.document_masked ? `Zapisany: ${data.document_masked}` : undefined}
                      >
                        <input
                          aria-label="Nowy numer dokumentu"
                          autoComplete="off"
                          placeholder={data.document_masked ? "nowy numer" : "np. ABC123456"}
                          className={CONTROL}
                          {...text("document_number")}
                        />
                      </Field>
                      <Field label="Data urodzenia">
                        <input type="date" aria-label="Data urodzenia" className={CONTROL} {...text("birth_date")} />
                      </Field>
                      <Field label="Płeć">
                        <select
                          aria-label="Płeć"
                          className={CONTROL}
                          value={form.sex}
                          onChange={(event) => set("sex", event.target.value as PersonForm["sex"])}
                        >
                          <option value="">—</option>
                          <option value="F">kobieta</option>
                          <option value="M">mężczyzna</option>
                        </select>
                      </Field>
                      <Field wide label="NIP (osoba bez PESEL-u)" hint="potrzebny do PIT-11, gdy osoba nie ma PESEL-u">
                        <input
                          aria-label="NIP (osoba bez PESEL-u)"
                          autoComplete="off"
                          inputMode="numeric"
                          maxLength={13}
                          placeholder="10 cyfr"
                          className={cn(CONTROL, "tabular-nums")}
                          {...text("nip")}
                        />
                      </Field>
                    </>
                  ) : null}
                  <Field label="Imię">
                    <input aria-label="Imię" className={CONTROL} {...text("first_name")} />
                  </Field>
                  <Field label="Nazwisko">
                    <input aria-label="Nazwisko" className={CONTROL} {...text("last_name")} />
                  </Field>
                  {!data.names_confirmed ? (
                    <p className="text-[11px] leading-4 text-muted-foreground sm:col-span-2">
                      Imię i nazwisko podpowiada konto — zapis je potwierdzi.
                    </p>
                  ) : null}
                  <Field label="Obywatelstwo" hint="kod kraju, np. PL">
                    <input aria-label="Obywatelstwo" maxLength={2} className={cn(CONTROL, "uppercase")} {...text("citizenship")} />
                  </Field>
                </div>
              </Section>

              <Section title="Urząd skarbowy i ZUS">
                <div className="grid gap-2 sm:grid-cols-[7rem_minmax(0,1fr)]">
                  <Field label="Kod urzędu">
                    <input
                      aria-label="Kod urzędu skarbowego"
                      inputMode="numeric"
                      maxLength={4}
                      placeholder="4 cyfry"
                      className={cn(CONTROL, "tabular-nums")}
                      {...text("tax_office_code")}
                    />
                  </Field>
                  <Field label="Urząd skarbowy">
                    <input aria-label="Nazwa urzędu skarbowego" placeholder="nazwa urzędu" className={CONTROL} {...text("tax_office_name")} />
                  </Field>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field label="Kod tytułu ubezpieczenia" hint="6 cyfr: 011000 — umowa o pracę, 041100 — zlecenie">
                    <input
                      aria-label="Kod tytułu ubezpieczenia"
                      inputMode="numeric"
                      maxLength={8}
                      placeholder="np. 011000"
                      className={cn(CONTROL, "tabular-nums")}
                      {...text("zus_title_code")}
                    />
                  </Field>
                  <Field label="Oddział NFZ" hint="01R–16R; puste = z województwa w adresie">
                    <input
                      aria-label="Oddział NFZ"
                      maxLength={3}
                      placeholder="np. 07R"
                      className={cn(CONTROL, "uppercase tabular-nums")}
                      {...text("nfz_code")}
                    />
                  </Field>
                  {team ? (
                    <Field label="Wymiar etatu" hint="dla umowy o pracę, np. 1/1 albo 1/2">
                      <input aria-label="Wymiar etatu" maxLength={5} placeholder="1/1" className={cn(CONTROL, "tabular-nums")} {...text("work_time")} />
                    </Field>
                  ) : null}
                </div>
              </Section>

              <Section title="PPK">
                <Check
                  label="Uczestniczy w PPK"
                  checked={form.ppk_participates}
                  onChange={(value) => set("ppk_participates", value)}
                />
                {form.ppk_participates ? (
                  <div className="grid gap-2 sm:grid-cols-3">
                    <Field label="Podstawowa osoby, %" hint="0,5–2">
                      <input aria-label="PPK — wpłata podstawowa osoby" inputMode="decimal" className={CONTROL} {...text("ppk_employee_rate")} />
                    </Field>
                    <Field label="Dodatkowa osoby, %" hint="0–2">
                      <input aria-label="PPK — wpłata dodatkowa osoby" inputMode="decimal" className={CONTROL} {...text("ppk_employee_extra")} />
                    </Field>
                    <Field label="Dodatkowa pracodawcy, %" hint="0–2,5">
                      <input aria-label="PPK — wpłata dodatkowa pracodawcy" inputMode="decimal" className={CONTROL} {...text("ppk_employer_extra")} />
                    </Field>
                  </div>
                ) : null}
              </Section>
            </div>

            <div className="min-w-0 space-y-5">
              <Section title="Adres zamieszkania">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {ADDRESS_FIELDS.map((field) => (
                    <Field key={field.key} label={field.label}>
                      <input
                        aria-label={field.label}
                        placeholder={field.placeholder}
                        className={cn(CONTROL, field.key === "country" && "uppercase")}
                        maxLength={field.key === "country" ? 2 : 60}
                        value={form.address[field.key]}
                        onChange={(event) => setAddress(field.key, event.target.value)}
                      />
                    </Field>
                  ))}
                </div>
              </Section>

              <Section title="Podatek">
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field label="PIT-2 (kwota zmniejszająca)">
                    <select
                      aria-label="PIT-2"
                      className={CONTROL}
                      value={form.pit2}
                      onChange={(event) => set("pit2", event.target.value as Pit2Value)}
                    >
                      {PIT2_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Koszty uzyskania" hint="dla umowy o pracę">
                    <select
                      aria-label="Koszty uzyskania"
                      className={CONTROL}
                      value={form.kup}
                      onChange={(event) => set("kup", event.target.value as PersonForm["kup"])}
                    >
                      <option value="standard">zwykłe</option>
                      <option value="increased">podwyższone</option>
                    </select>
                  </Field>
                </div>
                <div className="space-y-1.5">
                  {RELIEFS.map((relief) => (
                    <Check
                      key={relief.key}
                      label={relief.label}
                      checked={form.reliefs.includes(relief.key)}
                      onChange={(value) =>
                        set(
                          "reliefs",
                          value ? [...form.reliefs, relief.key] : form.reliefs.filter((item) => item !== relief.key),
                        )
                      }
                    />
                  ))}
                  <Check
                    label="Rezygnacja z ulgi dla młodych"
                    hint={data.youth_relief_now ? "Ulga dla młodych działa teraz (do 26 lat)." : undefined}
                    checked={form.youth_relief_waived}
                    onChange={(value) => set("youth_relief_waived", value)}
                  />
                </div>
                {contractor ? (
                  <Field label="Student do" hint="uczeń lub student do 26 lat — bez składek ZUS do tej daty">
                    <input type="date" aria-label="Student do" className={CONTROL} {...text("student_exempt_until")} />
                  </Field>
                ) : null}
              </Section>

              <Section title="Składki">
                {mandate ? (
                  <div className="space-y-1.5">
                    <p className="text-[12px] font-medium">Zlecenie</p>
                    <Check
                      label="Emerytalne i rentowe"
                      hint="bez nich (zbieg tytułów) — tylko zdrowotna"
                      checked={form.mandate_pension_insurance}
                      onChange={(value) => set("mandate_pension_insurance", value)}
                    />
                    <Check
                      label="Dobrowolne chorobowe"
                      checked={form.mandate_sickness_voluntary}
                      onChange={(value) => set("mandate_sickness_voluntary", value)}
                    />
                    <Check
                      label="Wypadkowe"
                      checked={form.mandate_accident_insurance}
                      onChange={(value) => set("mandate_accident_insurance", value)}
                    />
                  </div>
                ) : null}
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field label="Bez Funduszu Pracy do">
                    <input type="date" aria-label="Bez Funduszu Pracy do" className={CONTROL} {...text("labour_fund_exempt_until")} />
                  </Field>
                  <Field label="Bez FGŚP do">
                    <input type="date" aria-label="Bez FGŚP do" className={CONTROL} {...text("fgsp_exempt_until")} />
                  </Field>
                </div>
              </Section>

              {contractor ? (
                <Section title="Wypłata">
                  <Field
                    label="Rachunek do wypłaty"
                    hint={
                      data.bank_account_last4
                        ? `Zapisany: •••• ${data.bank_account_last4}. Wpisz nowy, żeby go zmienić.`
                        : "Brak rachunku — bez niego wypłata nie trafi do pliku przelewów."
                    }
                  >
                    <input
                      aria-label="Nowy rachunek do wypłaty"
                      autoComplete="off"
                      inputMode="numeric"
                      placeholder="26 cyfr NRB"
                      className={cn(CONTROL, "tabular-nums")}
                      {...text("bank_account")}
                    />
                  </Field>
                </Section>
              ) : null}
            </div>
          </div>
        </fieldset>

        {data.can_edit && problems.length ? (
          <ul aria-label="Do poprawy" className="space-y-0.5 text-[12px] text-destructive">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {data.can_edit ? "Anuluj" : "Zamknij"}
        </Button>
        {data.can_edit ? (
          <Button size="sm" disabled={!body || problems.length > 0} loading={save.isPending} onClick={submit}>
            Zapisz dane
          </Button>
        ) : null}
      </DialogFooter>
    </>
  );
}

function Note({ tone, children }: { tone: "info" | "warning" | "danger"; children: ReactNode }) {
  return (
    <p
      role="status"
      className={cn(
        "rounded-md px-3 py-2 text-[13px]",
        tone === "danger" && "bg-destructive-muted text-destructive-muted-foreground",
        tone === "warning" && "bg-warning-muted text-warning-muted-foreground",
        tone === "info" && "bg-info-muted text-info-muted-foreground",
      )}
    >
      {children}
    </p>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0 space-y-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

function Field({ label, hint, wide, children }: { label: string; hint?: string; wide?: boolean; children: ReactNode }) {
  return (
    <label className={cn("grid min-w-0 content-start gap-1", wide && "sm:col-span-2")}>
      <span className="text-[12px] font-medium">{label}</span>
      {children}
      {hint ? <span className="text-[11px] leading-4 text-muted-foreground">{hint}</span> : null}
    </label>
  );
}

function Check({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 text-[13px]">
      <Checkbox aria-label={label} checked={checked} onCheckedChange={(value) => onChange(value === true)} className="mt-0.5" />
      <span className="min-w-0">
        {label}
        {hint ? <span className="block text-[11px] leading-4 text-muted-foreground">{hint}</span> : null}
      </span>
    </label>
  );
}
