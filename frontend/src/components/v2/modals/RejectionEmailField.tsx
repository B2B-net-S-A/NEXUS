"use client";

/**
 * Mail odrzucenia w oknie odrzucenia — checkbox i podgląd (13.10.2026).
 *
 * Decyzje Artura D1–D6: okno pokazuje adresata, temat i treść, zanim ktoś
 * potwierdzi. Przy jednej osobie temat i treść da się poprawić (wysyłamy
 * dokładnie ten tekst, serwer robi escape), przy kilku podgląd jest tylko do
 * odczytu z listą, kto dostanie mail. Brak skrzynki, adresu albo uprawnień
 * widać od razu — checkbox jest wtedy wyłączony.
 *
 * 17.10.2026 (D1–D8): mail od „Zweryfikowany” w górę, z treścią „przed
 * klientem” albo „po kliencie”. Osoba, która jest jeszcze w innych
 * rekrutacjach, dostaje zamiast zakończenia dopisek „To dotyczy tylko tej
 * rekrutacji — nadal bierzesz udział w…” — serwer liczy listę w chwili
 * wysyłki, więc dopisek stoi obok pola, nie w nim. Bez skrzynki Microsoft 365
 * okno daje „Podłącz skrzynkę” i po powrocie sprawdza jeszcze raz.
 *
 * Podgląd: `POST /api/rejection-emails/preview` (ta sama reguła co planowanie
 * wysyłki w `rejection_email_scheduler`).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Mail, PenLine } from "lucide-react";

import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_COLUMN_LABEL, type BoardColumnKey } from "@/lib/board-stages";
import {
  REJECTION_EMAIL_TEXT_KIND_LABEL,
  rejectionEmailBlockedMessage,
  rejectionEmailDefaultBody,
  rejectionEmailPreviewKey,
  rejectionEmailSkipShort,
  type RejectionEmailOtherProcess,
  type RejectionEmailPreview,
  type RejectionEmailPreviewSample,
  type RejectionEmailText,
  type RejectionEmailTextKind,
} from "@/lib/rejection-email";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

export interface RejectionEmailPeople {
  jobId: number;
  people: { candidateId: number; name: string }[];
}

/** Co okno odrzucenia musi wiedzieć przy „Potwierdź”. */
export interface RejectionEmailFieldState {
  /** Mail nie wyjdzie do nikogo — checkbox wyłączony. */
  blocked: boolean;
  /** Zaznaczony mail z pustym tematem albo treścią — „Potwierdź” czeka. */
  invalid: boolean;
  /** Poprawki z okna (jedna osoba); `null` = wszystko domyślnie. */
  text: RejectionEmailText | null;
}

interface Props {
  /** `null` — wołający nie podał rekrutacji i osób: sam checkbox, bez podglądu. */
  preview: RejectionEmailPeople | null;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  onStateChange: (state: RejectionEmailFieldState) => void;
}

interface Draft {
  subject: string;
  body: string;
}

const SETTINGS_INTEGRATIONS = "/settings?tab=integracje";

const KIND_TAB_LABEL: Record<RejectionEmailTextKind, string> = {
  before_client: "Przed klientem",
  after_client: "Po kliencie",
};

function columnLabel(column: string): string {
  return BOARD_COLUMN_LABEL[column as BoardColumnKey] ?? column;
}

/** „Java Tech Lead · Rozmowa u klienta”; bez nazwy dla kandydata — dopisek. */
function otherProcessLine(process: RejectionEmailOtherProcess): string {
  const where = `${process.title} · ${columnLabel(process.column)}`;
  return process.mail_title ? where : `${where} (w mailu bez nazwy)`;
}

function KindBadge({ kind }: { kind: RejectionEmailTextKind | null | undefined }) {
  if (!kind) return null;
  return (
    <Badge variant="outline" size="sm">
      Treść: {REJECTION_EMAIL_TEXT_KIND_LABEL[kind]}
    </Badge>
  );
}

/** Dopisek liczony przez serwer w chwili wysyłki — poza polem edycji. */
function OtherProcessesNote({ text }: { text: string }) {
  return (
    <div
      className="space-y-1.5 rounded-md border border-dashed border-border bg-muted px-3 py-2"
      data-testid="rejection-email-other-processes"
    >
      <p className="whitespace-pre-wrap text-sm">{text}</p>
      <p className="border-t border-border pt-1.5 text-xs text-muted-foreground">
        Dopisek tworzy NEXUS. Lista sprawdzana w chwili wysyłki — jeśli osoba
        w tym czasie odpadnie z którejś rekrutacji, ta zniknie z maila.
      </p>
    </div>
  );
}

