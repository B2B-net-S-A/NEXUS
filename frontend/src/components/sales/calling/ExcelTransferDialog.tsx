"use client";

import { FileSpreadsheet } from "lucide-react";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCallCampaigns,
  usePreviewExcel,
  useTransferExcel,
  type ExcelPreview,
  type ExcelSheetPlan,
  type ImportFate,
  type RecordState,
} from "@/lib/api/sales-calling";

import { plural } from "../my-day";
import { SalesSelect } from "../SalesSelect";
import { fileProblem, STATE_TONES, stateLabel, SUMMARY_TEXT } from "./calling";

const MIN_SOURCE_CHARS = 3;

/** Co stanie się z osobą w danym stanie (te same daty powrotu co w kolejce). */
const STATE_PLAN: { state: RecordState; what: string; excel?: string }[] = [
  { state: "no_answer", what: "do kolejki na następny dzień roboczy" },
  { state: "call_back", what: "do kolejki w dniu z „Ponowny kontakt”" },
  { state: "offer_sent", what: "oddzwonienie za 3 dni robocze", excel: "żółty" },
  { state: "new", what: "do kolejki jako nowe" },
  { state: "meeting_booked", what: "zamknięte jako umówione spotkanie", excel: "niebieski, zielony" },
  { state: "not_interested", what: "wraca za pół roku", excel: "czerwony" },
  { state: "bad_contact", what: "zamknięte, do poprawy danych" },
];

/** Wiersze, których przeniesienie nie doda (te same bramki co import listy). */
const SKIPPED: ImportFate[] = ["already_in_campaign", "other_caller", "client", "do_not_contact", "no_phone"];

