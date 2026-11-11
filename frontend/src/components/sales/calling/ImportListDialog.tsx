"use client";

import { useMemo, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import { useOwnerCandidates } from "@/lib/api/sales";
import {
  useCallCampaigns,
  useImportList,
  usePreviewImport,
  type ImportInput,
  type ImportPreview,
} from "@/lib/api/sales-calling";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { useAuthStore } from "@/store/auth";

import { SalesSelect } from "../SalesSelect";
import { FATE_LABELS, FATE_TONES, fileProblem, IMPORT_ACCEPT, importSummary } from "./calling";

const MIN_SOURCE_CHARS = 3;
/** Więcej wierszy w tabeli spowalnia okno; filtr „do decyzji” pokazuje te ważne. */
const ROWS_SHOWN = 300;

interface PreviewProps {
  preview: ImportPreview;
  campaignName: string;
  sourceMissing: boolean;
  importing: boolean;
  onImport: () => void;
  onBack: () => void;
}

function Preview({ preview, campaignName, sourceMissing, importing, onImport, onBack }: PreviewProps) {
  const [onlyToDecide, setOnlyToDecide] = useState(false);
  const rows = useMemo(
    () => (onlyToDecide ? preview.rows.filter((row) => row.to_decide) : preview.rows),
    [onlyToDecide, preview.rows],
  );
  const shown = rows.slice(0, ROWS_SHOWN);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border border-border bg-card px-3 py-2">
        <div className="min-w-0 leading-tight">
          <p className="text-sm font-medium text-foreground">
            Lista do kampanii „{campaignName}”: {preview.total} wierszy z pliku
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">{importSummary(preview)}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            size="sm"
            variant={onlyToDecide ? "primary" : "outline"}
            className="h-8"
            aria-pressed={onlyToDecide}
            disabled={preview.to_decide === 0}
            onClick={() => setOnlyToDecide((value) => !value)}
          >
            Pokaż tylko do decyzji ({preview.to_decide})
          </Button>
          <Button
            size="sm"
            className="h-8"
            disabled={preview.addable === 0 || sourceMissing}
            title={sourceMissing ? "Wpisz, skąd masz kontakty z tej listy." : undefined}
            loading={importing}
            onClick={onImport}
          >
            Dodaj {preview.addable} do kolejki
          </Button>
        </div>
      </div>
      <div className="max-h-[46dvh] overflow-y-auto rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className={CALM_HEAD}>Firma z pliku</TableHead>
              <TableHead className={CALM_HEAD}>Osoba (stanowisko)</TableHead>
              <TableHead className={CALM_HEAD}>Co NEXUS o niej wie</TableHead>
              <TableHead className={`${CALM_HEAD} text-right`}>Co się stanie</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={row.line} className={CALM_ROW}>
                <TableCell className="py-1.5 font-medium text-foreground">
                  {row.company}
                  <span className={CALM_SUBLINE}>wiersz {row.line}</span>
                </TableCell>
                <TableCell className="py-1.5 text-sm text-muted-foreground">
                  {row.person ?? "—"}
                  <span className={`${CALM_SUBLINE} whitespace-nowrap tabular-nums`}>
                    {[row.title, row.phone].filter(Boolean).join(" · ") || "bez telefonu"}
                  </span>
                </TableCell>
                <TableCell className="py-1.5 text-sm text-muted-foreground">{row.detail}</TableCell>
                <TableCell className="py-1.5 text-right">
                  <Badge variant={FATE_TONES[row.fate]} size="md">
                    {FATE_LABELS[row.fate]}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {shown.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-4 text-center text-sm text-muted-foreground">
                  Żaden wiersz nie wymaga decyzji.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {rows.length > ROWS_SHOWN
            ? `Pokazano ${ROWS_SHOWN} z ${rows.length} wierszy. Import obejmuje wszystkie.`
            : "Wiersze poza „trafi do kolejki” zostają w pliku: import ich nie doda."}
        </p>
        <Button variant="outline" size="sm" onClick={onBack} disabled={importing}>
          Zmień plik
        </Button>
      </div>
    </div>
  );
}

interface ImportListDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNewCampaign: () => void;
}

