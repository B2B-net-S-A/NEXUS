"use client";

/**
 * „Dokumenty do startu” w panelu osoby i w kontrakcie (0649, decyzje Artura
 * 05.11.2026). Klient bez listy: karty nie ma. Konto bez dostępu do tej pary:
 * też nie ma, bo to nie jego sprawa, ale awaria mówi o sobie.
 */

import Link from "next/link";
import { useRef, useState, type ChangeEvent, type ReactNode } from "react";
import {
  CheckCircle2,
  Circle,
  Download,
  ExternalLink,
  FileUp,
  KeyRound,
  Mail,
  RotateCcw,
  Undo2,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  itemUrl,
  startDocsApi,
  startDocsKeys,
  usePairAction,
  usePairStartDocs,
  type PairStartDoc,
  type PairStartDocs,
} from "@/lib/api/start-documents";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { dayMonth, startLine } from "@/lib/start-docs-format";
import { cn } from "@/lib/utils";

import { REMIND_NOT_SENT } from "./StartDocsTasks";

const small = "h-7 px-2 text-xs";

type ReasonKind = "return" | "not_applicable";

function ReasonDialog({
  kind,
  item,
  busy,
  onSubmit,
  onClose,
}: {
  kind: ReasonKind;
  item: PairStartDoc;
  busy: boolean;
  onSubmit: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const valid = reason.trim().length >= 3;
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? null : onClose())}
      title={kind === "return" ? `Zwróć: ${item.name}` : `Nie dotyczy: ${item.name}`}
      description={
        kind === "return"
          ? "Rekruter dostanie powód w dzwonku, a pozycja wróci do braków."
          : "Pozycja przestaje być potrzebna tej osobie. Powód zostaje przy pozycji."
      }
      size="sm"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Anuluj
          </Button>
          <Button size="sm" disabled={!valid || busy} onClick={() => onSubmit(reason.trim())}>
            {kind === "return" ? "Zwróć" : "Zapisz"}
          </Button>
        </div>
      }
    >
      <Textarea
        aria-label="Powód"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder={kind === "return" ? "Np. brak podpisu" : "Np. NDA z poprzedniego kontraktu"}
        maxLength={500}
        rows={3}
      />
    </AppModal>
  );
}

function PeselDialog({
  busy,
  onSubmit,
  onClose,
}: {
  busy: boolean;
  onSubmit: (pesel: string) => void;
  onClose: () => void;
}) {
  const [pesel, setPesel] = useState("");
  const digits = pesel.replace(/\s/g, "");
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? null : onClose())}
      title="Wpisz PESEL"
      description="Po zapisie numer widzi tylko Delivery Lead klienta i administrator."
      size="sm"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Anuluj
          </Button>
          <Button size="sm" disabled={digits.length !== 11 || busy} onClick={() => onSubmit(digits)}>
            Zapisz
          </Button>
        </div>
      }
    >
      <Input
        aria-label="PESEL"
        inputMode="numeric"
        autoComplete="off"
        maxLength={13}
        value={pesel}
        onChange={(event) => setPesel(event.target.value)}
      />
    </AppModal>
  );
}

