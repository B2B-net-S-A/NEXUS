"use client";

// „Dla kogo jest aneks?” — jedno wyszukiwanie zamiast przycisku „Umowa spoza
// Nexusa” (13.10.2026). Wynik niesie umowy z rejestru i kontrakty bez umowy
// w rejestrze, więc człowiek nie musi wiedzieć z góry, czy umowa jest
// w NEXUSIE, i nie wybierze „spoza Nexusa” dla umowy, która w nim jest.
// Każdy aneks ma kontrakt; wyjątek („Tej osoby nie ma w kontraktach NEXUSA”)
// zapisuje aneks przy kliencie i odkłada podpis do powiązania.
// Kontrakty to dane Delivery: serwer pokazuje je tylko osobie z prawem edycji
// kontraktów. Reszta wybiera umowę z rejestru albo zapisuje aneks „Bez
// kontraktu” — i teksty nie twierdzą wtedy, że kontraktu nie ma.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { ClientSinglePicker } from "@/components/clients/ClientSinglePicker";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/lib/api-error";
import {
  b2bDocumentsApi,
  b2bDocumentsKeys,
  type DocumentSubject,
  type DocumentSubjectContract,
  type DocumentTypeDef,
} from "@/lib/api/b2bDocuments";
import { formatIsoDatePl } from "@/lib/date-pl";
import { contractStatusLabel } from "@/lib/status-labels";
import { canManageOrderLifecycle, useAuthStore } from "@/store/auth";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

/** Wybór podmiotu aneksu — część stanu kreatora, którą ustawia ten krok. */
export interface AnnexSubjectChoice {
  parentId: number | null;
  parentLabel: string | null;
  contractId: number | null;
  contractLabel: string | null;
  /** Umowa z rejestru ma kilka kontraktów do wyboru i żaden nie jest wskazany. */
  needsContractPick: boolean;
  /** Świadomy wybór „osoby nie ma w kontraktach” — aneks przy kliencie. */
  withoutContract: boolean;
  clientId: number | null;
  clientName: string | null;
}

export const EMPTY_ANNEX_CHOICE: AnnexSubjectChoice = {
  parentId: null,
  parentLabel: null,
  contractId: null,
  contractLabel: null,
  needsContractPick: false,
  withoutContract: false,
  clientId: null,
  clientName: null,
};

/** Czy z takim wyborem można przejść do treści aneksu. */
export function annexChoiceReady(
  type: Pick<DocumentTypeDef, "allows_external" | "parent">,
  choice: AnnexSubjectChoice,
): boolean {
  if (choice.parentId !== null) return !choice.needsContractPick;
  if (!takesContract(type)) return false;
  if (choice.contractId !== null) return true;
  return choice.withoutContract && choice.clientId !== null;
}

/** Typy, które można wystawić do kontraktu bez umowy w rejestrze. */
export function takesContract(
  type: Pick<DocumentTypeDef, "allows_external" | "parent">,
): boolean {
  return type.allows_external || type.parent === "mandate";
}

/** „Kontrakt #651 · aktywny · od 06.07.2026”; `named: false` pomija numer,
 *  gdy pozycja ma go już w tytule. */
