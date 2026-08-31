"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";

import { AppModal } from "@/components/ds";
import type {
  OrderGroupRead,
  OrderLineRead,
  OrderOffboardingRateBasis,
  OrderOffboardingResolutionInput,
} from "@/lib/api/orderGroups";
import { formatDate } from "@/types/client-profile";

import { formatMd } from "./MdBudgetBar";

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
}: Props) {
  const [action, setAction] = useState<"remove" | "transfer" | "restore">(
    "remove",
  );
  const [targetOrderId, setTargetOrderId] = useState("");
  const [rateBasis, setRateBasis] =
    useState<OrderOffboardingRateBasis>("departing");
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
    setTargetOrderId("");
    setRateBasis("departing");
    // Podpowiedź = koniec zamówienia. Operator może ją skrócić; nie może jej
    // wydłużyć poza zamówienie (walidacja niżej i po stronie serwera).
    setRestoreEndDate(group?.end_date ?? "");
  }, [open, offboardingCase?.id, group?.end_date]);

  const restoreEndTooLate =
    groupEndDate !== null &&
    restoreEndDate !== "" &&
    restoreEndDate > groupEndDate;

  const canSubmit =
    !submitting &&
    offboardingCase?.status === "pending" &&
    (action === "remove" ||
      (action === "transfer" && targetOrderId !== "") ||
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
    onSubmit({
      action: "transfer",
      target_order_id: Number(targetOrderId),
      rate_basis: rateBasis,
      expected_version: offboardingCase.version,
    });
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
                Wskaż aktywną osobę z tego samego zamówienia i podstawę stawki.
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
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="offboarding-recipient"
                className="mb-1 block text-xs font-semibold text-muted-foreground"
              >
                Konsultant przejmujący *
              </label>
              <select
                id="offboarding-recipient"
                value={targetOrderId}
                onChange={(event) => setTargetOrderId(event.target.value)}
                className={inputClass}
              >
                <option value="">Wybierz konsultanta</option>
                {recipients.map((recipient) => (
                  <option key={recipient.id} value={recipient.id}>
                    {recipient.consultant_name}
                  </option>
                ))}
              </select>
              {recipients.length === 0 ? (
                <p role="status" className="mt-1 text-xs text-destructive">
                  Brak innego aktywnego konsultanta w tym zamówieniu.
                </p>
              ) : null}
            </div>

            <div>
              <label
                htmlFor="offboarding-rate-basis"
                className="mb-1 block text-xs font-semibold text-muted-foreground"
              >
                Przelicz po stawce *
              </label>
              <select
                id="offboarding-rate-basis"
                value={rateBasis}
                onChange={(event) =>
                  setRateBasis(event.target.value as OrderOffboardingRateBasis)
                }
                className={inputClass}
              >
                <option value="departing">osoby odchodzącej</option>
                <option value="recipient">osoby przejmującej</option>
              </select>
            </div>
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