function ListMailDialog({
  candidateId,
  jobId,
  onClose,
  onSent,
}: {
  candidateId: number;
  jobId: number;
  onClose: () => void;
  onSent: () => void;
}) {
  const { showError, showSuccess } = useToast();
  const [sending, setSending] = useState(false);
  const preview = useQuery({
    queryKey: startDocsKeys.mail(candidateId, jobId),
    queryFn: () => startDocsApi.mailPreview(candidateId, jobId),
    retry: false,
    gcTime: 0,
  });
  const data = preview.data;
  const canSend = Boolean(data?.mailbox_connected && data?.to);
  const send = async () => {
    setSending(true);
    try {
      await startDocsApi.mailSend(candidateId, jobId);
      showSuccess("Lista poszła do konsultanta.");
      onSent();
      onClose();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wysłać listy."));
    } finally {
      setSending(false);
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(data?.text ?? "");
      showSuccess("Treść skopiowana.");
    } catch {
      showError("Nie udało się skopiować. Zaznacz treść i skopiuj ją ręcznie.");
    }
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? null : onClose())}
      title="Lista dokumentów dla konsultanta"
      description="Mail idzie z Twojej skrzynki. Dokumenty wracają do Ciebie, a Ty dodajesz je tutaj."
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose}>
            Anuluj
          </Button>
          {data && !canSend ? (
            <Button size="sm" variant="outline" onClick={() => void copy()}>
              Skopiuj treść
            </Button>
          ) : null}
          <Button size="sm" disabled={!canSend || sending} onClick={() => void send()}>
            Wyślij
          </Button>
        </div>
      }
    >
      {preview.isLoading ? (
        <p className="text-sm text-muted-foreground">Przygotowuję treść…</p>
      ) : preview.isError || !data ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(preview.error, "Nie udało się przygotować maila.")}
        </p>
      ) : (
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-[4.5rem_1fr] gap-y-1 text-[13px]">
            <span className="text-muted-foreground">Do</span>
            <span>{data.to ?? "Ta osoba nie ma adresu w NEXUSIE"}</span>
            <span className="text-muted-foreground">Temat</span>
            <span>{data.subject}</span>
          </div>
          {!data.mailbox_connected ? (
            <p className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
              Twoja skrzynka Microsoft 365 nie jest połączona z NEXUSEM. Skopiuj treść i wyślij ją z Outlooka.
            </p>
          ) : null}
          <pre className="whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3 font-sans text-[13px] leading-relaxed">
            {data.text}
          </pre>
          {data.attachments.length ? (
            <ul className="flex flex-wrap gap-2 text-xs">
              {data.attachments.map((name) => (
                <li key={name} className="rounded-md border border-border px-2 py-1">
                  {name}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </AppModal>
  );
}

function Row({
  item,
  detail,
  children,
}: {
  item: PairStartDoc;
  detail?: ReactNode;
  children?: ReactNode;
}) {
  const done = item.state === "delivered" || item.state === "not_applicable";
  return (
    <li className="flex items-start gap-2" data-testid={`start-doc-${item.id}`}>
      {done ? (
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
      ) : (
        <Circle
          className={cn(
            "mt-0.5 h-3.5 w-3.5 shrink-0",
            item.state === "returned" ? "text-destructive" : "text-muted-foreground",
          )}
          strokeDasharray={item.required ? undefined : "3 3"}
          aria-hidden
        />
      )}
      <div className="min-w-0 flex-1">
        <span className={cn("text-[13px] text-foreground", done && "text-muted-foreground")}>
          {item.name}
          {item.required ? null : " (opcjonalnie)"}
        </span>
        {!done && item.deadline ? (
          <span className="ml-1.5 text-[11px] tabular-nums text-muted-foreground">
            do {dayMonth(item.deadline)}
          </span>
        ) : null}
        {detail ? <span className="block text-[11px] text-muted-foreground">{detail}</span> : null}
        {children ? <div className="mt-1 flex flex-wrap items-center gap-1.5">{children}</div> : null}
      </div>
    </li>
  );
}

/** Stary wpis z błędnym adresem nie może wywrócić karty wszystkim rekruterom. */
export function linkLabel(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function detailOf(item: PairStartDoc, state: PairStartDocs): ReactNode {
  if (item.state === "returned") {
    return (
      <span className="text-destructive">
        Zwrócone: {item.reason}
        {item.reason_by_name ? ` (${item.reason_by_name})` : ""}
      </span>
    );
  }
  if (item.state === "not_applicable") {
    return `Nie dotyczy: ${item.reason ?? ""}`;
  }
  if (item.kind === "agreement") {
    return item.state === "delivered"
      ? `Nr ${state.agreement_number ?? "z kontraktu"}, odhacza się sama przy podpisie`
      : "Odhaczy się sama przy podpisie";
  }
  if (item.kind === "pesel") {
    return item.state === "delivered"
      ? "Wpisany. Widzi go tylko Delivery Lead klienta i administrator."
      : "Telefonicznie od konsultanta, nie mailem. Po zapisie widzi go tylko Delivery Lead.";
  }
  if (item.state === "delivered" && item.file_name) {
    const checked = item.checked_at
      ? `, sprawdzone${item.checked_by_name ? `: ${item.checked_by_name}` : ""}`
      : "";
    return `${item.file_name}${checked}`;
  }
  return (
    <>
      {item.note}
      {item.link_url ? (
        <>
          {item.note ? " " : null}
          <a
            href={item.link_url}
            target="_blank"
            rel="noreferrer"
            className="text-primary hover:underline"
          >
            {linkLabel(item.link_url)}
            <ExternalLink className="ml-0.5 inline h-2.5 w-2.5" aria-hidden />
          </a>
        </>
      ) : null}
    </>
  );
}

export function StartDocsCard({ candidateId, jobId }: { candidateId: number; jobId: number }) {
  const { showError, showSuccess } = useToast();
  const query = usePairStartDocs(candidateId, jobId);
  const action = usePairAction(candidateId, jobId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploadFor, setUploadFor] = useState<number | null>(null);
  const [reason, setReason] = useState<{ kind: ReasonKind; item: PairStartDoc } | null>(null);
  const [peselFor, setPeselFor] = useState<PairStartDoc | null>(null);
  // Numer jest przypięty do pary i do wpisu: po poprawce DL nie może widzieć starego.
  const [shownPesel, setShownPesel] = useState<{ key: string; value: string } | null>(null);
  const [mailOpen, setMailOpen] = useState(false);

  if (query.isError) {
    const status = (query.error as { response?: { status?: number } })?.response?.status;
    if (status === 403 || status === 404) return null;
    return (
      <p role="alert" className="rounded-lg border border-border p-3 text-xs text-destructive">
        Nie udało się sprawdzić dokumentów do startu.{" "}
        <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
          Ponów
        </button>
      </p>
    );
  }
  const state = query.data;
  if (!state || !state.items.length) return null;
  const { can_work: canWork, can_review: canReview, can_download: canDownload, can_view_pesel: canViewPesel } =
    state.permissions;

  const run = (call: () => Promise<PairStartDocs>, fallback: string) =>
    action.mutateAsync(call).catch((error) => {
      showError(apiErrorMessage(error, fallback));
      throw error;
    });

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || uploadFor === null) return;
    await run(
      () => startDocsApi.uploadFile(candidateId, jobId, uploadFor, file),
      "Nie udało się dodać pliku.",
    ).catch(() => undefined);
  };
  const pickFile = (documentId: number) => {
    setUploadFor(documentId);
    fileInput.current?.click();
  };
  const download = async (path: string, name: string) => {
    try {
      await downloadAuthenticatedFile(path, name);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać pliku."));
    }
  };
  const peselKey = (item: PairStartDoc) =>
    `${candidateId}-${jobId}-${item.id}-${item.delivered_at}`;
  const showPesel = async (item: PairStartDoc) => {
    try {
      setShownPesel({
        key: peselKey(item),
        value: await startDocsApi.readPesel(candidateId, jobId, item.id),
      });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się odczytać numeru."));
    }
  };
  const remind = async () => {
    try {
      const { sent } = await startDocsApi.remind(candidateId, jobId);
      showSuccess(sent ? "Rekruter dostał przypomnienie." : REMIND_NOT_SENT);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wysłać przypomnienia."));
    }
  };

  const complete = state.done === state.total;
  const late = !complete && state.tone !== "calm";
  const open = state.items.some((item) => item.state === "missing" || item.state === "returned");

  return (
    <section
      aria-label="Dokumenty do startu"
      className={cn(
        "space-y-2.5 rounded-lg border bg-card p-3",
        late ? "border-warning/40" : "border-border",
      )}
      data-testid="start-docs-card"
      data-tour="start-docs.card"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">Dokumenty do startu</h3>
        <Badge variant={complete ? "success" : "warning"}>
          {state.done} z {state.total}
        </Badge>
        <Link
          href={`/clients/${state.client_id}?tab=wejscie`}
          className="ml-auto text-[11px] text-muted-foreground hover:underline"
        >
          Lista klienta
        </Link>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={state.total}
        aria-valuenow={state.done}
        aria-label="Postęp dokumentów"
      >
        <div
          className={cn("h-full rounded-full", complete ? "bg-success" : "bg-warning")}
          style={{ width: `${state.total ? (state.done / state.total) * 100 : 0}%` }}
        />
      </div>
      <p
        className={cn(
          "text-xs",
          late ? "font-medium text-warning-muted-foreground" : "text-muted-foreground",
        )}
      >
        {complete ? "Komplet." : `${startLine(state.start_date, state.deadline, state.tone)}.`}
        {state.recruiter_name ? ` Prowadzi: ${state.recruiter_name}.` : ""}
      </p>
      <input
        ref={fileInput}
        type="file"
        accept=".pdf,.jpg,.jpeg,.png"
        className="hidden"
        aria-label="Plik dokumentu"
        onChange={(event) => void onFile(event)}
      />
      <ul className="space-y-2.5">
        {state.items.map((item) => {
          const missing = item.state === "missing" || item.state === "returned";
          return (
            <Row key={item.id} item={item} detail={detailOf(item, state)}>
              {item.kind === "file" && missing && canWork && item.template_name ? (
                <Button
                  size="sm"
                  variant="outline"
                  className={small}
                  onClick={() =>
                    void download(itemUrl(candidateId, jobId, item.id, "template"), item.template_name ?? "wzor")
                  }
                >
                  <Download className="h-3 w-3" aria-hidden />
                  Pobierz wzór
                </Button>
              ) : null}
              {item.kind === "file" && canWork && item.state !== "not_applicable" ? (
                <Button size="sm" variant="outline" className={small} onClick={() => pickFile(item.id)}>
                  <FileUp className="h-3 w-3" aria-hidden />
                  {missing ? "Dodaj plik" : "Podmień"}
                </Button>
              ) : null}
              {item.kind === "file" && item.file_name && canDownload && !missing ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className={small}
                  onClick={() =>
                    void download(itemUrl(candidateId, jobId, item.id, "file"), item.file_name ?? "dokument")
                  }
                >
                  <Download className="h-3 w-3" aria-hidden />
                  Pobierz
                </Button>
              ) : null}
              {item.kind === "pesel" && missing && canWork ? (
                <Button size="sm" variant="outline" className={small} onClick={() => setPeselFor(item)}>
                  <KeyRound className="h-3 w-3" aria-hidden />
                  Wpisz PESEL
                </Button>
              ) : null}
              {item.kind === "pesel" && item.state === "delivered" && canViewPesel ? (
                shownPesel?.key === peselKey(item) ? (
                  <span className="font-mono text-xs tabular-nums" data-testid="start-docs-pesel">
                    {shownPesel.value}
                  </span>
                ) : (
                  <Button size="sm" variant="outline" className={small} onClick={() => void showPesel(item)}>
                    <KeyRound className="h-3 w-3" aria-hidden />
                    Pokaż
                  </Button>
                )
              ) : null}
              {canReview && item.state === "delivered" && item.kind === "file" && !item.checked_at ? (
                <Button
                  size="sm"
                  variant="outline"
                  className={small}
                  onClick={() =>
                    void run(
                      () => startDocsApi.check(candidateId, jobId, item.id),
                      "Nie udało się zapisać.",
                    ).catch(() => undefined)
                  }
                >
                  Sprawdzone
                </Button>
              ) : null}
              {canReview && item.state === "delivered" && item.has_value ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className={small}
                  onClick={() => setReason({ kind: "return", item })}
                >
                  <Undo2 className="h-3 w-3" aria-hidden />
                  Zwróć
                </Button>
              ) : null}
              {canReview && missing ? (
                <button
                  type="button"
                  className="text-[11px] text-muted-foreground hover:underline"
                  onClick={() => setReason({ kind: "not_applicable", item })}
                >
                  Nie dotyczy
                </button>
              ) : null}
              {canReview && item.state === "not_applicable" ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className={small}
                  onClick={() =>
                    void run(
                      () => startDocsApi.reset(candidateId, jobId, item.id),
                      "Nie udało się cofnąć.",
                    ).catch(() => undefined)
                  }
                >
                  <RotateCcw className="h-3 w-3" aria-hidden />
                  Cofnij
                </Button>
              ) : null}
            </Row>
          );
        })}
      </ul>
      {open && canWork ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
          <Button size="sm" onClick={() => setMailOpen(true)} data-testid="start-docs-send-list">
            <Mail className="h-3.5 w-3.5" aria-hidden />
            Wyślij listę konsultantowi
          </Button>
          {canReview ? (
            <Button size="sm" variant="outline" onClick={() => void remind()}>
              Przypomnij rekruterowi
            </Button>
          ) : null}
          {state.list_sent_at ? (
            <span className="text-[11px] text-muted-foreground">Lista wysłana.</span>
          ) : null}
        </div>
      ) : null}
      {mailOpen ? (
        <ListMailDialog
          candidateId={candidateId}
          jobId={jobId}
          onClose={() => setMailOpen(false)}
          onSent={() => void query.refetch()}
        />
      ) : null}
      {reason ? (
        <ReasonDialog
          kind={reason.kind}
          item={reason.item}
          busy={action.isPending}
          onClose={() => setReason(null)}
          onSubmit={(text) => {
            const { kind, item } = reason;
            void run(
              () =>
                kind === "return"
                  ? startDocsApi.returnItem(candidateId, jobId, item.id, text)
                  : startDocsApi.notApplicable(candidateId, jobId, item.id, text),
              "Nie udało się zapisać.",
            )
              .then(() => setReason(null))
              .catch(() => undefined);
          }}
        />
      ) : null}
      {peselFor ? (
        <PeselDialog
          busy={action.isPending}
          onClose={() => setPeselFor(null)}
          onSubmit={(pesel) => {
            void run(
              () => startDocsApi.savePesel(candidateId, jobId, peselFor.id, pesel),
              "Nie udało się zapisać numeru.",
            )
              .then(() => setPeselFor(null))
              .catch(() => undefined);
          }}
        />
      ) : null}
    </section>
  );
}
