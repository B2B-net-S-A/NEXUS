"use client";

// Dane firm z umów — do potwierdzenia (E5a, 0755, decyzja Artura 22.11.2026).
// Model czyta podpisaną umowę aktywnego kontraktu B2B bez danych firmy
// w Generatorze; tu człowiek sprawdza propozycję z cytatem, poprawia ją,
// sprawdza w rejestrze i zatwierdza. Do profilu kandydata trafiają tylko puste
// pola, chyba że zaznaczy „Nadpisz dane wpisane w profilu”.

import { useState } from "react";
import Link from "next/link";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { AlertTriangle, FileText, ShieldCheck } from "lucide-react";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  applyPartnerRead,
  dismissPartnerRead,
  fetchPartnerReads,
  verifyPartnerRead,
  type CandidateChangeAction,
  type PartnerFieldName,
  type PartnerRead,
  type PartnerReadState,
  type PartnerReadValues,
} from "@/lib/api/contractPartnerReads";
import { apiErrorMessage } from "@/lib/api-error";
import { openAuthenticatedFile } from "@/lib/authenticated-files";
import { cn } from "@/lib/utils";

const PAGE = 20;

export const FIELD_LABELS: Record<PartnerFieldName, string> = {
  gender: "Forma w umowie",
  partner_name: "Imię i nazwisko",
  partner_legal_name: "Firma",
  partner_entity_type: "Rodzaj podmiotu",
  partner_nip: "NIP",
  partner_regon: "REGON",
  partner_business_address: "Adres działalności / siedziby",
  partner_correspondence_address: "Adres do korespondencji",
  partner_email: "E-mail",
  partner_phone: "Telefon",
  partner_krs: "KRS",
  partner_seat: "Siedziba",
  partner_registry_court: "Sąd rejestrowy",
  partner_share_capital: "Kapitał zakładowy",
  partner_representative_name: "Reprezentant",
  partner_representative_function: "Funkcja reprezentanta",
  partner_representation: "Reprezentacja",
};

const CHOICES: Partial<Record<PartnerFieldName, Record<string, string>>> = {
  gender: { m: "Pan", k: "Pani" },
  partner_entity_type: {
    sole_trader: "Jednoosobowa działalność",
    company: "Spółka",
  },
};

const COLUMN_LABELS: Record<string, string> = {
  legal_name: "firma",
  nip: "NIP",
  regon: "REGON",
  business_address: "adres",
  email: "e-mail",
  phone: "telefon",
};

const CHANGE_LABELS: Partial<Record<CandidateChangeAction, string>> = {
  written: "zapisano w profilu",
  same: "profil miał tę samą wartość",
  kept: "zostawiono wartość z profilu",
  taken: "pominięto — ten e-mail ma inna osoba",
};

const CONTACT_COLUMNS = new Set(["email", "phone"]);

const STATES: { value: PartnerReadState; label: string }[] = [
  { value: "open", label: "Do potwierdzenia" },
  { value: "failed", label: "Nieudane" },
  { value: "applied", label: "Zastosowane" },
  { value: "dismissed", label: "Odrzucone" },
];

function shown(name: PartnerFieldName, value: string | null): string {
  if (value === null || value === "") return "—";
  return CHOICES[name]?.[value] ?? value;
}

