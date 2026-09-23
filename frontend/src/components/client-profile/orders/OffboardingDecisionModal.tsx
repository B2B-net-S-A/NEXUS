"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";

import { AppModal } from "@/components/ds";
import type { ContractWithOrdersRead } from "@/lib/api/dlPortal";
import type {
  MdTransferMethod,
  OrderGroupRead,
  OrderLineRead,
  OrderLineTakeoverInput,
  OrderOffboardingResolutionInput,
} from "@/lib/api/orderGroups";
import {
  contractCostRatePerMd,
  defaultEntryDate,
  effectiveTransferMethod,
  transferPreview,
} from "@/lib/order-takeover";
import { warsawToday } from "@/lib/warsaw-date";
import { formatDate } from "@/types/client-profile";

import { formatMd } from "./MdBudgetBar";
import { MdTransferChoice } from "./MdTransferChoice";
import {
  TakeoverTermsFields,
  emptyTakeoverTerms,
  takeoverTermsError,
  toTakeoverInput,
  type TakeoverTermsValue,
} from "./TakeoverTermsFields";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  group: OrderGroupRead | null;
  line: OrderLineRead | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: OrderOffboardingResolutionInput) => void;
  /** Osoby ze szkiców klienta — grupa „Nowe osoby u klienta" (ticket 09.2026).
   *  Wybór takiej osoby daje ten sam efekt co „Wejdź za konsultanta". */
  newPeople?: readonly ContractWithOrdersRead[];
  onTakeover?: (values: OrderLineTakeoverInput) => void;
}

/** Decyzja Delivery Leada o linii MD po zakończeniu kontraktu.
 *
 *  Modal nie wylicza puli samodzielnie — pokazuje snapshot sprawy i wysyła
 *  jedynie intencję z wersją. Przeliczenie i blokada konkurencyjnych decyzji
 *  pozostają po stronie backendu. */