function contractLine(
  contract: DocumentSubjectContract | DocumentSubject,
  named = true,
): string {
  const status =
    "status" in contract ? contract.status : (contract.contract_status ?? "");
  const start =
    "start_date" in contract ? contract.start_date : contract.contract_start_date;
  return [
    named ? `Kontrakt #${contract.contract_id}` : "",
    contractStatusLabel(status).toLocaleLowerCase("pl"),
    start ? `od ${formatIsoDatePl(start)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Wybór z pozycji wyszukiwania (także dla wejścia z modułu Kontrakty). */
export function choiceFromSubject(
  subject: DocumentSubject,
  contractId: number | null = null,
): AnnexSubjectChoice {
  const who = subject.person_name || subject.partner_name || "";
  if (subject.kind === "agreement") {
    const options = subject.contract_options;
    const picked =
      subject.contract_id ??
      contractId ??
      (options.length === 1 ? options[0].contract_id : null);
    return {
      ...EMPTY_ANNEX_CHOICE,
      parentId: subject.parent_generated_contract_id,
      parentLabel: [subject.contract_number, who].filter(Boolean).join(" — "),
      contractId: picked,
      contractLabel: picked ? `Kontrakt #${picked}` : null,
      needsContractPick: picked === null && options.length > 1,
    };
  }
  return {
    ...EMPTY_ANNEX_CHOICE,
    contractId: subject.contract_id,
    contractLabel: [`Kontrakt #${subject.contract_id}`, who]
      .filter(Boolean)
      .join(" — "),
  };
}

