"use client";

/**
 * Board Data Entry — admin formularz miesięcznych raportów Rady Nadzorczej.
 * Port `BoardDataEntry.tsx` z artur-t-96/InfraReporter (536L).
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Save,
  RefreshCw,
  DollarSign,
  Plus,
  Trash2,
  AlertCircle,
  CheckCircle,
} from "lucide-react";
import {
  dynareporterBoardApi,
  dynareporterBoardAdminApi,
  type DrBoardPlacementClient,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function formatPLN(value: number): string {
  if (!value) return "0 zł";
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 0 }) + " zł";
}

export function BoardDataEntry() {
  const queryClient = useQueryClient();
  const now = new Date();
  const currentYM = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [reportMonth, setReportMonth] = useState(currentYM);
  const [revenue, setRevenue] = useState(0);
  const [consultantCosts, setConsultantCosts] = useState(0);
  const [otherCosts, setOtherCosts] = useState(0);
  const [activeConsultants, setActiveConsultants] = useState(0);
  const [departures, setDepartures] = useState(0);
  const [placements, setPlacements] = useState(0);
  const [avgMarginPerHour, setAvgMarginPerHour] = useState(0);
  const [hitRatio, setHitRatio] = useState(0);
  const [clients, setClients] = useState<DrBoardPlacementClient[]>([]);
  const [saveStatus, setSaveStatus] = useState<{
    type: "success" | "error";
    msg: string;
  } | null>(null);

  // Load existing data for selected month
  useQuery({
    queryKey: ["dr-board-monthly-admin"],
    queryFn: () => dynareporterBoardApi.monthly(),
    staleTime: 30_000,
  });

  const loadExisting = async (month: string) => {
    const all = await dynareporterBoardApi.monthly();
    const found = all.find((r) => r.report_month === month);
    if (found) {
      setRevenue(found.revenue);
      setConsultantCosts(found.consultant_costs);
      setOtherCosts(found.other_costs);
      setActiveConsultants(found.active_consultants);
      setDepartures(found.departures);
      setPlacements(found.placements);
      setAvgMarginPerHour(found.avg_margin_per_hour);
      setHitRatio(found.hit_ratio);
      setClients(found.placement_clients);
    } else {
      // Reset for new month
      setRevenue(0);
      setConsultantCosts(0);
      setOtherCosts(0);
      setActiveConsultants(0);
      setDepartures(0);
      setPlacements(0);
      setAvgMarginPerHour(0);
      setHitRatio(0);
      setClients([]);
    }
  };

  const upsertMutation = useMutation({
    mutationFn: () =>
      dynareporterBoardAdminApi.upsert({
        report_month: reportMonth,
        revenue,
        consultant_costs: consultantCosts,
        other_costs: otherCosts,
        active_consultants: activeConsultants,
        departures,
        placements,
        avg_margin_per_hour: avgMarginPerHour,
        hit_ratio: hitRatio,
        placement_clients: clients.filter((c) => c.client_name && c.count > 0),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-board-monthly"] });
      queryClient.invalidateQueries({ queryKey: ["dr-board-monthly-admin"] });
      setSaveStatus({ type: "success", msg: "Raport zapisany" });
      setTimeout(() => setSaveStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setSaveStatus({ type: "error", msg: `Błąd: ${extractErrorMsg(e)}` });
    },
  });

  const margin = revenue - consultantCosts;
  const profit = margin - otherCosts;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
            <DollarSign className="w-5 h-5 text-purple-600" />
            Rada Nadzorcza — wpisywanie miesięcznego raportu
          </h3>

          <div className="flex items-center gap-2 mb-4">
            <label className="text-sm text-muted-foreground">Miesiąc:</label>
            <input
              type="month"
              value={reportMonth}
              onChange={(e) => setReportMonth(e.target.value)}
              className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => loadExisting(reportMonth)}
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              <span className="ml-1">Wczytaj istniejące</span>
            </Button>
            <Button
              size="sm"
              onClick={() => upsertMutation.mutate()}
              disabled={upsertMutation.isPending}
              className="ml-auto"
            >
              <Save className="w-4 h-4" aria-hidden="true" />
              <span className="ml-1">Zapisz raport</span>
            </Button>
          </div>

          {saveStatus && (
            <div
              className={`mb-3 flex items-center gap-2 text-sm ${saveStatus.type === "success" ? "text-emerald-600" : "text-rose-600"}`}
            >
              {saveStatus.type === "success" ? (
                <CheckCircle className="w-4 h-4" />
              ) : (
                <AlertCircle className="w-4 h-4" />
              )}
              {saveStatus.msg}
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <NumberInput
              label="Revenue (PLN)"
              value={revenue}
              onChange={setRevenue}
            />
            <NumberInput
              label="Consultant costs (PLN)"
              value={consultantCosts}
              onChange={setConsultantCosts}
            />
            <NumberInput
              label="Other costs (PLN)"
              value={otherCosts}
              onChange={setOtherCosts}
            />
            <NumberInput
              label="Avg margin/h (PLN)"
              value={avgMarginPerHour}
              onChange={setAvgMarginPerHour}
            />
            <NumberInput
              label="Active consultants"
              value={activeConsultants}
              onChange={setActiveConsultants}
              integer
            />
            <NumberInput
              label="Departures"
              value={departures}
              onChange={setDepartures}
              integer
            />
            <NumberInput
              label="Placements"
              value={placements}
              onChange={setPlacements}
              integer
            />
            <NumberInput
              label="Hit Ratio (%)"
              value={hitRatio}
              onChange={setHitRatio}
              step={0.1}
            />
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div className="p-2 bg-muted/40 rounded">
              <span className="text-muted-foreground">
                Margin (rev − koszty):
              </span>{" "}
              <strong className="text-emerald-700 dark:text-emerald-400">
                {formatPLN(margin)}
              </strong>
            </div>
            <div className="p-2 bg-muted/40 rounded">
              <span className="text-muted-foreground">
                Profit (po wszystkim):
              </span>{" "}
              <strong className="text-purple-700 dark:text-purple-400">
                {formatPLN(profit)}
              </strong>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-base font-semibold">Placements per klient</h3>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                setClients([...clients, { client_name: "", count: 0 }])
              }
            >
              <Plus className="w-4 h-4" aria-hidden="true" />
              <span className="ml-1">Dodaj klienta</span>
            </Button>
          </div>
          {clients.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              Brak klientów. Kliknij "Dodaj klienta" żeby dodać pierwszy wpis.
            </p>
          ) : (
            <div className="space-y-2">
              {clients.map((c, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Nazwa klienta"
                    value={c.client_name}
                    onChange={(e) => {
                      const next = [...clients];
                      next[idx] = { ...c, client_name: e.target.value };
                      setClients(next);
                    }}
                    className="flex-1 px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                  />
                  <input
                    type="number"
                    min={0}
                    placeholder="0"
                    value={c.count}
                    onChange={(e) => {
                      const next = [...clients];
                      next[idx] = { ...c, count: Number(e.target.value) };
                      setClients(next);
                    }}
                    className="w-20 px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setClients(clients.filter((_, i) => i !== idx))
                    }
                    aria-label="Usuń klienta"
                  >
                    <Trash2
                      className="w-4 h-4 text-rose-600"
                      aria-hidden="true"
                    />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function NumberInput({
  label,
  value,
  onChange,
  step,
  integer,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  integer?: boolean;
}) {
  return (
    <div>
      <label className="block text-xs text-muted-foreground mb-1">
        {label}
      </label>
      <input
        type="number"
        min={0}
        step={step ?? (integer ? 1 : 0.01)}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md tabular-nums"
      />
    </div>
  );
}
