"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import {
  CONTRACT_TERMINATION_REASONS,
  contractEquipmentApi,
  contractsApi,
  type AgreementTerminationMode,
  type AgreementTerminationParty,
  type ContractTerminationReason,
} from "@/lib/api";
import { AppModal } from "@/components/ds/AppModal";
import { apiErrorMessage } from "@/lib/api-error";
import {
  AGREEMENT_PLANS,
  AGREEMENT_TERMINATION_MODES,
  AGREEMENT_TERMINATION_PARTIES,
  agreementTerminationPayload,
  attachmentDocType,
  defaultNonCompetePlan,
  emptyTerminationForm,
  missingTerminationFields,
  signedOnLabel,
  suggestedLastDay,
  terminationFormError,
  terminationWarnings,
  type AgreementPlan,
  type TerminationFormState,
} from "@/lib/contract-termination";
import { warsawToday } from "@/lib/warsaw-date";
import { documentsHref } from "@/lib/b2b-documents";
import {
  useContractEquipmentRegister,
  useCreateReturnTask,
} from "@/lib/api/equipment";
import { assignmentLabel } from "@/components/equipment/equipment-format";

interface Props {
  /** Jedna umowa = „Zakończ współpracę"; kilka = „Oznacz zakończone" w rejestrze. */
  contractIds: number[];
  /** Zbiorcze „Oznacz zakończone" — także przy jednym zaznaczonym wierszu. */
  bulk?: boolean;
  candidateName?: string | null;
  /** Podpowiedź daty zakończenia projektu (np. wpisana w formularzu edycji). */
  defaultDate?: string;
  /** Okres wypowiedzenia z umowy — podpowiedź „Ostatniego dnia umowy".
   *  Pominięty przy jednej umowie = dialog czyta go sam z kontraktu. */
  noticePeriodMonths?: number | null;
  /** Koniec zamówienia u klienta — ostrzeżenie, gdy projekt wykracza poza nie.
   *  Pominięty przy jednej umowie = dialog czyta go sam z kontraktu. */
  orderEndDate?: string | null;
  onClose: () => void;
  onSuccess: (result: { changed: number }) => void;
}

const FIELD =
  "mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950";

/**
 * „Zakończ współpracę" — JEDYNA droga do statusu „Zakończony" (ticket 09.2026).
 *
 * Otwierają je: lista statusu na karcie kontraktu, formularz edycji,
 * „Zakończ wcześniej" w aneksach, „Zakończ współpracę" na karcie kontraktora
 * (profil klienta, lista kontraktorów) i zbiorcze „Oznacz zakończone" w rejestrze
 * (jedno wspólne okno, dane stosowane do każdej zaznaczonej umowy). Backend
 * odmawia 409 `termination_required` statusowi „Zakończony" bez tego okna.
 *
 * Powłoka to `AppModal` (Radix): `role="dialog"`, focus trap, Escape.
 * „Anuluj"/„×" zamyka bez zmian — zapis dopiero po „Zakończ" z kompletem pól.
 */