export function AnnexSubjectPicker({
  type,
  choice,
  onChoice,
  initialQuery = "",
}: {
  type: DocumentTypeDef;
  choice: AnnexSubjectChoice;
  onChoice: (next: AnnexSubjectChoice) => void;
  /** Fraza startowa (harness pokazuje wynik bez wpisywania). */
  initialQuery?: string;
}) {
  const [query, setQuery] = useState(initialQuery);
  const q = useDebouncedValue(query, 300).trim();
  const enabled = q.length >= 2;
  const found = useQuery({
    queryKey: b2bDocumentsKeys.subjects(type.key, q),
    queryFn: () => b2bDocumentsApi.subjects({ documentType: type.key, q }),
    enabled,
    staleTime: 10_000,
  });
  const canGoWithoutContract = takesContract(type);
  // Lustro bramki serwera (`_binds_contracts`): edycja kontraktów + zapis
  // w sekcji Delivery.
  const seesContracts = canManageOrderLifecycle(useAuthStore((s) => s.user));

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="b2b-annex-subject-search">Dla kogo jest aneks?</Label>
        <div className="relative">
          <Search
            className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            id="b2b-annex-subject-search"
            className="w-full pl-8"
            placeholder="Imię i nazwisko, firma, NIP albo numer umowy"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {!enabled ? (
        <p className="text-sm text-muted-foreground">
          {seesContracts
            ? "Wpisz co najmniej dwa znaki — pokażemy umowy i kontrakty tej osoby."
            : "Wpisz co najmniej dwa znaki — pokażemy umowy tej osoby z rejestru."}
        </p>
      ) : found.isPending ? (
        <p className="text-sm text-muted-foreground">Szukam…</p>
      ) : found.isError ? (
        <Alert
          variant="error"
          title="Nie udało się przeszukać umów i kontraktów"
          description={apiErrorMessage(found.error, "Spróbuj ponownie.")}
        >
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => void found.refetch()}
          >
            Ponów
          </Button>
        </Alert>
      ) : found.isSuccess && found.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {seesContracts
            ? "Nie znaleźliśmy umowy ani kontraktu pasującego do wyszukiwania."
            : "Nie znaleźliśmy umowy pasującej do wyszukiwania."}
        </p>
      ) : (
        <ul className="max-h-80 space-y-2 overflow-y-auto">
          {(found.data ?? []).map((subject) => (
            <li
              key={
                subject.kind === "agreement"
                  ? `u-${subject.parent_generated_contract_id}`
                  : `k-${subject.contract_id}`
              }
            >
              <SubjectOption
                subject={subject}
                mandate={type.parent === "mandate"}
                choice={choice}
                onChoice={onChoice}
              />
            </li>
          ))}
        </ul>
      )}

      {canGoWithoutContract ? (
        <div className="space-y-2 border-t border-border pt-3">
          <Button
            variant={choice.withoutContract ? "primary" : "outline"}
            size="sm"
            aria-pressed={choice.withoutContract}
            onClick={() =>
              onChoice({ ...EMPTY_ANNEX_CHOICE, withoutContract: true })
            }
          >
            {seesContracts
              ? "Tej osoby nie ma w kontraktach NEXUSA"
              : "Umowy tej osoby nie ma w rejestrze"}
          </Button>
          <p className="text-xs text-muted-foreground">
            {seesContracts
              ? "Aneks trafi do rejestru z oznaczeniem „Bez kontraktu”. Powiążesz go, gdy kontrakt powstanie — do tego czasu nie da się go oznaczyć jako podpisany."
              : "Aneks trafi do rejestru z oznaczeniem „Bez kontraktu”. Z kontraktem powiąże go osoba prowadząca kontrakty — do tego czasu nie da się go oznaczyć jako podpisany."}
          </p>
          {choice.withoutContract ? (
            <div className="max-w-sm space-y-1">
              <Label>Klient, którego dotyczy aneks</Label>
              <ClientSinglePicker
                queryKey="b2b-annex-subject-clients"
                value={
                  choice.clientId !== null
                    ? { id: choice.clientId, name: choice.clientName ?? "" }
                    : null
                }
                onChange={(client) =>
                  onChoice({
                    ...choice,
                    clientId: client?.id ?? null,
                    clientName: client?.name ?? null,
                  })
                }
                selectableOnly
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SubjectOption({
  subject,
  mandate,
  choice,
  onChoice,
}: {
  subject: DocumentSubject;
  mandate: boolean;
  choice: AnnexSubjectChoice;
  onChoice: (next: AnnexSubjectChoice) => void;
}) {
  const agreement = subject.kind === "agreement";
  const chosen = agreement
    ? choice.parentId === subject.parent_generated_contract_id
    : choice.parentId === null && choice.contractId === subject.contract_id;
  const who = [subject.person_name, subject.client_name].filter(Boolean).join(" · ");
  const options = agreement ? subject.contract_options : [];

  return (
    <div
      className={cn(
        "rounded-lg border bg-card",
        chosen ? "border-primary bg-primary/5" : "border-border",
      )}
    >
      <button
        type="button"
        aria-pressed={chosen}
        onClick={() => onChoice(choiceFromSubject(subject))}
        className="flex w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left text-sm hover:bg-muted"
      >
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-foreground">
            {agreement
              ? `Umowa ${subject.contract_number ?? "bez numeru"}`
              : `Kontrakt #${subject.contract_id}`}
          </span>
          <Badge variant={agreement ? "neutral" : "warning"}>
            {agreement
              ? subject.source === "excel"
                ? "z Excela działu"
                : "z rejestru"
              : mandate
                ? "umowa zlecenie"
                : "umowa spoza Nexusa"}
          </Badge>
        </span>
        <span className="text-xs text-muted-foreground">{who || "—"}</span>
        <span className="text-xs text-muted-foreground">
          {subject.contract_id !== null
            ? contractLine(subject, agreement)
            : options.length === 1
              ? `${contractLine(options[0])} — zostanie powiązany z umową`
              : options.length > 1
                ? "Kilka trwających kontraktów — wskaż właściwy"
                : "Umowa bez powiązanego kontraktu — podpis zmieni tylko rejestr umów"}
        </span>
      </button>
      {chosen && options.length > 1 ? (
        <fieldset className="space-y-1 border-t border-border px-3 py-2">
          <legend className="text-xs font-medium text-foreground">
            Kontrakt tej umowy
          </legend>
          {options.map((option) => (
            <label
              key={option.contract_id}
              className="flex items-center gap-2 text-sm text-foreground"
            >
              <input
                type="radio"
                name={`annex-contract-${subject.parent_generated_contract_id}`}
                checked={choice.contractId === option.contract_id}
                onChange={() =>
                  onChoice(choiceFromSubject(subject, option.contract_id))
                }
              />
              {contractLine(option)}
            </label>
          ))}
        </fieldset>
      ) : null}
    </div>
  );
}