export function OffboardingDecisionModal({
  open,
  onOpenChange,
  group,
  line,
  submitting,
  error,
  onSubmit,
  newPeople = [],
  onTakeover,
}: Props) {
  const [action, setAction] = useState<"remove" | "transfer" | "restore">(
    "remove",
  );
  // `line:<id>` — osoba z tego zamówienia; `contract:<id>` — nowa osoba
  // ze szkiców klienta (wejdzie za odchodzącego jako nowa linia).
  const [targetKey, setTargetKey] = useState("");
  const [method, setMethod] = useState<MdTransferMethod | null>(null);
  const [terms, setTerms] = useState<TakeoverTermsValue>(
    emptyTakeoverTerms(warsawToday()),
  );
  // Data, do której współpraca trwa po przywróceniu. Oryginalna data końca
  // linii przepadła przy offboardingu (sprawa snapshotuje pulę i stawki, nie
  // okres), więc to jest DECYZJA operatora, nie odtworzenie — dlatego pole
  // jest puste, a nie „przywrócone".
  const [restoreEndDate, setRestoreEndDate] = useState("");

  const offboardingCase = line?.offboarding_case ?? null;
  const recipients = useMemo(
    () =>
      (group?.lines ?? []).filter(
        (candidate) =>
          candidate.id !== line?.id &&
          candidate.is_active &&
          candidate.offboarding_case?.status !== "pending",
      ),
    [group, line],
  );

  // Zamówienie z datą końca wymaga daty także od linii — pusta znaczyłaby
  // „bezterminowo", czyli linia przeżywająca własne zamówienie. Serwer to
  // odrzuca; formularz nie może więc pozwolić wysłać takiego żądania.
  const groupEndDate = group?.end_date ?? null;
  const restoreEndRequired = groupEndDate !== null;

  useEffect(() => {
    if (!open) return;
    setAction("remove");
    setTargetKey("");
    setMethod(null);
    setTerms(
      emptyTakeoverTerms(
        defaultEntryDate(offboardingCase?.effective_date ?? null, warsawToday()),
      ),
    );
    // Podpowiedź = koniec zamówienia. Operator może ją skrócić; nie może jej
    // wydłużyć poza zamówienie (walidacja niżej i po stronie serwera).
    setRestoreEndDate(group?.end_date ?? "");
  }, [open, offboardingCase?.id, offboardingCase?.effective_date, group?.end_date]);

  const restoreEndTooLate =
    groupEndDate !== null &&
    restoreEndDate !== "" &&
    restoreEndDate > groupEndDate;

  const sharedPool = offboardingCase?.uses_shared_md_pool === true;
  const targetLine = targetKey.startsWith("line:")
    ? (recipients.find((item) => `line:${item.id}` === targetKey) ?? null)
    : null;
  const targetPerson = targetKey.startsWith("contract:")
    ? (newPeople.find((item) => `contract:${item.contract_id}` === targetKey) ?? null)
    : null;
  const remainingMd = offboardingCase?.remaining_md_snapshot ?? 0;
  const departingRate =
    offboardingCase?.rate_revenue_snapshot ?? line?.rate_revenue ?? null;
  const existingPreview =
    targetLine && !sharedPool
      ? transferPreview({
          unit: line?.pool_unit,
          remaining: remainingMd,
          departingRate,
          incomingRate: targetLine.rate_revenue,
        })
      : null;
  const existingMethod = effectiveTransferMethod(line?.pool_unit, method);
  const departingForTakeover: OrderLineRead | null =
    line && offboardingCase
      ? {
          ...line,
          takeover_source: "ended",
          departure_date: offboardingCase.effective_date,
          rate_revenue: departingRate,
        }
      : null;
  const takeoverError = targetPerson
    ? takeoverTermsError(terms, departingForTakeover)
    : null;
  const costSuggestion = targetPerson
    ? contractCostRatePerMd(targetPerson.rate_candidate, targetPerson.rate_unit)
    : null;

  const transferReady =
    targetLine !== null
      ? sharedPool || existingMethod !== null
      : targetPerson !== null && onTakeover !== undefined && takeoverError === null;

  const canSubmit =
    !submitting &&
    offboardingCase?.status === "pending" &&
    (action === "remove" ||
      (action === "transfer" && transferReady) ||
      (action === "restore" &&
        !restoreEndTooLate &&
        (!restoreEndRequired || restoreEndDate !== "")));

  function submit() {
    if (!offboardingCase || !canSubmit) return;
    if (action === "remove") {
      onSubmit({
        action: "remove",
        expected_version: offboardingCase.version,
      });
      return;
    }
    if (action === "restore") {
      onSubmit({
        action: "restore",
        restore_end_date: restoreEndDate || null,
        expected_version: offboardingCase.version,
      });
      return;
    }
    if (targetPerson && departingForTakeover && onTakeover) {
      onTakeover(
        toTakeoverInput(terms, targetPerson.contract_id, departingForTakeover),
      );
      return;
    }
    if (!targetLine) return;
    onSubmit(
      sharedPool
        ? {
            action: "transfer",
            target_order_id: targetLine.id,
            rate_basis: "recipient",
            expected_version: offboardingCase.version,
          }
        : {
            action: "transfer",
            target_order_id: targetLine.id,
            md_transfer_method: existingMethod as MdTransferMethod,
            expected_version: offboardingCase.version,
          },
    );
  }

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Zakończenie współpracy — decyzja o MD"
      description={
        group && line
          ? `Zamówienie nr ${group.order_number} · ${line.consultant_name}`
          : undefined
      }
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
          >
            Anuluj
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : "Zapisz decyzję"}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? (
          <p
            role="alert"
            className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        {offboardingCase ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-3 text-sm">
            <p className="flex items-center gap-2 font-medium text-destructive">
              <AlertTriangle className="h-4 w-4" aria-hidden />
              Współpraca zakończona {formatDate(offboardingCase.effective_date)}
            </p>
            <p className="mt-1 text-muted-foreground">
              {offboardingCase.uses_shared_md_pool
                ? "Ta osoba korzystała ze wspólnej puli MD — nie ma wydzielonej puli osobistej."
                : `Pozostało ${formatMd(offboardingCase.remaining_md_snapshot)} MD według stanu zapisanego w chwili zakończenia kontraktu.`}
            </p>
          </div>
        ) : null}

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Decyzja po zakończeniu współpracy
          </legend>
          <label className="flex cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-3">
            <input
              type="radio"
              name="offboarding-action"
              value="remove"
              checked={action === "remove"}
              onChange={() => setAction("remove")}
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium text-foreground">
                Usuń z zamówienia
              </span>
              <span className="block text-xs text-muted-foreground">
                Osoba znika z aktywnej obsady. Na zamówieniu z pulą per osoba
                pozostałe MD przepadają.
              </span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-3">
            <input
              type="radio"
              name="offboarding-action"
              value="transfer"
              checked={action === "transfer"}
              onChange={() => setAction("transfer")}
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium text-foreground">
                Przelicz na innego konsultanta
              </span>
              <span className="block text-xs text-muted-foreground">
                Wskaż osobę z tego zamówienia albo nową osobę ze szkiców klienta.
              </span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-3">
            <input
              type="radio"
              name="offboarding-action"
              value="restore"
              checked={action === "restore"}
              onChange={() => setAction("restore")}
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium text-foreground">
                Przywróć jako aktywne
              </span>
              <span className="block text-xs text-muted-foreground">
                Współpraca trwa dalej. Osoba wraca na aktywną obsadę, pula MD
                zostaje nienaruszona, a zakończony kontrakt wraca do aktywnych.
              </span>
            </span>
          </label>
        </fieldset>

        {action === "transfer" ? (
          <div className="flex flex-col gap-4">
            <div>
              <label
                htmlFor="offboarding-recipient"
                className="mb-1 block text-xs font-semibold text-muted-foreground"
              >
                Konsultant przejmujący *
              </label>
              <select
                id="offboarding-recipient"
                value={targetKey}
                onChange={(event) => {
                  setTargetKey(event.target.value);
                  setMethod(null);
                  const person = newPeople.find(
                    (item) => `contract:${item.contract_id}` === event.target.value,
                  );
                  const suggestion = person
                    ? contractCostRatePerMd(person.rate_candidate, person.rate_unit)
                    : null;
                  setTerms((current) => ({
                    ...current,
                    method: null,
                    rateCost: suggestion ? String(suggestion.value) : "",
                    rateRevenue: "",
                  }));
                }}
                className={inputClass}
              >
                <option value="">Wybierz konsultanta</option>
                {recipients.length > 0 ? (
                  <optgroup label="Na tym zamówieniu">
                    {recipients.map((recipient) => (
                      <option key={recipient.id} value={`line:${recipient.id}`}>
                        {recipient.consultant_name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {!sharedPool && onTakeover && newPeople.length > 0 ? (
                  <optgroup label="Nowe osoby u klienta">
                    {newPeople.map((person) => (
                      <option
                        key={person.contract_id}
                        value={`contract:${person.contract_id}`}
                      >
                        {person.candidate_name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </select>
              {recipients.length === 0 && newPeople.length === 0 ? (
                <p role="status" className="mt-1 text-xs text-destructive">
                  Brak innego aktywnego konsultanta w tym zamówieniu.
                </p>
              ) : null}
            </div>

            {targetLine && !sharedPool ? (
              <MdTransferChoice
                name="offboarding-method"
                preview={existingPreview}
                incomingName={targetLine.consultant_name}
                departingName={line?.consultant_name ?? ""}
                value={method}
                onChange={setMethod}
              />
            ) : null}

            {targetPerson && departingForTakeover ? (
              <TakeoverTermsFields
                idPrefix="offboarding-takeover"
                departing={departingForTakeover}
                incomingName={targetPerson.candidate_name}
                value={terms}
                onChange={setTerms}
                costNote={costSuggestion?.note ?? null}
              />
            ) : null}
          </div>
        ) : null}

        {action === "restore" ? (
          <div>
            <label
              htmlFor="offboarding-restore-end"
              className="mb-1 block text-xs font-semibold text-muted-foreground"
            >
              Współpraca trwa do{restoreEndRequired ? " *" : ""}
            </label>
            <input
              id="offboarding-restore-end"
              type="date"
              value={restoreEndDate}
              max={groupEndDate ?? undefined}
              onChange={(event) => setRestoreEndDate(event.target.value)}
              className={inputClass}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              {restoreEndRequired
                ? `Zamówienie kończy się ${formatDate(groupEndDate)} — linia nie może trwać dłużej.`
                : "Puste = bezterminowo. Zamówienie nie ma daty zakończenia."}
            </p>
            {restoreEndTooLate ? (
              <p role="alert" className="mt-1 text-xs text-destructive">
                Data wykracza poza zamówienie.
              </p>
            ) : null}
            {restoreEndRequired && restoreEndDate === "" ? (
              <p role="alert" className="mt-1 text-xs text-destructive">
                Podaj datę — to zamówienie ma swój koniec, więc linia nie może
                być bezterminowa.
              </p>
            ) : null}
          </div>
        ) : null}

        {offboardingCase?.uses_shared_md_pool && action !== "restore" ? (
          <p
            role="status"
            className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-foreground"
          >
            To zamówienie ma wspólną pulę MD. Decyzja usuwa odchodzącą osobę z
            aktywnej obsady, ale wspólna pula pozostaje bez zmian — nie jest
            pomniejszana ani przypisywana do konsultanta.
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
