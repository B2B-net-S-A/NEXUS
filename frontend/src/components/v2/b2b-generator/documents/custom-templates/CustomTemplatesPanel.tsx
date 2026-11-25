"use client";

// Lista wzorów własnych w zakładce Dokumenty: zatwierdzone (wszyscy),
// własne szkice i — dla administratora — wzory czekające na zatwierdzenie.

import { FileText, Loader2 } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCustomTemplates,
  type CustomTemplatesList,
} from "@/lib/api/customTemplates";
import { templateStatusLabel } from "@/lib/custom-templates";

export function CustomTemplatesPanel({
  onOpen,
  onNew,
  canGenerate,
}: {
  onOpen: (id: number) => void;
  onNew: () => void;
  canGenerate: boolean;
}) {
  const list = useCustomTemplates();
  return (
    <CustomTemplatesPanelView
      state={
        list.isPending
          ? "loading"
          : list.isError && !list.data
            ? "error"
            : list.isSuccess && list.data.templates.length === 0
              ? "empty"
              : "ready"
      }
      data={list.data}
      error={list.error}
      onRetry={() => void list.refetch()}
      onOpen={onOpen}
      onNew={onNew}
      canGenerate={canGenerate}
    />
  );
}

export function CustomTemplatesPanelView({
  state,
  data,
  error,
  onRetry,
  onOpen,
  onNew,
  canGenerate,
}: {
  state: "loading" | "error" | "empty" | "ready";
  data?: CustomTemplatesList;
  error?: unknown;
  onRetry: () => void;
  onOpen: (id: number) => void;
  onNew: () => void;
  canGenerate: boolean;
}) {
  const rows = data?.templates ?? [];
  const pending = rows.filter((r) => r.working_status === "pending");
  return (
    <section className="space-y-2" aria-label="Wzory własne">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Wzory własne</h3>
        {data?.is_admin && pending.length ? (
          <Badge variant="warning">Do zatwierdzenia: {pending.length}</Badge>
        ) : null}
      </div>
      {state === "loading" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Wczytuję wzory…
        </p>
      ) : state === "error" ? (
        <Alert variant="error" title={apiErrorMessage(error, "Nie udało się wczytać wzorów własnych.")}>
          <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
            Ponów
          </Button>
        </Alert>
      ) : state === "empty" ? (
        <EmptyState
          icon={FileText}
          title="Nie ma jeszcze wzorów własnych"
          description="Nowy wzór (np. umowa o poprowadzeniu szkolenia) przygotujesz z asystentem — po zatwierdzeniu przez administratora pojawi się w „Nowy dokument”."
          action={
            canGenerate ? (
              <Button size="sm" variant="outline" onClick={onNew}>
                Nowy wzór z asystentem
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {rows.map((row) => {
            const status = templateStatusLabel(row);
            return (
              <li key={row.id}>
                <button
                  type="button"
                  onClick={() => onOpen(row.id)}
                  className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
                >
                  <FileText className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{row.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {row.kind_label}
                      {row.author_name ? ` · ${row.author_name}` : ""}
                      {row.working_status && row.active_version_no
                        ? ` · w pracy v${row.working_version_no}`
                        : ""}
                    </span>
                  </span>
                  <Badge variant={status.tone} size="sm">
                    {status.label}
                  </Badge>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
