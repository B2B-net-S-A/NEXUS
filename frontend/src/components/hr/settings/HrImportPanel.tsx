"use client";

import { useState } from "react";
import { Upload } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useHrImportApply,
  useHrImportDryRun,
  type HrImportModule,
  type HrImportModuleReport,
  type HrImportUpload,
} from "@/lib/api/hr-import";
import { formatDateTimePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

import { HrImportAttention } from "./HrImportAttention";
import { HrImportCountsTable } from "./HrImportCountsTable";

function pending(module: HrImportModuleReport): number {
  return module.counts.create + module.counts.update + module.counts.conflict;
}

/** Na start zaznaczone moduły, w których zapis coś zrobi (i bez błędu próby). */
function defaultSelection(upload: HrImportUpload): HrImportModule[] {
  return upload.modules
    .filter((module) => module.error === null && pending(module) > 0)
    .map((module) => module.module);
}

function confirmDescription(modules: HrImportModuleReport[]): string {
  const created = modules.reduce((sum, m) => sum + m.counts.create, 0);
  const updated = modules.reduce((sum, m) => sum + m.counts.update, 0);
  const conflicts = modules.reduce((sum, m) => sum + m.counts.conflict, 0);
  const labels = modules.map((m) => m.label).join(", ");
  return [
    `Zmieni się ${countPl(created + updated, "pozycja", "pozycje", "pozycji")}: nowe ${created}, zmienione ${updated} (${labels}).`,
    conflicts > 0
      ? `Pozycji z konfliktem (${conflicts}) import nie nadpisze — zmiany zrobione w NEXUSIE zostają.`
      : null,
    "Po zapisie paczka znika z NEXUSA, zostają liczby i suma SHA-256.",
  ]
    .filter(Boolean)
    .join(" ");
}

function UploadMeta({ upload }: { upload: HrImportUpload }) {
  return (
    <p className="text-xs text-muted-foreground">
      Partia #{upload.id} · SHA-256{" "}
      <span className="font-mono" title={upload.bundle_sha256}>
        {upload.bundle_sha256.slice(0, 12)}…
      </span>
      {upload.exported_at ? ` · eksport z Compassa ${formatDateTimePl(upload.exported_at)}` : ""}
      {upload.status === "applied"
        ? ` · zapisano ${formatDateTimePl(upload.applied_at)}${
            upload.applied_by_name ? ` (${upload.applied_by_name})` : ""
          }`
        : ` · sprawdzono ${formatDateTimePl(upload.created_at)} · ważna do ${formatDateTimePl(
            upload.expires_at,
          )}`}
    </p>
  );
}

/**
 * Ustawienia → Import z Compassa: paczka → sprawdzenie na sucho (liczby per
 * moduł, lista do wyjaśnienia) → wybór modułów → zapis (tylko administrator).
 */
export function HrImportPanel({ isAdmin }: { isAdmin: boolean }) {
  const { showToast } = useToast();
  const dryRun = useHrImportDryRun();
  const apply = useHrImportApply();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<HrImportUpload | null>(null);
  const [selected, setSelected] = useState<HrImportModule[]>([]);
  const [error, setError] = useState<string | null>(null);

  const check = () => {
    if (!file) return;
    setError(null);
    dryRun.mutate(file, {
      onSuccess: (result) => {
        setUpload(result);
        setSelected(defaultSelection(result));
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się sprawdzić paczki.")),
    });
  };

  const save = async () => {
    if (!upload) return;
    const modules = upload.modules.filter((m) => selected.includes(m.module));
    if (modules.length === 0) return;
    const ok = await askConfirm({
      title: "Zapisać paczkę z Compassa?",
      description: confirmDescription(modules),
      confirmLabel: "Zapisz",
      variant: "destructive",
    });
    if (!ok) return;
    setError(null);
    apply.mutate(
      {
        id: upload.id,
        bundle_sha256: upload.bundle_sha256,
        modules: modules.map((m) => m.module),
      },
      {
        onSuccess: (result) => {
          setUpload(result);
          setFile(null);
          showToast("Paczka zapisana", "success");
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać paczki.")),
      },
    );
  };

  const toggle = (module: HrImportModule, next: boolean) =>
    setSelected((current) =>
      next ? [...current, module] : current.filter((value) => value !== module),
    );

  const applied = upload?.status === "applied";
  const canSave = isAdmin && upload?.status === "dry_run";

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border p-4 text-sm">
        <Upload className="h-5 w-5 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {file ? file.name : "Paczka eksportu Compassa (.json albo .zip)"}
          </p>
          <p className="text-xs text-muted-foreground">
            Sprawdzenie na sucho niczego nie zapisuje. Paczka niesie dane osobowe: leży
            w NEXUSIE najwyżej do zapisu albo 24 h, potem zostają tylko liczby.
          </p>
        </div>
        <label className="inline-flex h-9 cursor-pointer items-center rounded-md border border-border px-4 text-sm hover:bg-muted">
          Wybierz plik paczki
          <input
            type="file"
            accept=".json,.zip,application/json,application/zip"
            className="sr-only"
            disabled={dryRun.isPending || apply.isPending}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              event.target.value = "";
            }}
          />
        </label>
        <Button onClick={check} disabled={!file || dryRun.isPending || apply.isPending}>
          {dryRun.isPending ? "Sprawdzanie…" : "Sprawdź na sucho"}
        </Button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {upload ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-foreground">
                {applied ? "Wynik zapisu" : "Sprawdzenie na sucho"}
              </h2>
              <UploadMeta upload={upload} />
            </div>
            {canSave ? (
              <Button
                onClick={save}
                disabled={selected.length === 0 || apply.isPending}
              >
                {apply.isPending ? "Zapisywanie…" : "Zapisz"}
              </Button>
            ) : null}
          </div>
          <HrImportCountsTable
            modules={
              applied
                ? upload.modules.filter((m) => upload.applied_modules.includes(m.module))
                : upload.modules
            }
            source={applied ? "applied" : "dry_run"}
            selected={canSave ? selected : undefined}
            onToggle={canSave ? toggle : undefined}
          />
          {upload.status === "dry_run" && !isAdmin ? (
            <p className="text-sm text-muted-foreground">
              Zapis robi administrator — przekaż mu ten raport (partia #{upload.id}).
            </p>
          ) : null}
          {canSave ? (
            <p className="text-xs text-muted-foreground">
              Moduły zapisują się w kolejności z tabeli. Urlopy, czas pracy i płace łączą
              osoby przez kartoteki, więc liczby na sucho zakładają zapis kartotek.
            </p>
          ) : null}
          {!applied ? <HrImportAttention modules={upload.modules} /> : null}
        </div>
      ) : null}
      {confirmDialog}
    </Card>
  );
}