export function ContractTerminationDialog({
  contractIds,
  bulk: bulkProp,
  candidateName,
  defaultDate,
  noticePeriodMonths: noticePeriodProp,
  orderEndDate: orderEndProp,
  onClose,
  onSuccess,
}: Props) {
  const qc = useQueryClient();
  const router = useRouter();
  const bulk = bulkProp ?? contractIds.length > 1;
  // Karta kontraktora i lista kontraktorów nie niosą okresu wypowiedzenia ani
  // końca zamówienia — dialog doczytuje je z kontraktu (ten sam klucz co karta
  // kontraktu, więc tam nie ma drugiego zapytania).
  // Runda 10 (F27): przy jednej umowie dialog czyta ZAWSZE kontrakt — data
  // startu blokuje koniec projektu przed nią (ten sam klucz co karta
  // kontraktu, więc tam nie ma drugiego zapytania).
  const needsContract = !bulk;
  const contractQuery = useQuery<{
    notice_period_months?: number | null;
    client_order_end_date?: string | null;
    start_date?: string | null;
    client_name?: string | null;
  }>({
    queryKey: ["contract", contractIds[0]],
    queryFn: () => contractsApi.get(contractIds[0]).then((r) => r.data),
    enabled: needsContract,
  });
  const noticePeriodMonths =
    noticePeriodProp !== undefined
      ? noticePeriodProp
      : contractQuery.data?.notice_period_months ?? null;
  const orderEndDate =
    orderEndProp !== undefined
      ? orderEndProp
      : contractQuery.data?.client_order_end_date ?? null;
  const [form, setForm] = useState<TerminationFormState>(() =>
    emptyTerminationForm({
      // Pojedyncza umowa: podpowiedź jak dotąd. Zbiorczo oba pola startują
      // puste — domyślny powód/data oznaczyłyby N umów wartością, której nikt
      // nie wybrał.
      reason: bulk ? "" : "project_ended",
      projectEndDate: bulk ? defaultDate || "" : defaultDate || warsawToday(),
    }),
  );
  // Ręcznie poprawiony „Ostatni dzień umowy" nie jest nadpisywany podpowiedzią.
  const [lastDayTouched, setLastDayTouched] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  // „Zwrot sprzętu” (moduł „Sprzęt”, „Ludzie w NEXUSIE”): co konsultant ma
  // oddać i zadanie odbioru dla recepcji. Wyłączony moduł (404) i brak
  // uprawnień (403) chowają sekcję — zakończenie działa jak dotąd.
  const equipmentRegister = useContractEquipmentRegister(contractIds[0], !bulk);
  const manualEquipment = useQuery({
    queryKey: ["contract-equipment", contractIds[0]],
    queryFn: () => contractEquipmentApi.list(contractIds[0]).then((r) => r.data),
    enabled: !bulk,
    retry: false,
  });
  const createReturnTask = useCreateReturnTask();
  const [planReturn, setPlanReturn] = useState(true);
  const [returnTaskError, setReturnTaskError] = useState<string | null>(null);
  const registerActive = equipmentRegister.data?.active ?? [];
  const manualPending = (manualEquipment.data ?? []).filter(
    (row) =>
      row.return_status === "pending" &&
      (row as { assignment_id?: number | null }).assignment_id == null,
  );
  const hasEquipmentToReturn = registerActive.length + manualPending.length > 0;
  const canPlanReturn = !bulk && equipmentRegister.isSuccess && hasEquipmentToReturn;

  const set = (patch: Partial<TerminationFormState>) =>
    setForm((prev) => {
      const next = { ...prev, ...patch };
      if ("reason" in patch && !next.nonCompeteTouched) {
        next.nonCompete = defaultNonCompetePlan(next.reason);
      }
      if (!lastDayTouched && ("signedOn" in patch || "mode" in patch)) {
        next.lastDay =
          next.mode === "notice"
            ? suggestedLastDay(next.signedOn, noticePeriodMonths) ?? ""
            : "";
      }
      return next;
    });

  const invalidate = () => {
    for (const id of contractIds) {
      qc.invalidateQueries({ queryKey: ["contract", id] });
      qc.invalidateQueries({ queryKey: ["contract-activities", id] });
      qc.invalidateQueries({ queryKey: ["contract-documents", id] });
      qc.invalidateQueries({ queryKey: ["contract-docs", id] });
    }
    // Rejestr (`staleTime` 30 s) i panel „Kończące się" (5 min) — bez tego
    // zakończony kontrakt dalej wisiał jako aktywny w oknie 30 dni.
    qc.invalidateQueries({ queryKey: ["contracts-v2"] });
    qc.invalidateQueries({ queryKey: ["client-register"] });
    qc.invalidateQueries({ queryKey: ["contracts-expiring-v2"] });
    qc.invalidateQueries({ queryKey: ["contractors-v2"] });
    qc.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
    // Profil klienta (kafle MRR, Konsultanci) i zamówienia — terminacja je
    // przycina. Prefiksem: zamontowany profil jest najwyżej jeden.
    qc.invalidateQueries({ queryKey: ["client-profile"] });
    qc.invalidateQueries({ queryKey: ["dl-orders-grouped"] });
    // Generator umów B2B — umowa zmienia zakładkę.
    qc.invalidateQueries({ queryKey: ["b2b-generated"] });
  };

  const mut = useMutation({
    mutationFn: async () => {
      const agreement = agreementTerminationPayload(form);
      const reason = form.reason as ContractTerminationReason;
      let count = contractIds.length;
      if (bulk) {
        const { data } = await contractsApi.bulkMarkEnded(contractIds, {
          termination_reason: reason,
          terminated_at: form.projectEndDate,
          termination_lessons: form.lessons.trim() || null,
          agreement_termination: agreement,
        });
        count = data.changed;
      } else {
        await contractsApi.terminate(contractIds[0], {
          termination_reason: reason,
          termination_lessons: form.lessons.trim() || null,
          terminated_at: form.projectEndDate,
          agreement_termination: agreement,
        });
      }
      // Zadanie odbioru sprzętu dla recepcji — jak załącznik: zakończenie jest
      // już zapisane, więc błąd tylko się pokazuje.
      let returnError: string | null = null;
      if (canPlanReturn && planReturn) {
        try {
          await createReturnTask.mutateAsync(contractIds[0]);
        } catch (error: unknown) {
          returnError = apiErrorMessage(
            error,
            "Nie udało się założyć zadania odbioru sprzętu.",
          );
        }
      }
      // Załącznik osobnym żądaniem — zakończenie jest już zapisane, więc
      // padnięty upload nie może go cofnąć ani udawać, że nic się nie stało.
      let uploadError: string | null = null;
      if (agreement && file) {
        for (const id of contractIds) {
          const body = new FormData();
          body.append("file", file);
          body.append("doc_type", attachmentDocType(agreement.mode));
          try {
            await contractsApi.uploadDocument(id, body);
          } catch (error: unknown) {
            uploadError = apiErrorMessage(error, "Nie udało się dodać załącznika.");
          }
        }
      }
      return { count, uploadError, returnError };
    },
    onSuccess: ({ count, uploadError, returnError }) => {
      invalidate();
      if (uploadError || returnError) {
        setChanged(count);
        setAttachmentError(uploadError);
        setReturnTaskError(returnError);
        return;
      }
      onSuccess({ changed: count });
      if (preparesAgreement) router.push(agreementHref);
    },
  });

  const clientName = contractQuery.data?.client_name ?? null;
  // „Przygotuj porozumienie”: zakończenie zapisuje się jak dotąd (umowa
  // czeka w „Umowach bez projektu”), a podpis porozumienia w generatorze
  // zamyka ją z datą rozwiązania — kolejność „najpierw koniec, potem dokument”
  // obsługuje `effects.apply` (projekt już zakończony = kontrakt bez zmian).
  const preparesAgreement = !bulk && form.agreementPlan === "prepare";
  const agreementHref = documentsHref({
    newType: "termination_agreement",
    contractId: contractIds[0],
    values: {
      termination_date: form.projectEndDate,
      last_service_date: form.projectEndDate,
      release_non_compete: form.nonCompete === "release",
      non_compete_client_name: form.nonCompete === "release" ? clientName ?? "" : "",
    },
  });
  const choosePlan = (plan: AgreementPlan) => {
    setLastDayTouched(false);
    setFile(null);
    setForm((prev) => ({
      ...prev,
      agreementPlan: plan,
      agreementTerminated: plan === "done",
      mode: "",
      party: "",
      signedOn: "",
      lastDay: "",
    }));
  };
  const missing = missingTerminationFields(form, { requirePlan: !bulk });
  const contractStart = bulk ? null : contractQuery.data?.start_date ?? null;
  const blocking = terminationFormError(form, contractStart);
  const warnings = terminationWarnings(form, orderEndDate);
  const ready = missing.length === 0 && !blocking;
  const formId = `contract-termination-${contractIds.join("-")}`;
  const hint =
    form.mode === "notice" && !noticePeriodMonths
      ? "Umowa nie ma zapisanego okresu wypowiedzenia — wpisz datę ręcznie."
      : "Koniec okresu wypowiedzenia lub dzień wskazany w porozumieniu";

  const agreementFields = (
            <div className="space-y-3 pl-6">
              <fieldset>
                <legend className="text-xs text-muted-foreground">Tryb *</legend>
                <div className="mt-1 flex flex-wrap gap-4">
                  {AGREEMENT_TERMINATION_MODES.map((m) => (
                    <label key={m.value} className="flex items-center gap-1.5 text-sm">
                      <input
                        type="radio"
                        name={`${formId}-mode`}
                        value={m.value}
                        checked={form.mode === m.value}
                        onChange={() =>
                          set({ mode: m.value as AgreementTerminationMode })
                        }
                      />
                      {m.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend className="text-xs text-muted-foreground">
                  Strona * (kto wypowiedział albo zainicjował porozumienie)
                </legend>
                <div className="mt-1 flex flex-wrap gap-4">
                  {AGREEMENT_TERMINATION_PARTIES.map((p) => (
                    <label key={p.value} className="flex items-center gap-1.5 text-sm">
                      <input
                        type="radio"
                        name={`${formId}-party`}
                        value={p.value}
                        checked={form.party === p.value}
                        onChange={() =>
                          set({ party: p.value as AgreementTerminationParty })
                        }
                      />
                      {p.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="block">
                <span className="text-xs text-muted-foreground">
                  {signedOnLabel(form.mode)} *
                </span>
                <input
                  type="date"
                  value={form.signedOn}
                  onChange={(e) => set({ signedOn: e.target.value })}
                  className={FIELD}
                />
              </label>
              <label className="block">
                <span className="text-xs text-muted-foreground">
                  Ostatni dzień umowy *
                </span>
                <input
                  type="date"
                  value={form.lastDay}
                  onChange={(e) => {
                    setLastDayTouched(true);
                    setForm((prev) => ({ ...prev, lastDay: e.target.value }));
                  }}
                  className={FIELD}
                />
                <span className="mt-1 block text-xs text-muted-foreground">
                  {hint}
                </span>
              </label>
              <label className="block">
                <span className="text-xs text-muted-foreground">
                  Załącznik (wypowiedzenie albo porozumienie — PDF, obraz)
                </span>
                <input
                  type="file"
                  accept="application/pdf,image/*"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="mt-1 block w-full text-sm"
                />
              </label>
            </div>
  );

  if (attachmentError || returnTaskError) {
    return (
      <AppModal
        open
        onOpenChange={(next) => {
          if (!next) onSuccess({ changed });
        }}
        title="Zakończenie zapisane"
        footer={
          <button
            type="button"
            onClick={() => onSuccess({ changed })}
            className="text-sm bg-primary text-primary-foreground rounded-md px-4 py-2"
          >
            Zamknij
          </button>
        }
      >
        {attachmentError ? (
          <p role="alert" className="text-sm text-destructive">
            Zakończenie współpracy jest zapisane, ale załącznik nie trafił do
            dokumentów kontraktu: {attachmentError} Dodaj go w zakładce „Dokumenty".
          </p>
        ) : null}
        {returnTaskError ? (
          <p role="alert" className="text-sm text-destructive">
            Zakończenie współpracy jest zapisane, ale recepcja nie dostała
            zadania odbioru sprzętu: {returnTaskError} Daj znać recepcji, że
            sprzęt jest do odebrania.
          </p>
        ) : null}
      </AppModal>
    );
  }

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Zakończ współpracę"
      description={
        bulk
          ? `Dane zostaną zapisane na ${contractIds.length} zaznaczonych kontraktach.`
          : candidateName
            ? `Konsultant: ${candidateName}`
            : undefined
      }
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={mut.isPending}
            className="text-sm text-muted-foreground hover:underline disabled:opacity-50"
          >
            Anuluj
          </button>
          <button
            type="submit"
            form={formId}
            disabled={!ready || mut.isPending}
            title={missing.length ? `Uzupełnij: ${missing.join(", ")}` : undefined}
            className="text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md px-4 py-2"
          >
            {mut.isPending
              ? "Zapisywanie…"
              : preparesAgreement
                ? "Zakończ i przygotuj porozumienie"
                : "Zakończ"}
          </button>
        </>
      }
    >
      <form
        id={formId}
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!ready) return;
          mut.mutate();
        }}
      >
        <label className="block">
          <span className="text-xs text-muted-foreground">Powód zakończenia *</span>
          <select
            value={form.reason}
            required
            onChange={(e) =>
              set({ reason: e.target.value as ContractTerminationReason | "" })
            }
            className={FIELD}
          >
            <option value="">— wybierz powód —</option>
            {CONTRACT_TERMINATION_REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">
            Data zakończenia projektu *
          </span>
          <input
            type="date"
            value={form.projectEndDate}
            required
            min={contractStart ?? undefined}
            onChange={(e) => set({ projectEndDate: e.target.value })}
            className={FIELD}
          />
          <span className="mt-1 block text-xs text-muted-foreground">
            Ostatni dzień pracy konsultanta na zamówieniu. Do tego dnia kontrakt
            jest „Kończący się”, od następnego — „Zakończony”.
          </span>
        </label>

        {!bulk && (
          <fieldset
            className="rounded-md border border-border p-3 space-y-2"
            data-tour="contract.end.b2b-question"
          >
            <legend className="px-1 text-sm font-medium">Co z umową B2B? *</legend>
            {AGREEMENT_PLANS.map((plan) => (
              <div key={plan.value}>
                <label className="flex items-start gap-2">
                  <input
                    type="radio"
                    name={`${formId}-plan`}
                    value={plan.value}
                    checked={form.agreementPlan === plan.value}
                    onChange={() => choosePlan(plan.value)}
                    className="mt-1"
                  />
                  <span className="text-sm">
                    {plan.label}
                    {plan.value === "prepare" && (
                      <span className="ml-1.5 rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
                        zalecane
                      </span>
                    )}
                    <span className="block text-xs text-muted-foreground">{plan.hint}</span>
                  </span>
                </label>
                {plan.value === "prepare" && form.agreementPlan === "prepare" && (
                  <fieldset className="mt-2 ml-6 space-y-1">
                    <legend className="text-xs text-muted-foreground">
                      Zakaz konkurencji w porozumieniu *
                    </legend>
                    {(
                      [
                        ["keep", "Zostaje — jak w umowie"],
                        [
                          "release",
                          `Zdejmujemy — Partner może przejść bezpośrednio do ${
                            clientName ?? "klienta"
                          }`,
                        ],
                      ] as const
                    ).map(([value, label]) => (
                      <label key={value} className="flex items-center gap-1.5 text-sm">
                        <input
                          type="radio"
                          name={`${formId}-noncompete`}
                          value={value}
                          checked={form.nonCompete === value}
                          onChange={() =>
                            setForm((prev) => ({
                              ...prev,
                              nonCompete: value,
                              nonCompeteTouched: true,
                            }))
                          }
                        />
                        {label}
                      </label>
                    ))}
                  </fieldset>
                )}
                {plan.value === "done" && form.agreementTerminated && agreementFields}
              </div>
            ))}
          </fieldset>
        )}

        {bulk && (
        <div className="rounded-md border border-border p-3 space-y-3">
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={form.agreementTerminated}
              onChange={(e) => {
                // Odznaczenie zdejmuje dodatkowe pola i ich wartości.
                setLastDayTouched(false);
                setFile(null);
                setForm((prev) => ({
                  ...prev,
                  agreementTerminated: e.target.checked,
                  mode: "",
                  party: "",
                  signedOn: "",
                  lastDay: "",
                }));
              }}
              className="mt-0.5"
            />
            <span className="text-sm">
              <span className="font-medium">Rozwiązanie umowy</span>
              <span className="block text-xs text-muted-foreground">
                Umowa B2B została wypowiedziana lub rozwiązana za porozumieniem
              </span>
            </span>
          </label>

          {form.agreementTerminated && agreementFields}
        </div>
        )}

        {/* Sekcja modułu „Sprzęt” — bez rejestru (moduł wyłączony, 404) jej nie ma. */}
        {canPlanReturn ? (
          <div className="rounded-md border border-border p-3 space-y-2">
            <p className="text-sm font-medium">Zwrot sprzętu</p>
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {registerActive.map((row) => (
                <li key={`r-${row.assignment_id}`}>
                  {assignmentLabel(row)}
                  {row.ownership === "klienta" ? " · zwrot do klienta" : ""}
                </li>
              ))}
              {manualPending.map((row) => (
                <li key={`m-${row.id}`}>
                  {row.brand_model || "Sprzęt"}
                  {row.serial_number ? ` · ${row.serial_number}` : ""}
                  {row.owner === "client" ? " · sprzęt klienta" : ""}
                </li>
              ))}
            </ul>
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={planReturn}
                onChange={(e) => setPlanReturn(e.target.checked)}
                className="mt-0.5"
              />
              <span className="text-sm">
                Załóż recepcji zadanie odbioru sprzętu na dzień zakończenia
              </span>
            </label>
          </div>
        ) : null}

        <label className="block">
          <span className="text-xs text-muted-foreground">
            Kto zdecydował i dlaczego / wnioski (TAC only)
          </span>
          <textarea
            value={form.lessons}
            onChange={(e) => set({ lessons: e.target.value })}
            className={FIELD}
            rows={4}
            placeholder={
              bulk
                ? "Puste pole nie kasuje wniosków zapisanych wcześniej na kontraktach."
                : "Np.: Klient — brak budżetu. Klient poprosił o konsultanta na 6 mies., potrzebowali 12 — zbadać wcześniej…"
            }
          />
        </label>

        {warnings.length > 0 && (
          <ul className="space-y-1" aria-label="Ostrzeżenia">
            {warnings.map((w) => (
              <li
                key={w}
                className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200"
              >
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {w}
              </li>
            ))}
          </ul>
        )}
        {blocking && (
          <p role="alert" className="text-xs text-destructive">
            {blocking}
          </p>
        )}
        {mut.isError && (
          <p role="alert" className="text-xs text-destructive">
            {apiErrorMessage(mut.error, "Błąd zapisu. Spróbuj ponownie.")}
          </p>
        )}
      </form>
    </AppModal>
  );
}