function dayPl(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function FieldInput({
  name,
  value,
  onChange,
}: {
  name: PartnerFieldName;
  value: string;
  onChange: (value: string) => void;
}) {
  const choices = CHOICES[name];
  const label = `${FIELD_LABELS[name]} — poprawka`;
  if (choices) {
    return (
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 w-full rounded-md border border-border bg-card px-2 text-[13px] text-foreground focus:border-primary focus:outline-hidden"
      >
        <option value="">— brak w umowie</option>
        {Object.entries(choices).map(([key, text]) => (
          <option key={key} value={key}>
            {text}
          </option>
        ))}
      </select>
    );
  }
  return (
    <Input
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 text-[13px]"
    />
  );
}

function ReadCard({ item }: { item: PartnerRead }) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const original = Object.fromEntries(
    item.fields.map((f) => [f.name, f.value ?? ""]),
  ) as Record<PartnerFieldName, string>;
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState<Record<PartnerFieldName, string>>(original);
  const [overwrite, setOverwrite] = useState(false);
  const open = item.status === "read" && item.decision === null;

  const corrections = (): PartnerReadValues =>
    Object.fromEntries(
      (Object.keys(edits) as PartnerFieldName[])
        .filter((name) => edits[name] !== original[name])
        .map((name) => [name, edits[name]]),
    );
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["contract-partner-reads"] });
  const onError = (fallback: string) => (error: unknown) =>
    showError(apiErrorMessage(error, fallback));

  const apply = useMutation({
    mutationFn: () =>
      applyPartnerRead(item.id, { overwrite, values: corrections() }),
    onSuccess: () => {
      showSuccess("Dane firmy potwierdzone.");
      refresh();
    },
    onError: onError("Nie udało się zastosować danych firmy."),
  });
  const dismiss = useMutation({
    mutationFn: () => dismissPartnerRead(item.id),
    onSuccess: () => {
      showSuccess("Odczyt odrzucony.");
      refresh();
    },
    onError: onError("Nie udało się odrzucić odczytu."),
  });
  const verify = useMutation({
    mutationFn: () => verifyPartnerRead(item.id, corrections()),
    onSuccess: refresh,
    onError: onError("Nie udało się sprawdzić firmy w rejestrze."),
  });
  const busy = apply.isPending || dismiss.isPending || verify.isPending;

  // E-mail i telefon trafiają tylko w puste pole, więc „Nadpisz” ich nie liczy.
  const conflicts = item.fields.filter(
    (f) =>
      f.column &&
      !CONTACT_COLUMNS.has(f.column) &&
      f.current &&
      f.value &&
      f.current !== f.value,
  );
  const confirmed = item.confirmed;
  const rows = item.fields.filter(
    (f) =>
      editing ||
      f.value ||
      f.current ||
      f.quote ||
      item.confirmed?.fields[f.name],
  );
  // Uwaga o rodzaju dokumentu idzie pierwsza (backend wstawia ją na początek).
  const issues = item.issues;

  const runApply = async () => {
    if (overwrite) {
      const ok = await askConfirm({
        title: "Nadpisać dane firmy w profilu kandydata?",
        description:
          "Firma, NIP, REGON i adres z umowy zastąpią wartości wpisane w profilu. E-mail i telefon zostają bez zmian.",
        confirmLabel: "Nadpisz i zastosuj",
      });
      if (!ok) return;
    }
    apply.mutate();
  };
  const openFile = () =>
    openAuthenticatedFile(
      `/api/contracts/${item.contract_id}/documents/${item.document_id}/download`,
      null,
      item.filename ?? "umowa",
    ).catch(onError("Nie udało się otworzyć pliku umowy."));

  return (
    <section
      aria-label={`Dane firmy: ${item.candidate_name ?? "kontraktor"}`}
      className="rounded-lg border border-border bg-card"
    >
      {confirmDialog}
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border/60 px-4 py-2">
        {item.candidate_id ? (
          <Link
            href={`/candidates/${item.candidate_id}`}
            className="text-sm font-semibold text-foreground hover:text-primary hover:underline"
          >
            {item.candidate_name ?? "Kandydat"}
          </Link>
        ) : (
          <span className="text-sm font-semibold text-foreground">
            Kontrakt bez kandydata
          </span>
        )}
        <span className="text-[12px] text-muted-foreground">
          {item.client_name ?? "—"}
        </span>
        <button
          type="button"
          onClick={openFile}
          className="inline-flex items-center gap-1 text-[12px] text-muted-foreground underline-offset-2 hover:text-primary hover:underline"
        >
          <FileText className="h-3.5 w-3.5" aria-hidden="true" />
          {item.filename ?? "plik umowy"}
        </button>
        {item.agreement_number ? (
          <span className="text-[12px] text-muted-foreground">
            nr {item.agreement_number}
          </span>
        ) : null}
        <Link
          href={`/contracts/${item.contract_id}`}
          className="text-[12px] text-muted-foreground underline-offset-2 hover:text-primary hover:underline"
        >
          kontrakt
        </Link>
        <span className="ml-auto text-[11px] text-muted-foreground">
          odczyt AI {dayPl(item.read_at)}
        </span>
      </header>

      {item.status !== "read" ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">
          Odczyt tej umowy się nie udał (skan nieczytelny, plik bez treści albo
          awaria modelu). Uzupełnij dane firmy w profilu kandydata.
        </p>
      ) : (
        <div className="space-y-3 px-4 py-3">
          {issues.length ? (
            <ul className="space-y-0.5 rounded-md bg-warning-muted/60 px-3 py-2 text-[12px] text-warning-muted-foreground">
              {issues.map((issue) => (
                <li key={`${issue.field}-${issue.message}`} className="flex gap-1.5">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span>
                    {issue.field in FIELD_LABELS
                      ? `${FIELD_LABELS[issue.field as PartnerFieldName]}: `
                      : ""}
                    {issue.message}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          <table className="w-full table-fixed text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="w-28 py-1 pr-3 font-medium sm:w-44">Pole</th>
                <th className="py-1 pr-3 font-medium">Z umowy</th>
                <th className="w-24 py-1 font-medium sm:w-56">W profilu kandydata</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((field) => (
                <tr key={field.name} className="border-t border-border/60 align-top">
                  <td className="py-1.5 pr-3 text-muted-foreground">
                    {FIELD_LABELS[field.name]}
                  </td>
                  <td className="min-w-0 py-1.5 pr-3">
                    {editing && open ? (
                      <FieldInput
                        name={field.name}
                        value={edits[field.name]}
                        onChange={(value) =>
                          setEdits((prev) => ({ ...prev, [field.name]: value }))
                        }
                      />
                    ) : confirmed ? (
                      <span className="font-medium text-foreground [overflow-wrap:anywhere]">
                        {shown(field.name, confirmed.fields[field.name] ?? null)}
                        {confirmed.corrected.includes(field.name) ? (
                          <span className="ml-1.5 text-[11px] font-normal text-muted-foreground">
                            (poprawione)
                          </span>
                        ) : null}
                      </span>
                    ) : (
                      <span className="font-medium text-foreground [overflow-wrap:anywhere]">
                        {shown(field.name, field.value)}
                      </span>
                    )}
                    {field.quote ? (
                      <q
                        className={cn(
                          "mt-0.5 block text-[11px] leading-snug [overflow-wrap:anywhere]",
                          field.quote_found === false
                            ? "text-warning-muted-foreground"
                            : "text-muted-foreground",
                        )}
                      >
                        {field.quote}
                      </q>
                    ) : null}
                  </td>
                  <td className="py-1.5 text-muted-foreground [overflow-wrap:anywhere]">
                    {field.column ? (field.current ?? "puste") : "tylko nowa umowa"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {item.verification ? (
            <Verification
              item={item}
              canUse={open}
              onUse={(name, value) => {
                setEditing(true);
                setEdits((prev) => ({ ...prev, [name]: value }));
              }}
            />
          ) : null}

          {item.decision === "applied" && item.candidate_changes ? (
            <p className="text-[12px] text-muted-foreground">
              {Object.entries(item.candidate_changes)
                .filter(([, change]) => CHANGE_LABELS[change.action])
                .map(
                  ([column, change]) =>
                    `${COLUMN_LABELS[column] ?? column}: ${CHANGE_LABELS[change.action]}`,
                )
                .join(" · ")}
            </p>
          ) : null}

          {open ? (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button size="sm" disabled={busy} onClick={runApply}>
                Zastosuj
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => setEditing((v) => !v)}
              >
                {editing ? "Koniec poprawek" : "Popraw dane"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="gap-1"
                disabled={busy}
                onClick={() => verify.mutate()}
              >
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                {verify.isPending ? "Sprawdzam…" : "Sprawdź w rejestrze"}
              </Button>
              <Button
                size="sm"
                variant="quiet"
                disabled={busy}
                onClick={() => dismiss.mutate()}
              >
                Odrzuć
              </Button>
              {conflicts.length ? (
                <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
                  <Checkbox
                    checked={overwrite}
                    onCheckedChange={(v) => setOverwrite(v === true)}
                    aria-label="Nadpisz dane wpisane w profilu"
                  />
                  Nadpisz dane wpisane w profilu ({conflicts.length})
                </label>
              ) : null}
            </div>
          ) : null}
          {open ? (
            <p className="text-[11px] text-muted-foreground">
              „Zastosuj” wpisuje firmę, NIP, REGON, adres, e-mail i telefon tylko
              w puste pola profilu. Wszystkie pola zostają też jako potwierdzone
              dane do nowej umowy.
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}

function Verification({
  item,
  canUse,
  onUse,
}: {
  item: PartnerRead;
  canUse: boolean;
  onUse: (name: PartnerFieldName, value: string) => void;
}) {
  const v = item.verification!;
  const registry = v.registry === "krs" ? "KRS" : v.registry === "ceidg" ? "CEIDG" : "rejestr";
  return (
    <div className="rounded-md border border-border/60 px-3 py-2 text-[12px]">
      <p className="font-medium text-foreground">
        {v.status === "verified"
          ? `Sprawdzono w ${registry} ${dayPl(v.checked_at)}`
          : (v.message ?? "Rejestr nie potwierdził firmy.")}
      </p>
      {v.warnings.map((w) => (
        <p key={w.code ?? w.message} className="text-destructive">
          {w.message}
        </p>
      ))}
      {v.comparison.length ? (
        <ul className="mt-1 space-y-0.5">
          {v.comparison.map((row) => (
            <li key={row.field} className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-muted-foreground">{FIELD_LABELS[row.field]}:</span>
              <span className={row.same ? "text-foreground" : "text-warning-muted-foreground"}>
                {row.same
                  ? "zgodne z rejestrem"
                  : `w rejestrze „${shown(row.field, row.registry)}”`}
              </span>
              {!row.same && canUse ? (
                <button
                  type="button"
                  onClick={() => onUse(row.field, row.registry)}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  Weź z rejestru
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function PartnerReadsList() {
  const [state, setState] = useState<PartnerReadState>("open");
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ["contract-partner-reads", state, offset],
    queryFn: () => fetchPartnerReads(state, offset, PAGE),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
  const counts = query.data?.counts;

  return (
    <div className="space-y-3">
      <header className="space-y-1">
        <h1 className="text-[22px] font-semibold leading-7 tracking-tight text-foreground">
          Dane firm z umów — do potwierdzenia
        </h1>
        <p className="max-w-3xl text-[13px] text-muted-foreground">
          NEXUS czyta podpisaną umowę aktywnych kontraktów B2B, które nie mają
          danych firmy w Generatorze. Sprawdź propozycję z cytatem, popraw ją
          albo sprawdź w rejestrze i zastosuj — dane posłużą do nowej umowy.
        </p>
        {counts ? (
          <p className="text-[12px] text-muted-foreground">
            Kontrakty bez danych firmy: {counts.eligible} · czeka na odczyt:{" "}
            {counts.to_read} · bez pliku umowy w Dokumentach: {counts.without_file}
          </p>
        ) : null}
      </header>
      <SegmentedRadio<PartnerReadState>
        label="Stan odczytu"
        size="sm"
        value={state}
        onChange={(next) => {
          setState(next);
          setOffset(0);
        }}
        options={STATES.map((s) => ({
          value: s.value,
          label: counts ? `${s.label} (${counts[s.value]})` : s.label,
        }))}
      />
      {query.isError ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się pobrać danych firm z umów. Odczyty mogą czekać — spróbuj ponownie."
          onRetry={() => query.refetch()}
        />
      ) : !query.isSuccess ? (
        <p className="text-[13px] text-muted-foreground">Ładowanie…</p>
      ) : query.data.items.length === 0 ? (
        <p role="status" className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-[13px] text-muted-foreground">
          {state === "open" ? "Nic do potwierdzenia." : "Brak odczytów w tym stanie."}
        </p>
      ) : (
        <div className="space-y-3">
          {query.data.items.map((item) => (
            <ReadCard key={item.id} item={item} />
          ))}
          {query.data.total > PAGE ? (
            <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
              <Button
                size="sm"
                variant="outline"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Poprzednie
              </Button>
              <span>
                {offset + 1}–{Math.min(offset + PAGE, query.data.total)} z{" "}
                {query.data.total}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={offset + PAGE >= query.data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Następne
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