/** Import listy do kampanii: najpierw los każdego wiersza, potem „Dodaj N do kolejki”. */
export function ImportListDialog({ open, onOpenChange, onNewCampaign }: ImportListDialogProps) {
  const me = useAuthStore((s) => s.user);
  const campaigns = useCallCampaigns(open);
  const people = useOwnerCandidates();
  const preview = usePreviewImport();
  const importList = useImportList();
  const { showError, showSuccess } = useToast();
  const [campaignId, setCampaignId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [assignee, setAssignee] = useState(me ? String(me.id) : "");

  const campaign = (campaigns.data ?? []).find((item) => String(item.id) === campaignId) ?? null;
  const sourceMissing = source.trim().length < MIN_SOURCE_CHARS;
  const input = (): ImportInput | null =>
    campaign && file
      ? {
          campaign_id: campaign.id,
          file,
          contact_source: source.trim(),
          assignee_user_id: assignee ? Number(assignee) : undefined,
        }
      : null;

  const pickFile = (next: File | null) => {
    preview.reset();
    const problem = next ? fileProblem(next) : null;
    if (problem) {
      showError(problem);
      setFile(null);
      return;
    }
    setFile(next);
  };

  const check = () => {
    const payload = input();
    if (!payload) return;
    preview.mutate(payload, {
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się sprawdzić listy.")),
    });
  };

  const add = () => {
    const payload = input();
    if (!payload) return;
    importList.mutate(payload, {
      onSuccess: (result) => {
        showSuccess(`Dodano ${result.added} do kolejki.`);
        onOpenChange(false);
      },
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać listy do kolejki.")),
    });
  };

  const assignees = (people.data ?? []).map((person) => ({ value: String(person.id), label: person.name }));
  const assigneeOptions =
    me && !assignees.some((option) => option.value === String(me.id))
      ? [{ value: String(me.id), label: me.name }, ...assignees]
      : assignees;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Importuj listę do kampanii"
      description="Plik CSV albo Excel (.xlsx) z kolumnami Firma i Telefon; opcjonalnie Osoba, Stanowisko, E-mail, WWW, NIP, Branża, Uwagi. Do 2000 wierszy i 2 MB."
      size="xl"
    >
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
          <div className="space-y-1">
            <Label htmlFor="call-import-campaign">Kampania</Label>
            <div className="flex gap-1.5">
              <SalesSelect
                id="call-import-campaign"
                className="min-w-0 flex-1 text-left [&>span]:line-clamp-1"
                value={campaignId}
                onValueChange={(value) => {
                  preview.reset();
                  setCampaignId(value);
                }}
                options={(campaigns.data ?? []).map((item) => ({ value: String(item.id), label: item.name }))}
                anyLabel="Wybierz kampanię"
                disabled={!campaigns.isSuccess}
              />
              <Button variant="outline" className="shrink-0 px-2.5" onClick={onNewCampaign}>
                Nowa
              </Button>
            </div>
            {campaigns.isError && (
              <p role="alert" className="text-xs text-destructive">
                {apiErrorMessage(campaigns.error, "Nie udało się wczytać kampanii.")}
              </p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="call-import-file">Plik z listą</Label>
            <Input
              id="call-import-file"
              type="file"
              accept={IMPORT_ACCEPT}
              onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="call-import-source" required>
              Skąd kontakt
            </Label>
            <Input
              id="call-import-source"
              value={source}
              maxLength={255}
              placeholder="np. własny research ze stron firm"
              onChange={(event) => setSource(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="call-import-assignee">Kto dzwoni</Label>
            <SalesSelect
              id="call-import-assignee"
              value={assignee}
              onValueChange={(value) => {
                preview.reset();
                setAssignee(value);
              }}
              options={assigneeOptions}
            />
          </div>
        </div>
        {preview.data && campaign ? (
          <Preview
            preview={preview.data}
            campaignName={campaign.name}
            sourceMissing={sourceMissing}
            importing={importList.isPending}
            onImport={add}
            onBack={() => preview.reset()}
          />
        ) : (
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Najpierw zobaczysz, co stanie się z każdym wierszem. Do kolejki nic nie trafi bez Twojego kliknięcia.
            </p>
            <Button onClick={check} disabled={!campaign || !file} loading={preview.isPending}>
              Sprawdź listę
            </Button>
          </div>
        )}
      </div>
    </AppModal>
  );
}
