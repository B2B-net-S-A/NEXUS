"use client";

import { useEffect, useMemo, useState } from "react";

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
import { ClientSinglePicker, type ClientRef } from "@/components/clients/ClientSinglePicker";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useApprovalBeneficiaries,
  useApprovalRoutePreview,
  useResubmitApproval,
  useSubmitApproval,
  type ApprovalKind,
  type ApprovalPayer,
  type ApprovalRecurrence,
  type ApprovalRequestInput,
  type ApprovalRequestRow,
} from "@/lib/api/hr-approvals";
import { monthTitlePl, shiftMonth } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import { KIND_OPTIONS, PAYER_OPTIONS, RECURRENCE_OPTIONS, moneyPl } from "./approvals-format";

export interface FormState {
  kind: ApprovalKind;
  title: string;
  purpose: string;
  amount: string;
  amountBasis: "gross" | "net";
  recurrence: ApprovalRecurrence;
  payer: ApprovalPayer;
  linkUrl: string;
  neededBy: string;
  startsOn: string;
  endsOn: string;
  beneficiary: string;
  payout: string;
  /** Etap 3 (0486): klient prezentu i NIP sprzedawcy, jeśli autor go zna. */
  client: ClientRef | null;
  sellerNip: string;
  /** 0491: punkt umowy albo numer aneksu (premia dla B2B). */
  contractBasis: string;
}

function initialState(row: ApprovalRequestRow | null, currentMonth: string): FormState {
  return {
    kind: row?.kind ?? "subscription",
    title: row?.title ?? "",
    purpose: row?.purpose ?? "",
    amount: row ? row.amount.replace(".", ",").replace(/,00$/, "") : "",
    amountBasis: row?.amount_basis ?? "gross",
    recurrence: row?.recurrence ?? "once",
    payer: row?.payer ?? "company_invoice",
    linkUrl: row?.link_url ?? "",
    neededBy: row?.needed_by ?? "",
    startsOn: row?.starts_on ?? "",
    endsOn: row?.ends_on ?? "",
    beneficiary: row?.beneficiary_user_id ? String(row.beneficiary_user_id) : "",
    payout:
      row?.payout_year && row.payout_month
        ? `${row.payout_year}-${String(row.payout_month).padStart(2, "0")}`
        : currentMonth,
    client:
      row?.client_id && row.client_name ? ({ id: row.client_id, name: row.client_name } as ClientRef) : null,
    sellerNip: row?.seller_nip ?? "",
    contractBasis: row?.contract_basis ?? "",
  };
}

/** Ciało `POST`/`PUT` z formularza; kwota z przecinkiem i spacjami jak wpisano. */
export function toInput(form: FormState): ApprovalRequestInput {
  const bonus = form.kind === "bonus";
  const [year, month] = form.payout.split("-").map(Number);
  return {
    kind: form.kind,
    title: form.title.trim(),
    purpose: form.purpose.trim(),
    amount: form.amount.replace(/\s/g, "").replace(",", "."),
    currency: "PLN",
    amount_basis: bonus ? "gross" : form.amountBasis,
    recurrence: bonus ? "once" : form.recurrence,
    payer: bonus ? null : form.payer,
    link_url: form.linkUrl.trim() || null,
    needed_by: form.neededBy || null,
    starts_on: bonus ? null : form.startsOn || null,
    ends_on: bonus ? null : form.endsOn || null,
    beneficiary_user_id: bonus && form.beneficiary ? Number(form.beneficiary) : null,
    payout_year: bonus ? year : null,
    payout_month: bonus ? month : null,
    client_id: form.kind === "gift" && form.client ? form.client.id : null,
    seller_nip: bonus ? null : form.sellerNip.replace(/[\s-]/g, "") || null,
    contract_basis: bonus ? form.contractBasis.trim() || null : null,
  };
}

interface ConsentRequestFormProps {
  /** Zgoda do poprawki (zwrócona z pytaniem albo jeszcze nierozpatrzona). */
  editing: ApprovalRequestRow | null;
  onDone: (row: ApprovalRequestRow) => void;
  onCancel: () => void;
}