export function RejectionEmailField({
  preview,
  checked,
  onCheckedChange,
  onStateChange,
}: Props) {
  const ids = useMemo(
    () => (preview?.people ?? []).map((p) => p.candidateId),
    [preview]
  );
  const single = ids.length === 1;
  const query = useQuery({
    queryKey: rejectionEmailPreviewKey(preview?.jobId ?? 0, ids),
    queryFn: () =>
      api
        .post<RejectionEmailPreview>("/api/rejection-emails/preview", {
          job_id: preview?.jobId,
          candidate_ids: ids,
        })
        .then((r) => r.data),
    enabled: preview !== null && ids.length > 0,
    staleTime: 0,
    // Po „Podłącz skrzynkę” (nowa karta) okno sprawdza jeszcze raz po powrocie.
    refetchOnWindowFocus: true,
    // Awaria podglądu nie blokuje odrzucenia (mail wyjdzie z treścią
    // domyślną) — od razu to mówimy, zamiast ponawiać w tle.
    retry: false,
  });
  const data = query.isSuccess ? query.data : null;

  const people = data?.people ?? [];
  const eligible = people.filter((p) => !p.skip_reason);
  const blockedReason = (() => {
    if (!data || people.length === 0 || eligible.length > 0) return null;
    const reasons = new Set(people.map((p) => p.skip_reason ?? ""));
    return reasons.size === 1 ? [...reasons][0] : "";
  })();
  const blockedMessage =
    blockedReason === null
      ? null
      : blockedReason
        ? rejectionEmailBlockedMessage(blockedReason)
        : "Mail nie wyjdzie do nikogo z zaznaczonych osób.";
  const blocked = blockedMessage !== null;

  const others = single ? (eligible[0]?.other_processes ?? []) : [];
  const [appendOthers, setAppendOthers] = useState(true);
  const withOthers = others.length > 0 && appendOthers;

  const defaults: Draft | null =
    data?.subject != null && data?.body != null
      ? {
          subject: data.subject,
          body: rejectionEmailDefaultBody(data.body, data.closing, withOthers),
        }
      : null;
  const [draft, setDraft] = useState<Draft | null>(null);
  useEffect(() => {
    if (defaults && draft === null) setDraft(defaults);
    // Szkic startuje z treści domyślnej raz — kolejne odświeżenia zapytania
    // nie nadpisują tego, co ktoś już poprawił.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults?.subject, defaults?.body]);

  const editDraft = single && defaults !== null ? draft : null;
  const edited =
    editDraft !== null &&
    defaults !== null &&
    (editDraft.subject !== defaults.subject || editDraft.body !== defaults.body);
  const subjectEmpty = editDraft !== null && editDraft.subject.trim() === "";
  const bodyEmpty = editDraft !== null && editDraft.body.trim() === "";
  const invalid = checked && (subjectEmpty || bodyEmpty);

  // Zmiana dopisku zmienia treść domyślną (zakończenie znika albo wraca) —
  // nietknięte pole idzie za nią, poprawionego nie ruszamy.
  const toggleOthers = (next: boolean) => {
    if (data?.body != null && editDraft !== null && !edited) {
      setDraft({
        subject: editDraft.subject,
        body: rejectionEmailDefaultBody(data.body, data.closing, others.length > 0 && next),
      });
    }
    setAppendOthers(next);
  };

  useEffect(() => {
    if (blocked && checked) onCheckedChange(false);
  }, [blocked, checked, onCheckedChange]);

  const othersOff = others.length > 0 && !appendOthers;
  useEffect(() => {
    const text: RejectionEmailText = {};
    if (edited && editDraft) {
      text.subject = editDraft.subject;
      text.body = editDraft.body;
    }
    if (othersOff) text.otherProcesses = false;
    onStateChange({
      blocked,
      invalid,
      text: Object.keys(text).length > 0 ? text : null,
    });
  }, [blocked, invalid, edited, editDraft, othersOff, onStateChange]);

  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (checked) boxRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [checked, data]);

  const label = single || preview === null
    ? "Powiadomienie e-mail do kandydata"
    : "Powiadomienie e-mail do kandydatów";
  const nameOf = (candidateId: number | undefined) =>
    preview?.people.find((p) => p.candidateId === candidateId)?.name ?? null;
  const firstName = nameOf(eligible[0]?.candidate_id);
  const shortName = firstName?.split(" ")[0] ?? "osoby";

  // Starszy serwer (albo atrapa) bez `samples` — jedna treść z pól głównych.
  const samples: RejectionEmailPreviewSample[] = data?.samples?.length
    ? data.samples
    : data?.subject != null && data?.body != null
      ? [
          {
            text_kind: data.text_kind ?? "after_client",
            candidate_id: eligible[0]?.candidate_id ?? 0,
            subject: data.subject,
            body: data.body,
            closing: data.closing ?? "",
            other_processes_text: data.other_processes_text ?? null,
          },
        ]
      : [];
  const [sampleKind, setSampleKind] = useState<RejectionEmailTextKind | null>(null);
  const sample =
    samples.find((s) => s.text_kind === sampleKind) ?? samples[0] ?? null;
  const kindCount = (kind: RejectionEmailTextKind) =>
    eligible.filter((p) => p.text_kind === kind).length;
  const withOthersCount = eligible.filter((p) => (p.other_processes?.length ?? 0) > 0).length;

  return (
    <FormField label={label}>
      <label
        className={`flex items-start gap-2 text-sm rounded-md p-1.5 ${
          blocked ? "text-muted-foreground" : "cursor-pointer hover:bg-primary/10"
        }`}
      >
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))] text-primary focus:ring-primary"
          checked={checked && !blocked}
          disabled={blocked}
          onChange={(e) => onCheckedChange(e.target.checked)}
        />
        <span className="flex items-start gap-1.5">
          <Mail className="mt-0.5 h-3.5 w-3.5 text-[hsl(var(--muted-foreground))] shrink-0" />
          <span>
            {single || preview === null
              ? "Wyślij e-mail do kandydata 15 minut po potwierdzeniu."
              : "Wyślij e-mail 15 minut po potwierdzeniu."}{" "}
            Do tego czasu można cofnąć wysyłkę.
          </span>
        </span>
      </label>

      {blockedMessage ? (
        <Alert variant="warning" description={blockedMessage} className="mt-1 py-2">
          {blockedReason === "no_mailbox" ? (
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <a
                href={SETTINGS_INTEGRATIONS}
                target="_blank"
                rel="noopener"
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
              >
                Podłącz skrzynkę
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </a>
              <span className="text-xs">
                Otworzy Ustawienia → Integracje w nowej karcie. Wróć tutaj — okno
                sprawdzi to jeszcze raz.
              </span>
            </div>
          ) : null}
        </Alert>
      ) : null}

      {checked && !blocked && preview !== null ? (
        <div ref={boxRef} className="mt-1" data-testid="rejection-email-preview">
          {query.isPending ? (
            <p className="px-1.5 text-xs text-muted-foreground">Wczytuję podgląd maila…</p>
          ) : query.isError ? (
            <Alert
              variant="error"
              className="py-2"
              description={`${apiErrorMessage(
                query.error,
                "Nie udało się wczytać podglądu maila."
              )} Mail wyjdzie z treścią domyślną.`}
            />
          ) : editDraft && defaults ? (
            <div className="rounded-lg border border-primary/30">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-t-lg border-b border-border bg-primary/5 px-3 py-1.5">
                <span className="text-xs font-semibold uppercase tracking-[0.06em] text-primary">
                  Podgląd maila
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  <KindBadge kind={data?.text_kind} />
                  {edited ? (
                    <>
                      <Badge variant="warning" size="sm">
                        Zmieniona ręcznie
                      </Badge>
                      <button
                        type="button"
                        className="text-xs font-medium text-primary hover:underline"
                        onClick={() => setDraft(defaults)}
                      >
                        Przywróć treść domyślną
                      </button>
                    </>
                  ) : null}
                </span>
              </div>
              <div className="space-y-2 p-3">
                <p className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2 text-sm">
                  <span className="text-xs text-muted-foreground">Do</span>
                  <span className="break-all">{eligible[0]?.to_email}</span>
                </p>
                <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-2">
                  <label
                    htmlFor="rejection-email-subject"
                    className="text-xs text-muted-foreground"
                  >
                    Temat
                  </label>
                  <Input
                    id="rejection-email-subject"
                    className="h-9"
                    value={editDraft.subject}
                    maxLength={998}
                    invalid={subjectEmpty}
                    onChange={(e) => setDraft({ ...editDraft, subject: e.target.value })}
                  />
                </div>
                {subjectEmpty ? (
                  <p className="text-xs text-destructive">Temat maila nie może być pusty.</p>
                ) : null}
                {data?.title_warning ? (
                  <p className="text-xs text-warning-muted-foreground">
                    Nazwa rekrutacji wygląda na kod zlecenia albo nazwę klienta —
                    popraw temat i treść, zanim mail wyjdzie.
                  </p>
                ) : null}
                <div className="space-y-1">
                  <label
                    htmlFor="rejection-email-body"
                    className="text-xs text-muted-foreground"
                  >
                    Treść
                  </label>
                  <Textarea
                    id="rejection-email-body"
                    rows={withOthers ? 5 : 7}
                    value={editDraft.body}
                    maxLength={5000}
                    invalid={bodyEmpty}
                    onChange={(e) => setDraft({ ...editDraft, body: e.target.value })}
                  />
                  {bodyEmpty ? (
                    <p className="text-xs text-destructive">
                      Treść maila nie może być pusta. Wpisz treść albo odznacz wysyłkę.
                    </p>
                  ) : null}
                </div>
                {others.length > 0 ? (
                  <div className="space-y-2">
                    <label className="flex cursor-pointer items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))] text-primary focus:ring-primary"
                        checked={appendOthers}
                        onChange={(e) => toggleOthers(e.target.checked)}
                      />
                      <span>
                        <span className="font-medium">
                          Dopisz pozostałe rekrutacje {shortName} ({others.length})
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {others.map(otherProcessLine).join(" — ")}
                        </span>
                      </span>
                    </label>
                    {appendOthers && data?.other_processes_text ? (
                      <OtherProcessesNote text={data.other_processes_text} />
                    ) : null}
                  </div>
                ) : null}
                <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                  <PenLine className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  Pod treścią NEXUS doda Twój podpis z Outlooka. Mail wyjdzie z Twojej
                  skrzynki Microsoft 365.
                </p>
              </div>
            </div>
          ) : data && sample ? (
            <div className="rounded-lg border border-primary/30">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-t-lg border-b border-border bg-primary/5 px-3 py-1.5">
                <span className="text-xs font-semibold uppercase tracking-[0.06em] text-primary">
                  {samples.length === 1 && nameOf(sample.candidate_id)
                    ? `Podgląd maila · ${nameOf(sample.candidate_id)}`
                    : "Podgląd maila"}
                </span>
                {samples.length > 1 ? (
                  <div role="tablist" aria-label="Rodzaj treści" className="flex gap-1">
                    {samples.map((s) => {
                      const selected = s.text_kind === sample.text_kind;
                      return (
                        <button
                          key={s.text_kind}
                          type="button"
                          role="tab"
                          aria-selected={selected}
                          onClick={() => setSampleKind(s.text_kind)}
                          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                            selected
                              ? "bg-primary text-primary-foreground"
                              : "border border-primary/30 text-primary hover:bg-primary/10"
                          }`}
                        >
                          {KIND_TAB_LABEL[s.text_kind]} ({kindCount(s.text_kind)})
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <Badge variant="outline" size="sm">
                    tylko do odczytu
                  </Badge>
                )}
              </div>
              <div className="space-y-2 p-3 text-sm">
                <p className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2">
                  <span className="text-xs text-muted-foreground">Temat</span>
                  <span>{sample.subject}</span>
                </p>
                <p className="whitespace-pre-wrap rounded-md bg-muted px-3 py-2">
                  {rejectionEmailDefaultBody(sample.body, sample.closing, false)}
                </p>
                {withOthersCount > 0 ? (
                  <p className="rounded-md border border-dashed border-border px-3 py-1.5 text-xs text-muted-foreground">
                    {withOthersCount === 1
                      ? "1 osoba dostanie"
                      : `Osoby z innymi rekrutacjami (${withOthersCount}) dostaną`}{" "}
                    zamiast ostatniego zdania dopisek z listą swoich pozostałych
                    rekrutacji (lista z chwili wysyłki).
                  </p>
                ) : null}
                <p className="text-xs text-muted-foreground">
                  Każda osoba dostanie tę treść ze swoim imieniem. Treść poprawisz,
                  odrzucając osoby pojedynczo.
                </p>
                <div className="space-y-1 text-xs">
                  <p className="text-muted-foreground">
                    Mail wyjdzie do {eligible.length} z {people.length} osób
                  </p>
                  <ul className="divide-y divide-dashed divide-border">
                    {people.map((p) => {
                      const name = nameOf(p.candidate_id) ?? `#${p.candidate_id}`;
                      const othersCount = p.other_processes?.length ?? 0;
                      return (
                        <li key={p.candidate_id} className="flex justify-between gap-2 py-1">
                          <span className={p.skip_reason ? "text-muted-foreground" : ""}>
                            {name}
                          </span>
                          <span className="flex flex-wrap justify-end gap-1.5 text-right text-muted-foreground">
                            {p.skip_reason ? (
                              `bez maila: ${rejectionEmailSkipShort(p.skip_reason)}`
                            ) : (
                              <>
                                {p.text_kind ? (
                                  <span>{REJECTION_EMAIL_TEXT_KIND_LABEL[p.text_kind]}</span>
                                ) : null}
                                {othersCount > 0 ? <span>· +{othersCount} w toku</span> : null}
                                <span>· {p.to_email}</span>
                              </>
                            )}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </FormField>
  );
}