function SheetCard({
  sheet,
  people,
  assignee,
  onAssign,
}: {
  sheet: ExcelSheetPlan;
  people: { value: string; label: string }[];
  assignee: string;
  onAssign: (value: string) => void;
}) {
  const skipped = SKIPPED.filter((fate) => (sheet.fates[fate] ?? 0) > 0);
  const selectId = `excel-sheet-${sheet.title.replace(/\W+/g, "-")}`;
  return (
    <section aria-label={`Arkusz ${sheet.title}`} className="space-y-2 rounded-lg border border-border bg-card p-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <Label htmlFor={selectId} className="text-sm font-semibold text-foreground">
          Arkusz „{sheet.title}” →
        </Label>
        <SalesSelect
          id={selectId}
          className="w-56"
          value={assignee}
          onValueChange={onAssign}
          options={people}
          anyLabel="Wybierz osobę"
        />
      </header>
      {assignee ? (
        <table className="w-full text-xs">
          <tbody className="divide-y divide-border">
            {STATE_PLAN.filter((item) => (sheet.states[item.state] ?? 0) > 0).map((item) => (
              <tr key={item.state}>
                <td className="py-1 pr-2">
                  <Badge variant={STATE_TONES[item.state]} size="sm">
                    {stateLabel(item.state)}
                  </Badge>
                  {item.excel && <span className="ml-1 text-[10px] text-muted-foreground">({item.excel} w Excelu)</span>}
                </td>
                <td className="py-1 pr-2 text-right font-semibold tabular-nums text-foreground">
                  {sheet.states[item.state]}
                </td>
                <td className="py-1 text-muted-foreground">{item.what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-xs text-muted-foreground">Wybierz osobę, a zobaczysz, co trafi do jej kolejki.</p>
      )}
      <ul className="space-y-0.5 text-xs text-muted-foreground">
        {assignee && skipped.length > 0 && (
          <li>
            Pominięte: {skipped.map((fate) => `${sheet.fates[fate]} ${SUMMARY_TEXT[fate]}`).join(" · ")}
          </li>
        )}
        {sheet.moved > 0 && <li>{sheet.moved} osób stoi też w późniejszym arkuszu i trafi tam.</li>}
        {sheet.review > 0 && <li>{sheet.review} z komentarzem bez wyniku: trafią jako nowe, z komentarzem w notatce.</li>}
        {sheet.without_company > 0 && <li>{sheet.without_company} wierszy bez nazwy firmy pominięto.</li>}
        {sheet.days > 0 && (
          <li>
            Podsumowania dnia: {plural(sheet.days, "dzień", "dni", "dni")} · {sheet.totals.calls} telefonów ·{" "}
            {sheet.totals.talks} rozmów · {sheet.totals.offers} ofert · {sheet.totals.meetings} spotkań → historia
            {sheet.duplicate_days > 0 &&
              ` (${plural(sheet.duplicate_days, "dzień ma", "dni mają", "dni ma")} dwa podsumowania: liczy się późniejsze)`}
          </li>
        )}
      </ul>
    </section>
  );
}

interface ExcelTransferDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Jednorazowe przeniesienie Excela osób dzwoniących (decyzja Artura 11.11.2026): arkusz to
 * osoba, kolor wiersza to wynik, podsumowania dni to historia. Najpierw bieg na sucho,
 * zapis dopiero po kliknięciu.
 */
export function ExcelTransferDialog({ open, onOpenChange }: ExcelTransferDialogProps) {
  const campaigns = useCallCampaigns(open);
  const preview = usePreviewExcel();
  const transfer = useTransferExcel();
  const { showError, showSuccess } = useToast();
  const [campaignId, setCampaignId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [assignees, setAssignees] = useState<Record<string, number>>({});

  const campaign = (campaigns.data ?? []).find((item) => String(item.id) === campaignId) ?? null;
  const data: ExcelPreview | undefined = preview.data;
  const people = (data?.people ?? []).map((person) => ({ value: String(person.id), label: person.name }));
  const chosen = (sheet: ExcelSheetPlan) => assignees[sheet.title] ?? sheet.assignee_id ?? null;
  const unassigned = (data?.sheets ?? []).filter((sheet) => chosen(sheet) === null);
  const addable = (data?.sheets ?? []).reduce((sum, sheet) => sum + sheet.addable, 0);
  const sourceMissing = source.trim().length < MIN_SOURCE_CHARS;

  const mapping = (base: Record<string, number>): Record<string, number> => {
    const merged: Record<string, number> = {};
    for (const sheet of data?.sheets ?? []) {
      const value = base[sheet.title] ?? sheet.assignee_id;
      if (value !== null && value !== undefined) merged[sheet.title] = value;
    }
    return { ...merged, ...base };
  };

  const check = (next: Record<string, number> = assignees) => {
    if (!campaign || !file) return;
    preview.mutate(
      { campaign_id: campaign.id, file, contact_source: source.trim(), assignees: mapping(next) },
      { onError: (error) => showError(apiErrorMessage(error, "Nie udało się sprawdzić pliku.")) },
    );
  };

  const assign = (title: string, value: string) => {
    const next = { ...assignees, [title]: Number(value) };
    setAssignees(next);
    check(next);
  };

  const run = () => {
    if (!campaign || !file || !data) return;
    transfer.mutate(
      { campaign_id: campaign.id, file, contact_source: source.trim(), assignees: mapping(assignees) },
      {
        onSuccess: (result) => {
          showSuccess(
            `Przeniesiono ${plural(result.added, "osobę", "osoby", "osób")} i ${plural(result.days, "dzień", "dni", "dni")} podsumowań.`,
          );
          onOpenChange(false);
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się przenieść Excela.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Przenieś Excel dzwoniących"
      description="Plik .xlsx z arkuszem na osobę. Kolor wiersza i komentarz to wynik, „Ponowny kontakt” to data powrotu, a wiersze „Podsumowanie” trafią do historii."
      size="xl"
    >
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="excel-transfer-campaign">Kampania</Label>
            <SalesSelect
              id="excel-transfer-campaign"
              value={campaignId}
              onValueChange={(value) => {
                preview.reset();
                setCampaignId(value);
              }}
              options={(campaigns.data ?? []).map((item) => ({ value: String(item.id), label: item.name }))}
              anyLabel="Wybierz kampanię"
              disabled={!campaigns.isSuccess}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="excel-transfer-file">Plik Excela</Label>
            <Input
              id="excel-transfer-file"
              type="file"
              accept=".xlsx"
              onChange={(event) => {
                const next = event.target.files?.[0] ?? null;
                preview.reset();
                setAssignees({});
                const problem = next ? fileProblem(next) : null;
                if (problem) showError(problem);
                setFile(problem ? null : next);
              }}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="excel-transfer-source" required>
              Skąd kontakt
            </Label>
            <Input
              id="excel-transfer-source"
              value={source}
              maxLength={255}
              placeholder="np. Lista BE Leady (Excel dzwoniących)"
              onChange={(event) => setSource(event.target.value)}
            />
          </div>
        </div>
        {data ? (
          <>
            <div className="grid gap-2 lg:grid-cols-2">
              {data.sheets.map((sheet) => (
                <SheetCard
                  key={sheet.title}
                  sheet={sheet}
                  people={people}
                  assignee={chosen(sheet) === null ? "" : String(chosen(sheet))}
                  onAssign={(value) => assign(sheet.title, value)}
                />
              ))}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                {unassigned.length > 0
                  ? `Wybierz osobę dla: ${unassigned.map((sheet) => `„${sheet.title}”`).join(", ")}.`
                  : sourceMissing
                    ? "Wpisz, skąd są kontakty z tego pliku."
                    : "Ten sam plik drugi raz niczego nie zdubluje."}
              </p>
              <Button
                onClick={run}
                disabled={unassigned.length > 0 || sourceMissing || addable === 0 || preview.isPending}
                loading={transfer.isPending}
              >
                <FileSpreadsheet className="mr-1.5 h-4 w-4" aria-hidden /> Przenieś {plural(addable, "osobę", "osoby", "osób")}
              </Button>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Najpierw zobaczysz, co stanie się z każdym arkuszem. Nic się nie zapisze bez Twojego kliknięcia.
            </p>
            <Button onClick={() => check()} disabled={!campaign || !file} loading={preview.isPending}>
              Sprawdź plik
            </Button>
          </div>
        )}
      </div>
    </AppModal>
  );
}
