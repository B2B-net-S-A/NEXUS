"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  jpkKrFilePath,
  useCompareJpkKr,
  useJpkKr,
  useSaveJpkKrSettings,
  type JpkKrAddress,
  type JpkKrCompareResult,
  type JpkKrOverview,
  type JpkKrProblem,
} from "@/lib/api/accounting-reports";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { countPl } from "@/lib/plural-pl";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "./AccountingShell";
import { gr } from "./ledger-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const ADDRESS_FIELDS: { key: keyof JpkKrAddress; label: string; wide?: boolean }[] = [
  { key: "province", label: "Województwo" },
  { key: "county", label: "Powiat" },
  { key: "commune", label: "Gmina" },
  { key: "city", label: "Miejscowość" },
  { key: "street", label: "Ulica", wide: true },
  { key: "building", label: "Nr budynku" },
  { key: "unit", label: "Nr lokalu" },
  { key: "postal_code", label: "Kod pocztowy" },
];
const MODE_LABELS: Record<JpkKrOverview["mode"], string> = {
  symfonia: "Symfonia FK",
  parallel: "równolegle z Symfonią",
  nexus: "NEXUS",
};

interface ProblemListProps {
  problems: JpkKrProblem[];
}

function ProblemList({ problems }: ProblemListProps) {
  if (!problems.length) return null;
  return (
    <ul className="space-y-1 rounded-md border border-destructive/40 bg-destructive/5 px-3.5 py-2 text-[13px]">
      {problems.map((item) => (
        <li key={item.code}>
          <b>{item.message}</b>
          {item.items.length ? (
            <span className="text-muted-foreground"> {item.items.slice(0, 30).join(", ")}{item.items.length > 30 ? "…" : ""}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1 rounded-md border border-warning/40 bg-warning/10 px-3.5 py-2 text-[12.5px]">
      {items.map((text) => (
        <p key={text}>{text}</p>
      ))}
    </div>
  );
}

interface SettingsFormProps {
  data: JpkKrOverview;
}

function SettingsForm({ data }: SettingsFormProps) {
  const [address, setAddress] = useState<JpkKrAddress>(data.settings.address);
  const [estonian, setEstonian] = useState(data.settings.estonian);
  const [since, setSince] = useState(data.settings.estonian_since ? String(data.settings.estonian_since) : "");
  const save = useSaveJpkKrSettings();
  const { showToast } = useToast();

  const submit = () =>
    save.mutate(
      { address, estonian, estonian_since: estonian && since ? Number(since) : null },
      {
        onSuccess: () => showToast("Zapisano dane do JPK_KR_PD.", "success"),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać danych do JPK_KR_PD."), "error"),
      },
    );

  return (
    <SectionCard title="Dane podatnika do JPK_KR_PD i JPK_ST_KR" aside="ustawia administrator">
      <div className="grid gap-2 px-3.5 py-3 sm:grid-cols-2 lg:grid-cols-4">
        {ADDRESS_FIELDS.map((field) => (
          <label key={field.key} className={cn("grid gap-1 text-[12.5px] text-muted-foreground", field.wide && "lg:col-span-2")}>
            {field.label}
            <input
              aria-label={field.label}
              className={CONTROL}
              value={address[field.key] ?? ""}
              onChange={(e) => setAddress({ ...address, [field.key]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-border/70 px-3.5 py-2 text-[13px]">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={estonian} onChange={(e) => setEstonian(e.target.checked)} />
          CIT estoński (ryczałt od dochodów spółek)
        </label>
        {estonian ? (
          <label className="flex items-center gap-2 text-muted-foreground">
            od roku
            <input
              aria-label="Pierwszy rok CIT estońskiego"
              className={cn(CONTROL, "w-20")}
              inputMode="numeric"
              value={since}
              onChange={(e) => setSince(e.target.value.replace(/\D/g, "").slice(0, 4))}
            />
          </label>
        ) : null}
        <Button size="sm" className="ml-auto" disabled={save.isPending} onClick={submit}>
          Zapisz dane
        </Button>
      </div>
    </SectionCard>
  );
}

interface CompareResultProps {
  result: JpkKrCompareResult;
}

function CompareResult({ result }: CompareResultProps) {
  if (result.same) {
    return <p className="px-3.5 py-3 text-[13px] text-success">Bez różnic — konta, kwoty, znaczniki i sumy kontrolne są zgodne.</p>;
  }
  return (
    <div className="space-y-2 px-3.5 py-3 text-[13px]">
      <p>
        <b>{countPl(result.differences, "różnica", "różnice", "różnic")}</b> · kont w NEXUSIE {result.accounts_nexus}, w Symfonii {result.accounts_symfonia}
      </p>
      {Object.keys(result.ctrl).length ? (
        <p>
          Sumy kontrolne:{" "}
          {Object.entries(result.ctrl)
            .map(([key, side]) => `${key} NEXUS ${side.nexus ?? "—"} / Symfonia ${side.symfonia ?? "—"}`)
            .join("; ")}
        </p>
      ) : null}
      {result.amounts.length ? (
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className={CALM_HEAD}>
              <th className="px-2 py-1.5 text-left">Konto</th>
              <th className="px-2 py-1.5 text-left">Pole</th>
              <th className="px-2 py-1.5 text-right">NEXUS</th>
              <th className="px-2 py-1.5 text-right">Symfonia</th>
            </tr>
          </thead>
          <tbody>
            {result.amounts.flatMap((row) =>
              Object.entries(row.fields).map(([field, side]) => (
                <tr key={`${row.account}-${field}`} className={CALM_ROW}>
                  <td className="px-2 py-1 font-mono">{row.account}</td>
                  <td className="px-2 py-1">{field}</td>
                  <td className={cn(CALM_AMOUNT, "px-2 py-1")}>{gr(side.nexus)}</td>
                  <td className={cn(CALM_AMOUNT, "px-2 py-1")}>{gr(side.symfonia)}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      ) : null}
      {result.markers.length ? (
        <p>
          Inne znaczniki:{" "}
          {result.markers.map((row) => `${row.account} (${row.nexus.join("/")} ≠ ${row.symfonia.join("/")})`).join("; ")}
        </p>
      ) : null}
      {result.only_nexus.length ? <p>Tylko w NEXUSIE: {result.only_nexus.join(", ")}</p> : null}
      {result.only_symfonia.length ? <p>Tylko w Symfonii: {result.only_symfonia.join(", ")}</p> : null}
    </div>
  );
}

interface CompareCardProps {
  year: number;
}

function CompareCard({ year }: CompareCardProps) {
  const compare = useCompareJpkKr();
  const [file, setFile] = useState<File | null>(null);
  return (
    <SectionCard title="Porównanie z JPK_KR_PD z Symfonii" aside="pliku nie zapisujemy">
      <div className="flex flex-wrap items-center gap-2 border-b border-border/70 px-3.5 py-2 text-[13px]">
        <input
          aria-label="Plik JPK_KR_PD z Symfonii"
          type="file"
          accept=".xml,application/xml,text/xml"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Button size="sm" variant="outline" disabled={!file || compare.isPending} onClick={() => file && compare.mutate({ year, file })}>
          {compare.isPending ? "Porównuję…" : "Porównaj"}
        </Button>
      </div>
      {compare.isError ? (
        <p className="px-3.5 py-3 text-[13px] text-destructive">
          {apiErrorMessage(compare.error, "Nie udało się porównać pliku z Symfonii.")}
        </p>
      ) : compare.data ? (
        <CompareResult result={compare.data} />
      ) : (
        <p className="px-3.5 py-3 text-[12.5px] text-muted-foreground">
          Wgraj plik roczny z Symfonii FK — NEXUS porówna zestawienie obrotów i sald (kwoty, znaczniki) i sumy kontrolne
          dziennika.
        </p>
      )}
    </SectionCard>
  );
}

interface JpkKrViewProps {
  year: number;
}

export function JpkKrView({ year }: JpkKrViewProps) {
  const overview = useJpkKr(year);
  const [correction, setCorrection] = useState(false);
  const [busy, setBusy] = useState<"kr" | "st" | null>(null);
  const { showToast } = useToast();

  if (overview.isError) return <QueryStateNotice state="error" onRetry={() => overview.refetch()} />;
  if (!overview.isSuccess) return <p className="py-6 text-sm text-muted-foreground">Wczytywanie JPK_KR_PD…</p>;
  const data = overview.data;

  const download = async (kind: "kr" | "st") => {
    setBusy(kind);
    try {
      await downloadAuthenticatedFile(
        jpkKrFilePath(year, kind, correction),
        kind === "kr" ? data.file_name : data.st.file_name,
      );
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się pobrać pliku JPK."), "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      <SectionCard
        title={`JPK_KR_PD za ${year}`}
        aside={
          <span className={data.ready ? "text-success" : "text-destructive"}>
            {data.ready ? "plik się składa" : countPl(data.problems.length, "brak", "braki", "braków")}
          </span>
        }
      >
        <div className="space-y-2 px-3.5 py-3">
          <p className="text-[13px] text-muted-foreground">
            Księgi roku z NEXUSA: {countPl(data.documents, "dokument", "dokumenty", "dokumentów")},{" "}
            {countPl(data.accounts, "konto", "konta", "kont")} w zestawieniu obrotów i sald. Księga
            urzędowa roku: {MODE_LABELS[data.mode]}. NEXUS składa plik i sprawdza go schematem MF — niczego nie wysyła.
          </p>
          <ProblemList problems={data.problems} />
          <Warnings items={data.warnings} />
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t border-border/70 px-3.5 py-2 text-[13px]">
          {data.can_download ? (
            <>
              <Button size="sm" disabled={!data.ready || busy !== null} onClick={() => void download("kr")}>
                {busy === "kr" ? "Pobieram…" : "Pobierz JPK_KR_PD"}
              </Button>
              <label className="flex items-center gap-2 text-muted-foreground">
                <input type="checkbox" checked={correction} onChange={(e) => setCorrection(e.target.checked)} />
                Korekta (cały plik od nowa)
              </label>
            </>
          ) : (
            <span className="text-muted-foreground">
              Plik zawiera dokumenty płacowe — pobiera go osoba z Płacami albo administrator.
            </span>
          )}
        </div>
      </SectionCard>

      <SectionCard
        title={`JPK_ST_KR za ${year} — ewidencja środków trwałych`}
        aside={
          <span className={data.st.ready ? "text-success" : "text-destructive"}>
            {data.st.ready
              ? countPl(data.st.assets, "środek", "środki", "środków")
              : countPl(data.st.problems.length, "brak", "braki", "braków")}
          </span>
        }
      >
        <div className="space-y-2 px-3.5 py-3">
          <p className="text-[13px] text-muted-foreground">
            Za lata 2026–2028 MF zwolniło z przesyłania JPK_ST_KR — plik służy sprawdzeniu ewidencji K6.
          </p>
          <ProblemList problems={data.st.problems} />
          <Warnings items={data.st.warnings} />
        </div>
        <div className="border-t border-border/70 px-3.5 py-2">
          <Button size="sm" variant="outline" disabled={!data.st.ready || busy !== null} onClick={() => void download("st")}>
            {busy === "st" ? "Pobieram…" : "Pobierz JPK_ST_KR"}
          </Button>
        </div>
      </SectionCard>

      {data.can_compare ? <CompareCard year={year} /> : null}
      {data.can_edit_settings ? <SettingsForm data={data} /> : null}
    </div>
  );
}
