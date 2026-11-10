"use client";

import { Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { useOwnerCandidates } from "@/lib/api/sales";
import {
  useAcceptResearchPeople,
  usePreviewResearchList,
  type ResearchOutcome,
  type ResearchPreview,
} from "@/lib/api/sales-research-import";
import { CALM_HEAD } from "@/lib/calm-table";
import { useAuthStore } from "@/store/auth";

import { SalesSelect } from "../SalesSelect";

import {
  bulkEffect,
  bulkQuestion,
  IMPORT_ACCEPT,
  MIN_SOURCE_CHARS,
  peopleCount,
  previewSummary,
  resolveTarget,
  rowPhase,
  sourceFromFile,
  toInput,
  type CardChoice,
  type CreatedAccount,
  type Target,
} from "./research-import";
import { ResearchRowItem, type ResearchItem } from "./ResearchRowItem";

const SOURCE_MISSING = "Wpisz, skąd pochodzi lista: trafi to przy każdej osobie na mapie.";
const COMPANY_BUSY = "Poczekaj: zapisuje się inna osoba tej firmy.";

type ReadyItem = ResearchItem & { target: Target };

function isReady(item: ResearchItem): item is ReadyItem {
  return item.phase === "ready" && item.target !== null;
}

function skippedLine(skipped: ResearchPreview["skipped"]): string {
  const byReason = new Map<string, number[]>();
  for (const row of skipped) byReason.set(row.reason, [...(byReason.get(row.reason) ?? []), row.line]);
  return [...byReason.entries()]
    .map(([reason, lines]) => `${reason}: ${lines.length === 1 ? "wiersz" : "wiersze"} ${lines.join(", ")}`)
    .join("; ");
}

interface ResearchReviewProps {
  preview: ResearchPreview;
  fileName: string;
  onReset: () => void;
}

function ResearchReview({ preview, fileName, onReset }: ResearchReviewProps) {
  const user = useAuthStore((state) => state.user);
  const owners = useOwnerCandidates();
  const accept = useAcceptResearchPeople();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const [sourceLabel, setSourceLabel] = useState(() => sourceFromFile(fileName));
  const [ownerId, setOwnerId] = useState("");
  const [levels, setLevels] = useState<Record<number, number>>({});
  const [choices, setChoices] = useState<Record<string, CardChoice>>({});
  const [outcomes, setOutcomes] = useState<Record<number, ResearchOutcome>>({});
  const [created, setCreated] = useState<Record<string, CreatedAccount>>({});
  const [saving, setSaving] = useState<ReadonlySet<number>>(new Set());
  const [onlyToDecide, setOnlyToDecide] = useState(false);

  const companies = useMemo(
    () => new Map(preview.companies.map((company) => [company.key, company])),
    [preview.companies],
  );
  const items = preview.rows.flatMap((row): ResearchItem[] => {
    const company = companies.get(row.company_key);
    if (!company) return [];
    const target = resolveTarget(company, choices[company.key], created[company.key]);
    const outcome = outcomes[row.line];
    return [
      {
        row,
        company,
        target,
        outcome,
        phase: rowPhase(row, company, target, outcome),
        level: levels[row.line] ?? row.decision_level,
      },
    ];
  });
  const toDecide = items.filter(
    (item) => item.phase === "choose" || (item.phase === "ready" && item.row.confidence === "to_verify"),
  );
  // Jedna firma naraz: druga osoba ma trafić na kartę i konto założone przez pierwszą,
  // a zna je dopiero odpowiedź serwera.
  const busyCompanies = new Set(items.filter((item) => saving.has(item.row.line)).map((item) => item.company.key));
  const certain = items
    .filter(isReady)
    .filter((item) => item.row.confidence === "confirmed" && !busyCompanies.has(item.company.key));
  const added = items.filter((item) => item.phase === "added").length;
  const shown = onlyToDecide ? toDecide : items;
  const blockedReason = sourceLabel.trim().length < MIN_SOURCE_CHARS ? SOURCE_MISSING : null;
  const ownerOptions = (owners.data ?? [])
    .filter((owner) => owner.id !== user?.id)
    .map((owner) => ({ value: String(owner.id), label: owner.name }));

  const save = async (list: readonly ReadyItem[]) => {
    const lines = list.map((item) => item.row.line);
    const keyOf = new Map(list.map((item) => [item.row.line, item.company]));
    setSaving((current) => new Set([...current, ...lines]));
    try {
      // `mutateAsync`, bo kilka wierszy klikniętych po kolei ma każdy dostać swój wynik.
      const data = await accept.mutateAsync({
        source_label: sourceLabel.trim(),
        owner_user_id: ownerId ? Number(ownerId) : null,
        people: list.map((item) => toInput(item.row, item.level, item.target)),
      });
      setOutcomes((current) => ({
        ...current,
        ...Object.fromEntries(data.outcomes.map((outcome) => [outcome.line, outcome])),
      }));
      setCreated((current) => {
        const next = { ...current };
        for (const outcome of data.outcomes) {
          const company = keyOf.get(outcome.line);
          const landed = outcome.result === "added" || outcome.result === "on_map";
          // Firma z kontem od początku nie potrzebuje wpisu: jej cel się nie zmienia.
          if (!landed || !company || company.state === "account") continue;
          if (outcome.company_id && outcome.opportunity_id) {
            next[company.key] = { companyId: outcome.company_id, opportunityId: outcome.opportunity_id };
          }
        }
        return next;
      });
      const failed = data.outcomes.filter((outcome) => outcome.result !== "added");
      if (list.length > 1) {
        showSuccess(
          `Na mapy trafiło: ${peopleCount(data.added)}.${failed.length > 0 ? ` Bez zmian: ${failed.length}.` : ""}`,
        );
      } else if (failed[0]) {
        showError(failed[0].detail ?? "Nie udało się dodać osoby do mapy.");
      } else {
        showSuccess("Dodano osobę na mapę.");
      }
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się dodać osób do map."));
    } finally {
      setSaving((current) => new Set([...current].filter((line) => !lines.includes(line))));
    }
  };

  const onBulk = async () => {
    const ok = await askConfirm({
      title: `Dodać do map: ${peopleCount(certain.length)}?`,
      description: bulkQuestion(bulkEffect(certain)),
      confirmLabel: "Dodaj do map",
    });
    if (ok) await save(certain);
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 rounded-lg border border-border bg-card px-3 py-2">
        <div className="min-w-0 leading-tight">
          <div className="flex min-w-0 items-center gap-2">
            <Badge variant="soft" size="sm" className="shrink-0">
              Lista z researchu
            </Badge>
            <p className="truncate text-sm font-medium text-foreground">{fileName}</p>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {previewSummary(preview)}
            {added > 0 ? ` · dodano ${added}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-0.5">
            <Label htmlFor="research-source" className="text-xs text-muted-foreground">
              Skąd lista
            </Label>
            <Input
              id="research-source"
              className="h-8 w-64"
              maxLength={255}
              value={sourceLabel}
              onChange={(event) => setSourceLabel(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-0.5">
            <Label htmlFor="research-owner" className="text-xs text-muted-foreground">
              Opiekun nowych kont
            </Label>
            <SalesSelect
              id="research-owner"
              className="h-8 w-44"
              value={ownerId}
              onValueChange={setOwnerId}
              options={ownerOptions}
              anyLabel="Ja"
            />
          </div>
          <Button
            size="sm"
            variant={onlyToDecide ? "primary" : "outline"}
            className="h-8"
            aria-pressed={onlyToDecide}
            disabled={toDecide.length === 0 && !onlyToDecide}
            onClick={() => setOnlyToDecide((value) => !value)}
          >
            Tylko do decyzji ({toDecide.length})
          </Button>
          <Button
            size="sm"
            className="h-8"
            disabled={certain.length === 0 || blockedReason !== null}
            title={blockedReason ?? undefined}
            loading={accept.isPending && saving.size > 1}
            onClick={() => void onBulk()}
          >
            Dodaj pewne do map ({certain.length})
          </Button>
          <Button size="sm" variant="outline" className="h-8" onClick={onReset}>
            Zmień plik
          </Button>
        </div>
      </div>
      {preview.skipped.length > 0 && (
        <p role="status" className="text-xs text-muted-foreground">
          Pominięte wiersze pliku ({preview.skipped.length}): {skippedLine(preview.skipped)}.
        </p>
      )}
      {preview.known_failed && (
        <p role="status" className="text-xs text-warning">
          Nie udało się teraz policzyć „Znamy teraz”. Reszta przeglądu działa, a liczniki są na liście kont lejka.
        </p>
      )}
      {preview.known_truncated && (
        <p role="status" className="text-xs text-muted-foreground">
          „Znamy teraz” to dolna granica: skan bazy trafił w limit wierszy.
        </p>
      )}
      {/* `Table` ma własne przewijanie w poziomie; przy 1280 px mieści się bez niego. */}
      <Table density="compact" className="min-w-[940px]">
        <TableHeader>
          <TableRow>
            <TableHead className={`${CALM_HEAD} sticky left-0 min-w-[12.5rem] bg-background`}>Firma i osoba</TableHead>
            <TableHead className={CALM_HEAD}>Poziom</TableHead>
            <TableHead className={CALM_HEAD}>Pewność</TableHead>
            <TableHead className={CALM_HEAD}>W NEXUSIE</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Znamy teraz</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Co zrobić</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((item) => (
            <ResearchRowItem
              key={item.row.line}
              item={item}
              choice={choices[item.company.key]}
              resolved={created[item.company.key] !== undefined}
              saving={saving.has(item.row.line)}
              blockedReason={
                blockedReason ??
                (busyCompanies.has(item.company.key) && !saving.has(item.row.line) ? COMPANY_BUSY : null)
              }
              onLevel={(level) => setLevels((current) => ({ ...current, [item.row.line]: level }))}
              onChoose={(choice) => setChoices((current) => ({ ...current, [item.company.key]: choice }))}
              onAccept={() => {
                if (isReady(item)) void save([item]);
              }}
            />
          ))}
          {shown.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="py-4 text-center text-sm text-muted-foreground">
                {items.length === 0 ? "W pliku nie ma wierszy do dodania." : "Żaden wiersz nie czeka na decyzję."}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <p className="text-xs text-muted-foreground">
        Osoba trafia na mapę ze statusem „bez kontaktu”, ze źródłem i dzisiejszą datą. Nic się nie wysyła i nie dzwoni
        samo.
      </p>
      {confirmDialog}
    </div>
  );
}

/**
 * Leady → „Lista z researchu”: wgranie pliku z osobami i przegląd przed zapisem
 * do map decyzyjnych lejka Fabryki IT. Plik czyta serwer; ekran niczego nie
 * zapisuje, dopóki człowiek nie zaakceptuje wiersza albo wszystkich pewnych.
 */
export function ResearchImport() {
  const preview = usePreviewResearchList();
  const inputRef = useRef<HTMLInputElement>(null);
  const [loaded, setLoaded] = useState<{ preview: ResearchPreview; fileName: string; token: number } | null>(null);

  const onFile = (file: File | undefined) => {
    if (!file) return;
    preview.mutate(file, {
      onSuccess: (data) => setLoaded({ preview: data, fileName: file.name, token: Date.now() }),
    });
  };

  if (loaded) {
    return (
      <ResearchReview
        key={loaded.token}
        preview={loaded.preview}
        fileName={loaded.fileName}
        onReset={() => {
          preview.reset();
          setLoaded(null);
        }}
      />
    );
  }
  return (
    <div className="max-w-3xl space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="space-y-1">
        <h2 className="text-sm font-semibold text-foreground">Lista osób z researchu</h2>
        <p className="text-sm text-muted-foreground">
          Wgraj plik z osobami w firmach. Zanim cokolwiek trafi na mapy decyzyjne lejka Fabryki IT, zobaczysz każdy
          wiersz: firmę w NEXUSIE, pewność i to, co się stanie po akceptacji.
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={IMPORT_ACCEPT}
        className="hidden"
        aria-label="Plik z listą osób"
        onChange={(event) => {
          onFile(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      <Button size="sm" loading={preview.isPending} onClick={() => inputRef.current?.click()}>
        <Upload className="mr-1 h-4 w-4" aria-hidden /> Wybierz plik
      </Button>
      <p className="text-xs text-muted-foreground">
        CSV albo Excel (.xlsx), do 500 wierszy i 2 MB. Kolumny: Firma, Imię i nazwisko, Stanowisko; opcjonalnie E-mail,
        Telefon, LinkedIn, Źródło, Strona www, Pewność, Poziom, Notatka.
      </p>
      {preview.isError && (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(preview.error, "Nie udało się odczytać pliku.")}
        </p>
      )}
    </div>
  );
}
