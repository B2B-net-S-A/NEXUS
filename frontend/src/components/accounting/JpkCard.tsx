"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  jpkFilePath,
  useJpk,
  useMarkJpkSent,
  usePrepareJpk,
  useSetJpkContact,
  type JpkFile,
  type JpkOverview,
} from "@/lib/api/accounting-vat";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "./AccountingShell";
import { datePl, gr, MONTHS_PL } from "./ledger-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const NOTE = "px-3.5 py-2.5 text-[13px] text-muted-foreground";

/** Kwota deklaracji (pełne złote) jak reszta ekranu: „1 173,00 zł”. */
function zl(value: number | null | undefined): string {
  return `${gr((value ?? 0) * 100)} zł`;
}

/** Saldo wersji: do wpłaty (P_51) albo nadwyżka do przeniesienia (P_62). */
export function jpkBalance(file: Pick<JpkFile, "totals">): string | null {
  const totals = file.totals;
  if (!totals) return null;
  return (totals.P_51 ?? 0) > 0 ? `do wpłaty ${zl(totals.P_51)}` : `do przeniesienia ${zl(totals.P_62)}`;
}

/**
 * JPK_V7M miesiąca z nagłówka (K5b): wersje pliku (złożenie, potem korekty),
 * przygotowanie z walidacją schematem MF, pobranie XML i oznaczenie „wysłany”
 * (z numerem UPO). Plik zawiera faktury osób zespołu — przygotowuje i pobiera go
 * osoba z Płacami (D2), reszta widzi tylko stan wersji.
 */
