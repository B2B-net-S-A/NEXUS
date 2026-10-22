"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Mail, Paperclip, Pencil, X } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CASE_AREA_LABELS,
  CASE_SOURCE_LABELS,
  CASE_STATUSES,
  CASE_STATUS_LABELS,
  useAddCaseComment,
  useCase,
  useCloseCase,
  useUpdateCase,
  type CaseChecklistItem,
  type CaseDetail,
  type CaseStatus,
} from "@/lib/api/admin-cases";
import { useHrConfig } from "@/lib/api/hr";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";
import { canSeeCareBoard } from "@/components/work-board/care-access";
import { useAuthStore } from "@/store/auth";

import { CaseConsultantSection, CaseWhoBar } from "./CaseConsultant";
import { CaseFormDialog } from "./CaseFormDialog";
import {
  PRIORITY_BADGE,
  STATUS_TONE,
  addChecklistItem,
  dueLabel,
  fileSize,
  removeChecklistItem,
  toggleChecklistItem,
} from "./case-format";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
      {children}
    </h2>
  );
}

function Checklist({ detail }: { detail: CaseDetail }) {
  const update = useUpdateCase(detail.id);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const items = detail.checklist;

  const save = (next: CaseChecklistItem[], after?: () => void) => {
    setError(null);
    update.mutate(
      { checklist: next, expected_updated_at: detail.updated_at },
      {
        onSuccess: after,
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać checklisty.")),
      },
    );
  };

  return (
    <Card className="p-4">
      <SectionTitle>
        Checklista
        {items.length > 0
          ? ` · ${items.filter((item) => item.done).length}/${items.length}`
          : ""}
      </SectionTitle>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Bez pozycji.</p>
      ) : (
        <ul className="space-y-1">
          {items.map((item, index) => (
            <li key={`${index}-${item.text}`} className="group flex items-start gap-2 text-sm">
              <Checkbox
                className="mt-0.5"
                checked={item.done}
                disabled={!detail.can_manage || update.isPending}
                onCheckedChange={() => save(toggleChecklistItem(items, index))}
                aria-label={item.text}
              />
              <span
                className={
                  item.done ? "flex-1 text-muted-foreground line-through" : "flex-1 text-foreground"
                }
              >
                {item.text}
              </span>
              {detail.can_manage ? (
                <button
                  type="button"
                  className="hit-area text-muted-foreground hover:text-foreground pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100 focus-visible:opacity-100"
                  aria-label={`Usuń pozycję „${item.text}”`}
                  disabled={update.isPending}
                  onClick={() => save(removeChecklistItem(items, index))}
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {detail.can_manage ? (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!draft.trim()) return;
            save(addChecklistItem(items, draft), () => setDraft(""));
          }}
        >
          <Input
            aria-label="Nowa pozycja checklisty"
            placeholder="np. Badania okresowe"
            maxLength={300}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="h-8"
          />
          <Button type="submit" size="sm" variant="outline" disabled={update.isPending}>
            Dodaj
          </Button>
        </form>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </Card>
  );
}

function Messages({ detail }: { detail: CaseDetail }) {
  if (detail.messages.length === 0) return null;
  return (
    <Card className="p-4">
      <SectionTitle>Wiadomości · {detail.messages.length}</SectionTitle>
      <ol className="space-y-3">
        {detail.messages.map((message) => (
          <li key={message.id} className="rounded-md border border-border/70 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-muted-foreground">
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <Mail className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="truncate font-medium text-foreground">
                  {message.sender_name ?? message.sender_email ?? "Nadawca nieznany"}
                </span>
                {message.sender_name && message.sender_email ? (
                  <span className="truncate">{message.sender_email}</span>
                ) : null}
              </span>
              <span>{formatMomentPl(message.received_at)}</span>
            </div>
            {message.subject ? (
              <p className="mt-1 text-sm font-medium text-foreground">{message.subject}</p>
            ) : null}
            <p className="mt-1 whitespace-pre-line break-words text-sm text-foreground">
              {message.body_text || "Wiadomość bez treści."}
            </p>
            {message.attachments.filter((file) => !file.inline).length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {message.attachments
                  .filter((file) => !file.inline)
                  .map((file, index) => (
                    <li
                      key={`${index}-${file.name}`}
                      className="inline-flex max-w-full items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      <Paperclip className="h-3 w-3 shrink-0" aria-hidden />
                      <span className="truncate">{file.name}</span>
                      {file.size != null ? (
                        <span className="shrink-0">{` · ${fileSize(file.size)}`}</span>
                      ) : null}
                    </li>
                  ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ol>
      <p className="mt-2 text-xs text-muted-foreground">
        Załączniki są w skrzynce administracja@ — NEXUS trzyma tylko ich nazwy.
      </p>
    </Card>
  );
}

function Comments({ detail }: { detail: CaseDetail }) {
  const add = useAddCaseComment(detail.id);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <Card className="p-4">
      <SectionTitle>Komentarze · {detail.comments.length}</SectionTitle>
      {detail.comments.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nikt jeszcze nie skomentował.</p>
      ) : (
        <ol className="space-y-2.5">
          {detail.comments.map((comment) => (
            <li key={comment.id} className="text-sm">
              <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">
                  {comment.author?.name ?? "Konto usunięte"}
                </span>
                <span>{formatMomentPl(comment.created_at)}</span>
              </div>
              <p className="mt-0.5 whitespace-pre-line break-words text-foreground">
                {comment.body}
              </p>
            </li>
          ))}
        </ol>
      )}
      {detail.can_comment ? (
        <form
          className="mt-3 space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!body.trim()) return;
            setError(null);
            add.mutate(body, {
              onSuccess: () => setBody(""),
              onError: (err) =>
                setError(apiErrorMessage(err, "Nie udało się dodać komentarza.")),
            });
          }}
        >
          <Textarea
            aria-label="Komentarz"
            placeholder="Co ustalono, na co czekamy…"
            rows={3}
            maxLength={10000}
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
          <div className="flex justify-end">
            <Button type="submit" size="sm" disabled={add.isPending || !body.trim()}>
              {add.isPending ? "Zapisywanie…" : "Dodaj komentarz"}
            </Button>
          </div>
          {error ? (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          ) : null}
        </form>
      ) : null}
    </Card>
  );
}

function Header({ detail, onEdit }: { detail: CaseDetail; onEdit: () => void }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const update = useUpdateCase(detail.id);
  const close = useCloseCase(detail.id);
  const due = dueLabel(detail);

  const changeStatus = (status: CaseStatus) => {
    update.mutate(
      { status, expected_updated_at: detail.updated_at },
      {
        onSuccess: () => showToast(`Status: ${CASE_STATUS_LABELS[status]}`, "success"),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zmienić statusu."), "error"),
      },
    );
  };

  const closeCase = async () => {
    const confirmed = await askConfirm({
      title: "Zamknąć sprawę?",
      description: "Sprawa zniknie z tablicy. Znajdziesz ją po zaznaczeniu „Pokaż zamknięte”.",
      confirmLabel: "Zamknij sprawę",
    });
    if (!confirmed) return;
    close.mutate(undefined, {
      onSuccess: () => showToast("Sprawa zamknięta", "success"),
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się zamknąć sprawy."), "error"),
    });
  };

  return (
    <header className="flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="text-xl font-semibold text-foreground">{detail.title}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
          <StatusDot tone={STATUS_TONE[detail.status]}>
            {CASE_STATUS_LABELS[detail.status]}
          </StatusDot>
          <Badge variant={PRIORITY_BADGE[detail.priority]} size="sm">
            {detail.priority}
          </Badge>
          {due ? (
            <Badge variant={due.overdue ? "danger" : "outline"} size="sm">
              {due.text}
            </Badge>
          ) : null}
          <span className="text-muted-foreground">
            {CASE_AREA_LABELS[detail.area]} · {CASE_SOURCE_LABELS[detail.source]}
          </span>
        </div>
      </div>
      {detail.can_manage ? (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={detail.status}
            onValueChange={(value) => changeStatus(value as CaseStatus)}
            disabled={update.isPending}
          >
            <SelectTrigger className="h-9 w-44" aria-label="Status sprawy">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CASE_STATUSES.map((status) => (
                <SelectItem key={status} value={status}>
                  {CASE_STATUS_LABELS[status]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={onEdit}>
            <Pencil className="h-4 w-4" aria-hidden />
            Edytuj
          </Button>
          {detail.status !== "closed" ? (
            <Button variant="outline" onClick={closeCase} disabled={close.isPending}>
              Zamknij sprawę
            </Button>
          ) : null}
        </div>
      ) : null}
      {confirmDialog}
    </header>
  );
}

/**
 * Szczegół sprawy: nagłówek z akcjami, „Kogo dotyczy?” (sprawa bez
 * kontraktu), opis, wątek maili, komentarze, checklista i karta „Konsultant”
 * (od 22.10.2026 zamiast „Powiązań”, gdy sprawa ma kontrakt).
 */
export function CaseDetailView({ caseId }: { caseId: number }) {
  const query = useCase(caseId);
  const [editing, setEditing] = useState(false);
  const user = useAuthStore((s) => s.user);
  const hrConfig = useHrConfig();
  const careAccess = canSeeCareBoard(user, hrConfig.data);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie sprawy…</p>;
  }
  if (state !== "ready" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "forbidden"
            ? "Sprawę widzi obsługa skrzynki i osoba do niej przypisana."
            : state === "not_found"
              ? "Nie ma takiej sprawy albo moduł „Sprawy” jest wyłączony."
              : undefined
        }
        onRetry={() => query.refetch()}
      />
    );
  }

  const detail = query.data;
  return (
    <div className="space-y-4">
      <Link
        href="/people/cases"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        Sprawy
      </Link>
      <Header detail={detail} onEdit={() => setEditing(true)} />
      <CaseWhoBar detail={detail} />

      <div className="grid gap-4 lg:grid-cols-3">
        {/* `min-w-0`: bez tego długi adres albo nazwa załącznika rozpycha stronę na telefonie. */}
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <Card className="p-4">
            <SectionTitle>Opis</SectionTitle>
            <p className="whitespace-pre-line break-words text-sm text-foreground">
              {detail.description ?? (
                <span className="text-muted-foreground">Bez opisu.</span>
              )}
            </p>
          </Card>
          <Messages detail={detail} />
          <Comments detail={detail} />
        </div>
        <div className="min-w-0 space-y-4">
          <Card className="p-4">
            <SectionTitle>Szczegóły</SectionTitle>
            <Fact label="Osoba odpowiedzialna">{detail.assignee?.name ?? "nikt"}</Fact>
            <Fact label="Termin">{formatIsoDatePl(detail.due_on)}</Fact>
            <Fact label="Kontakt">{formatIsoDatePl(detail.follow_up_on)}</Fact>
            <Fact label="Założona">{formatMomentPl(detail.created_at)}</Fact>
            {detail.created_by ? (
              <Fact label="Założył(a)">{detail.created_by.name ?? "—"}</Fact>
            ) : null}
            {detail.closed_at ? <Fact label="Zakończona">{formatMomentPl(detail.closed_at)}</Fact> : null}
          </Card>
          <Checklist detail={detail} />
          {detail.contract ? (
            <Card className="p-4">
              <SectionTitle>Konsultant</SectionTitle>
              <CaseConsultantSection detail={detail} careAccess={careAccess} />
            </Card>
          ) : null}
          {detail.subject_user ? (
            <Card className="p-4">
              <SectionTitle>Osoba</SectionTitle>
              <Fact label="Pracownik">
                <Link href={`/people/${detail.subject_user.id}`} className="hover:underline">
                  {detail.subject_user.name ?? `#${detail.subject_user.id}`}
                </Link>
              </Fact>
            </Card>
          ) : null}
          {!detail.contract && !detail.subject_user && !detail.can_manage ? (
            <Card className="p-4">
              <SectionTitle>Powiązania</SectionTitle>
              <p className="text-sm text-muted-foreground">
                Sprawa nie jest spięta z kontraktem ani z osobą.
              </p>
            </Card>
          ) : null}
        </div>
      </div>

      {detail.can_manage && editing ? (
        <CaseFormDialog open={editing} onOpenChange={setEditing} existing={detail} />
      ) : null}
    </div>
  );
}