export function ConsentRequestForm({ editing, onDone, onCancel }: ConsentRequestFormProps) {
  const today = warsawToday();
  const currentMonth = today.slice(0, 7);
  const [form, setForm] = useState<FormState>(() => initialState(editing, currentMonth));
  const [error, setError] = useState<string | null>(null);
  const submit = useSubmitApproval();
  const resubmit = useResubmitApproval();
  const preview = useApprovalRoutePreview();
  const beneficiaries = useApprovalBeneficiaries(form.kind === "bonus");
  const bonus = form.kind === "bonus";
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));
  const { showToast } = useToast();

  const payoutOptions = useMemo(
    () => [-1, 0, 1, 2].map((delta) => shiftMonth(currentMonth, delta)),
    [currentMonth],
  );
  const input = toInput(form);
  // Premia dla B2B (i formy „do uzupełnienia”) wymaga podstawy w umowie — 422 bez niej.
  const needsBasis =
    bonus &&
    (beneficiaries.data ?? []).some(
      (person) => String(person.user_id) === form.beneficiary && person.needs_contract_basis,
    );
  const ready =
    input.title.length > 0 &&
    input.purpose.length > 0 &&
    Number(input.amount) > 0 &&
    (!bonus || input.beneficiary_user_id !== null);
  const basisMissing = needsBasis && !input.contract_basis;
  const previewKey = ready ? JSON.stringify(input) : "";

  // „Kto zdecyduje” liczy serwer tą samą drogą co przy wysłaniu.
  useEffect(() => {
    if (!previewKey) return;
    const timer = window.setTimeout(() => preview.mutate(JSON.parse(previewKey)), 400);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);

  const yearly =
    !bonus && form.recurrence === "monthly" && Number(input.amount) > 0
      ? moneyPl(String(Number(input.amount) * 12))
      : null;

  const send = () => {
    if (!ready) {
      setError(
        bonus
          ? "Wybierz osobę i uzupełnij kwotę, za co i po co."
          : "Uzupełnij: co dokładnie, kwotę i po co.",
      );
      return;
    }
    if (basisMissing) {
      setError("Ta osoba współpracuje na B2B — wpisz podstawę w umowie: punkt umowy albo numer aneksu.");
      return;
    }
    setError(null);
    const handlers = {
      onSuccess: (row: ApprovalRequestRow) => {
        showToast("Wysłane do zgody.", "success");
        onDone(row);
      },
      onError: (err: unknown) => setError(apiErrorMessage(err, "Nie udało się wysłać zgody.")),
    };
    if (editing) resubmit.mutate({ id: editing.id, input }, handlers);
    else submit.mutate(input, handlers);
  };

  const pending = submit.isPending || resubmit.isPending;
  const route = preview.data;

  return (
    <div data-help="hr.consents.form" className="flex flex-wrap gap-4">
      <div className="min-w-0 flex-[999_1_560px] space-y-5 rounded-xl border border-border bg-card p-4 md:p-5">
        {editing?.status === "returned" && editing.decision_note ? (
          <div className="rounded-lg bg-warning-muted px-3.5 py-3 text-sm text-warning-muted-foreground">
            <p className="font-semibold">Pytanie od {editing.decided_by_name ?? "decydującego"}</p>
            <p className="mt-0.5 whitespace-pre-line">{editing.decision_note}</p>
          </div>
        ) : null}
        <fieldset>
          <legend className="mb-2 text-sm font-semibold text-foreground">
            Na co potrzebujesz zgody?
          </legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            {KIND_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={form.kind === option.value}
                onClick={() => set("kind", option.value)}
                className={cn(
                  "flex min-h-[72px] flex-col gap-1 rounded-lg border border-border p-2.5 text-left text-sm font-semibold text-foreground transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  form.kind === option.value && "border-primary bg-primary/5 ring-1 ring-primary",
                )}
              >
                {option.label}
                <span className="text-xs font-normal text-muted-foreground">{option.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        {bonus ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="Dla kogo" htmlFor="consent-person" required>
              <Select value={form.beneficiary} onValueChange={(value) => set("beneficiary", value)}>
                <SelectTrigger id="consent-person">
                  <SelectValue
                    placeholder={
                      beneficiaries.isLoading
                        ? "Wczytywanie…"
                        : (beneficiaries.data?.length ?? 0) === 0
                          ? "Brak osób w Twoim zespole"
                          : "Wybierz osobę"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {(beneficiaries.data ?? []).map((person) => (
                    <SelectItem key={person.user_id} value={String(person.user_id)}>
                      {person.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField label="Wypłata z listą płac" htmlFor="consent-payout" required>
              <Select value={form.payout} onValueChange={(value) => set("payout", value)}>
                <SelectTrigger id="consent-payout">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {payoutOptions.map((month) => (
                    <SelectItem key={month} value={month}>
                      {monthTitlePl(month)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </div>
        ) : null}

        {bonus ? (
          <FormField
            label="Podstawa w umowie"
            htmlFor="consent-contract-basis"
            description={
              needsBasis
                ? "Punkt umowy albo numer aneksu, który przewiduje to wynagrodzenie. Bez podstawy dla B2B nie wyślesz."
                : "Punkt umowy albo numer aneksu — przy umowie o pracę i zleceniu nieobowiązkowe."
            }
            required={needsBasis}
          >
            <Input
              id="consent-contract-basis"
              maxLength={200}
              placeholder="np. § 6 ust. 2 umowy z 01.03.2025 albo aneks nr 3 z 15.10.2026"
              value={form.contractBasis}
              onChange={(event) => set("contractBasis", event.target.value)}
            />
          </FormField>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            label={bonus ? "Za co — krótko" : "Co dokładnie"}
            htmlFor="consent-title"
            description={bonus ? undefined : "Nazwa tak, jak będzie na fakturze"}
            required
          >
            <Input
              id="consent-title"
              maxLength={200}
              value={form.title}
              onChange={(event) => set("title", event.target.value)}
            />
          </FormField>
          <FormField label="Link do oferty albo cennika" htmlFor="consent-link">
            <Input
              id="consent-link"
              type="url"
              inputMode="url"
              placeholder="https://"
              value={form.linkUrl}
              onChange={(event) => set("linkUrl", event.target.value)}
            />
          </FormField>
        </div>

        <div className="grid gap-4 sm:grid-cols-[200px_minmax(0,1fr)]">
          <FormField
            label={bonus ? "Kwota brutto" : "Kwota"}
            htmlFor="consent-amount"
            description={yearly ? `Rocznie wyjdzie ${yearly}` : undefined}
            required
          >
            <Input
              id="consent-amount"
              inputMode="decimal"
              value={form.amount}
              onChange={(event) => set("amount", event.target.value)}
            />
          </FormField>
          {bonus ? null : (
            <div className="flex flex-wrap gap-4">
              <div className="space-y-1.5">
                <span id="consent-basis" className="block text-sm font-medium text-foreground">
                  Netto czy brutto
                </span>
                <SegmentedRadio
                  labelledBy="consent-basis"
                  value={form.amountBasis}
                  onChange={(value) => set("amountBasis", value)}
                  options={[
                    { value: "gross", label: "Brutto" },
                    { value: "net", label: "Netto" },
                  ]}
                />
              </div>
              <div className="space-y-1.5">
                <span id="consent-recurrence" className="block text-sm font-medium text-foreground">
                  Jak często
                </span>
                <SegmentedRadio
                  labelledBy="consent-recurrence"
                  value={form.recurrence}
                  onChange={(value) => set("recurrence", value)}
                  options={RECURRENCE_OPTIONS}
                />
              </div>
            </div>
          )}
        </div>

        {bonus ? null : (
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1.5">
              <span id="consent-payer" className="block text-sm font-medium text-foreground">
                Kto płaci
              </span>
              <SegmentedRadio
                labelledBy="consent-payer"
                value={form.payer}
                onChange={(value) => set("payer", value)}
                options={PAYER_OPTIONS}
              />
            </div>
            {form.kind === "trip" ? (
              <>
                <FormField label="Wyjazd od" htmlFor="consent-from">
                  <Input
                    id="consent-from"
                    type="date"
                    value={form.startsOn}
                    onChange={(event) => set("startsOn", event.target.value)}
                  />
                </FormField>
                <FormField label="do" htmlFor="consent-to">
                  <Input
                    id="consent-to"
                    type="date"
                    value={form.endsOn}
                    onChange={(event) => set("endsOn", event.target.value)}
                  />
                </FormField>
              </>
            ) : null}
          </div>
        )}

        {bonus ? null : (
          <div className="grid gap-4 sm:grid-cols-2">
            {form.kind === "gift" ? (
              <FormField
                label="Dla klienta"
                htmlFor="consent-client"
                description="Prezent trafi do Historii zdarzeń klienta"
              >
                <ClientSinglePicker
                  value={form.client}
                  onChange={(client) => setForm((prev) => ({ ...prev, client }))}
                  queryKey="consent-gift-client"
                  placeholder="Wybierz klienta (opcjonalnie)"
                  allowClear
                />
              </FormField>
            ) : null}
            <FormField
              label="NIP sprzedawcy"
              htmlFor="consent-seller"
              description="Jeśli znasz — faktura z KSeF przypnie się sama"
            >
              <Input
                id="consent-seller"
                inputMode="numeric"
                maxLength={20}
                value={form.sellerNip}
                onChange={(event) => set("sellerNip", event.target.value)}
              />
            </FormField>
          </div>
        )}

        <FormField label="Po co — jedno, dwa zdania" htmlFor="consent-purpose" required>
          <Textarea
            id="consent-purpose"
            rows={3}
            maxLength={2000}
            value={form.purpose}
            onChange={(event) => set("purpose", event.target.value)}
          />
        </FormField>

        <FormField
          label="Potrzebne do"
          htmlFor="consent-needed"
          description="Zgoda z bliskim terminem jest na górze skrzynki zatwierdzającego"
          className="max-w-[220px]"
        >
          <Input
            id="consent-needed"
            type="date"
            min={today}
            value={form.neededBy}
            onChange={(event) => set("neededBy", event.target.value)}
          />
        </FormField>

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={send} disabled={pending}>
            {pending ? "Wysyłanie…" : editing ? "Wyślij poprawioną" : "Wyślij do zgody"}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Anuluj
          </Button>
          <span className="ml-auto text-xs text-muted-foreground">
            Wynagrodzenie z reguł umowy (placement, liga) liczą Płace same — tu go nie składasz.
          </span>
        </div>
      </div>

      <aside
        aria-label="Kto zdecyduje"
        className="min-w-0 flex-[1_1_300px] space-y-3 self-start rounded-xl border border-border bg-card p-4"
      >
        <h2 className="text-sm font-semibold text-foreground">Kto zdecyduje</h2>
        {!ready ? (
          <p className="text-sm text-muted-foreground">
            Uzupełnij kwotę i opis — pokażę, kto zdecyduje.
          </p>
        ) : preview.isError ? (
          <p className="text-sm text-muted-foreground">
            {apiErrorMessage(preview.error, "Nie udało się sprawdzić, kto zdecyduje.")}
          </p>
        ) : !route ? (
          <p className="text-sm text-muted-foreground">Sprawdzam…</p>
        ) : (
          <ol className="space-y-3 text-sm">
            {route.supervisor_name ? (
              <li>
                <p className="font-semibold text-foreground">{route.supervisor_name}</p>
                <p className="text-muted-foreground">
                  {route.supervisor_decides_alone
                    ? `Twój koordynator — potwierdza sam (do ${moneyPl(String(route.supervisor_limit ?? 0))})`
                    : "Twój koordynator — popiera albo dopytuje"}
                </p>
              </li>
            ) : null}
            {!route.supervisor_decides_alone ? (
              <li>
                <p className="font-semibold text-foreground">
                  {route.final_approver_names.join(", ") || "Zatwierdzający"}
                </p>
                <p className="text-muted-foreground">
                  {bonus
                    ? "wynagrodzenie dodatkowe zawsze u zatwierdzającego"
                    : route.supervisor_limit === null
                      ? "ten rodzaj zawsze u zatwierdzającego"
                      : `kwota ponad próg koordynatora (${moneyPl(String(route.supervisor_limit))})`}
                </p>
              </li>
            ) : null}
            <li className="text-muted-foreground">
              {bonus
                ? "Po zgodzie wynagrodzenie dodatkowe trafia do Płac jako przyznane."
                : "Po zgodzie możesz kupić albo zapłacić."}
            </li>
          </ol>
        )}
      </aside>
    </div>
  );
}