export function JpkCard({ year, month, blockers = [] }: { year: number; month: number; blockers?: readonly string[] }) {
  const overview = useJpk(year, month);
  if (overview.isError) {
    return (
      <SectionCard title="JPK_V7M">
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => overview.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!overview.isSuccess) return null;
  const data = overview.data;
  return (
    <SectionCard title={`JPK_V7M za ${MONTHS_PL[month - 1]?.toLowerCase() ?? month} ${year}`} aside="ewidencja z deklaracją · termin 25.">
      {data.missing.length ? (
        <p className="border-b border-border/70 px-3.5 py-2 text-[13px] text-warning-muted-foreground">
          Do JPK brakuje: {data.missing.join("; ")}.
        </p>
      ) : null}
      {data.stale ? (
        <p className="border-b border-border/70 px-3.5 py-2 text-[13px] text-destructive-text">
          {data.stale === "surplus"
            ? "Wysłany JPK jest nieaktualny: korekta JPK za poprzedni miesiąc zmieniła nadwyżkę (P_39) — przygotuj korektę."
            : "Wysłany JPK jest nieaktualny: rejestr VAT zmienił się po wysłaniu — przygotuj korektę."}
        </p>
      ) : null}
      <FilesTable data={data} />
      {data.can_prepare ? (
        <PrepareForm data={data} blockers={blockers} />
      ) : !data.can_download ? (
        <p className={NOTE}>Plik zawiera faktury osób zespołu — przygotowuje i pobiera go osoba z Płacami.</p>
      ) : null}
      {data.can_edit_contact ? <ContactForm data={data} /> : null}
      {data.notes.length ? (
        <ul className="space-y-0.5 border-t border-border/70 px-3.5 py-2 text-[12px] text-muted-foreground">
          {data.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  );
}

function FilesTable({ data }: { data: JpkOverview }) {
  const { showToast } = useToast();
  const markSent = useMarkJpkSent();
  const [sending, setSending] = useState<number | null>(null);
  const [note, setNote] = useState("");
  if (!data.files.length) {
    return <p className={NOTE}>Za ten miesiąc nie ma jeszcze pliku JPK.</p>;
  }
  const anySent = data.files.some((file) => file.status === "sent");
  // Wysłaną bramką MF można oznaczyć także starszą wersję (pozostałe niewysłane
  // staną się unieważnione) — byle nie było nowszej wysłanej, a złożenie nie po
  // wysłanym JPK.
  const markable = (file: JpkFile) =>
    file.status === "prepared" &&
    !data.files.some((other) => other.version > file.version && other.status === "sent") &&
    !(file.purpose === "submission" && anySent);
  const download = async (file: JpkFile) => {
    try {
      await downloadAuthenticatedFile(jpkFilePath(file.id), `JPK_V7M_${data.year}-${String(data.month).padStart(2, "0")}_v${file.version}.xml`);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się pobrać pliku JPK."), "error");
    }
  };
  const send = (file: JpkFile) =>
    markSent.mutate(
      { id: file.id, note: note.trim() },
      {
        onSuccess: () => {
          setSending(null);
          setNote("");
          showToast(`JPK v${file.version} oznaczony jako wysłany.`);
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się oznaczyć wysłania."), "error"),
      },
    );
  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-border/70">
          <th className={cn(CALM_HEAD, "w-[16%] px-3.5 py-2 text-left")}>Wersja</th>
          <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Stan</th>
          {data.can_download ? <th className={cn(CALM_HEAD, "w-[24%] px-2 py-2 text-right")}>Deklaracja</th> : null}
          <th className={cn(CALM_HEAD, "w-[30%] py-2 pl-2 pr-3.5 text-right")} aria-label="Akcje" />
        </tr>
      </thead>
      <tbody>
        {data.files.map((file) => (
          <tr key={file.id} className={cn(CALM_ROW, "last:border-0")}>
            <td className="px-3.5 py-1.5">
              <span className="font-medium">v{file.version}</span>
              <span className={CALM_SUBLINE}>{file.purpose === "correction" ? "korekta" : "złożenie"}</span>
            </td>
            <td className="min-w-0 px-2 py-1.5 text-[13px]">
              {file.status === "sent" ? (
                <span className="text-success-muted-foreground">wysłany {datePl(file.sent_at?.slice(0, 10))}</span>
              ) : file.status === "void" ? (
                <span className="text-muted-foreground">unieważniony (wysłano inną wersję)</span>
              ) : (
                <span>przygotowany {datePl(file.created_at?.slice(0, 10))}</span>
              )}
              {file.sent_note ? <span className={cn(CALM_SUBLINE, "block truncate")}>{file.sent_note}</span> : null}
            </td>
            {data.can_download ? (
              <td className="px-2 py-1.5 text-right text-[13px] tabular-nums">{jpkBalance(file)}</td>
            ) : null}
            <td className="py-1.5 pl-2 pr-3.5 text-right">
              <div className="flex flex-wrap items-center justify-end gap-1.5">
                {data.can_download ? (
                  <Button size="sm" variant="outline" onClick={() => download(file)}>
                    Pobierz XML
                  </Button>
                ) : null}
                {data.can_mark_sent && markable(file) ? (
                  sending === file.id ? (
                    <form
                      className="flex items-center gap-1.5"
                      onSubmit={(event) => {
                        event.preventDefault();
                        send(file);
                      }}
                    >
                      <input
                        className={cn(CONTROL, "w-40")}
                        aria-label="Numer UPO"
                        placeholder="numer UPO"
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                      />
                      <Button size="sm" type="submit" loading={markSent.isPending}>
                        Wysłany
                      </Button>
                    </form>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => setSending(file.id)}>
                      Oznacz jako wysłany
                    </Button>
                  )
                ) : null}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PrepareForm({ data, blockers }: { data: JpkOverview; blockers: readonly string[] }) {
  const { showToast } = useToast();
  const prepare = usePrepareJpk();
  const [reason, setReason] = useState("");
  const [surplus, setSurplus] = useState(data.surplus_value != null ? String(data.surplus_value) : "");
  const correction = data.purpose === "correction";
  const surplusValue = surplus.trim() === "" ? null : Number(surplus);
  const ready =
    !data.missing.length &&
    !blockers.length &&
    (!data.needs_opening_surplus || (surplusValue != null && Number.isInteger(surplusValue) && surplusValue >= 0)) &&
    (!correction || reason.trim().length >= 3);
  const run = () =>
    prepare.mutate(
      {
        year: data.year,
        month: data.month,
        ...(correction ? { reason: reason.trim() } : {}),
        ...(data.surplus_editable && surplusValue != null ? { opening_surplus: surplusValue } : {}),
      },
      {
        onSuccess: (result) => {
          setReason("");
          const warnings = result.warnings.length ? ` Do sprawdzenia: ${result.warnings.join("; ")}.` : "";
          showToast(`JPK v${result.file.version} przygotowany i zgodny ze schematem MF.${warnings}`);
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się przygotować JPK."), "error"),
      },
    );
  return (
    <form
      className="flex flex-wrap items-end gap-2.5 border-t border-border/70 px-3.5 py-2.5 text-[13px]"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) run();
      }}
    >
      {data.surplus_editable ? (
        <label className="flex flex-col gap-1">
          <span className="text-muted-foreground">Nadwyżka z poprzedniej deklaracji (P_62, zł)</span>
          <input
            className={cn(CONTROL, "w-44 tabular-nums")}
            inputMode="numeric"
            aria-label="Nadwyżka z poprzedniej deklaracji"
            value={surplus}
            onChange={(event) => setSurplus(event.target.value.replace(/[^\d]/g, ""))}
            placeholder="0, gdy jej nie było"
          />
        </label>
      ) : null}
      {correction ? (
        <label className="flex min-w-[16rem] flex-1 flex-col gap-1">
          <span className="text-muted-foreground">Uzasadnienie korekty (P_ORDZU)</span>
          <input
            className={cn(CONTROL, "w-full")}
            aria-label="Uzasadnienie korekty"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      ) : null}
      <Button size="sm" type="submit" disabled={!ready} loading={prepare.isPending}>
        {correction ? "Przygotuj korektę JPK" : "Przygotuj JPK"}
      </Button>
      {blockers.length ? (
        <p className="basis-full text-[12px] text-warning-muted-foreground">
          JPK powstanie po zamknięciu listy „Do sprawdzenia”: {blockers.join("; ")}.
        </p>
      ) : null}
    </form>
  );
}

function ContactForm({ data }: { data: JpkOverview }) {
  const { showToast } = useToast();
  const save = useSetJpkContact();
  const [email, setEmail] = useState(data.contact.email);
  const [phone, setPhone] = useState(data.contact.phone);
  const changed = email.trim() !== data.contact.email || phone.trim() !== data.contact.phone;
  return (
    <form
      className="flex flex-wrap items-end gap-2.5 border-t border-border/70 px-3.5 py-2.5 text-[13px]"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(
          { email: email.trim(), phone: phone.trim() },
          {
            onSuccess: () => showToast("Zapisano kontakt w JPK."),
            onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać kontaktu."), "error"),
          },
        );
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground">E-mail w JPK</span>
        <input className={cn(CONTROL, "w-56")} aria-label="E-mail w JPK" value={email} onChange={(event) => setEmail(event.target.value)} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground">Telefon (opcjonalnie)</span>
        <input className={cn(CONTROL, "w-40")} aria-label="Telefon w JPK" value={phone} onChange={(event) => setPhone(event.target.value)} />
      </label>
      <Button size="sm" variant="outline" type="submit" disabled={!changed || !email.trim()} loading={save.isPending}>
        Zapisz kontakt
      </Button>
    </form>
  );
}
