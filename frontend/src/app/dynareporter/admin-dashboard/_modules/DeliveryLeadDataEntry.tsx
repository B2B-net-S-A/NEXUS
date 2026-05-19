"use client";

/**
 * Delivery Lead Data Entry — admin formularz miesięcznych KPI dla DL.
 * Port `DeliveryLeadDataEntry.tsx` z artur-t-96/InfraReporter.
 */

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, RefreshCw, Target, CheckCircle, AlertCircle } from "lucide-react";
import { dynareporterDeliveryLeadApi, type DrDLMember } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function DeliveryLeadDataEntry() {
  const queryClient = useQueryClient();
  const now = new Date();
  const currentYM = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [reportMonth, setReportMonth] = useState(currentYM);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [requests, setRequests] = useState(0);
  const [placements, setPlacements] = useState(0);
  const [vacancies, setVacancies] = useState(0);
  const [openRequests, setOpenRequests] = useState(0);
  const [openVacancies, setOpenVacancies] = useState(0);
  const [saveStatus, setSaveStatus] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  // Get list of all DLs
  const dashboardQuery = useQuery({
    queryKey: ["dr-dl-dashboard-admin"],
    queryFn: () => dynareporterDeliveryLeadApi.dashboard(),
    staleTime: 60_000,
  });

  // Default to first DL
  useEffect(() => {
    if (dashboardQuery.data && selectedUserId === null) {
      const first = dashboardQuery.data.delivery_leads.find((dl: DrDLMember) => dl.is_active);
      if (first) setSelectedUserId(first.id);
    }
  }, [dashboardQuery.data, selectedUserId]);

  const upsertMutation = useMutation({
    mutationFn: () => {
      if (selectedUserId === null) throw new Error("Wybierz DL");
      return dynareporterDeliveryLeadApi.upsert({
        user_id: selectedUserId,
        report_month: reportMonth,
        requests,
        placements,
        vacancies,
        open_requests: openRequests,
        open_vacancies: openVacancies,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-dl-dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["dr-dl-dashboard-admin"] });
      setSaveStatus({ type: "success", msg: "KPI DL zapisane" });
      setTimeout(() => setSaveStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setSaveStatus({ type: "error", msg: `Błąd: ${String(e)}` });
    },
  });

  const selectedDL = dashboardQuery.data?.delivery_leads.find(
    (dl: DrDLMember) => dl.id === selectedUserId,
  );

  return (
    <Card>
      <CardContent className="pt-6">
        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
          <Target className="w-5 h-5 text-orange-600" />
          Delivery Lead — wpisywanie miesięcznych KPI
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Miesiąc</label>
            <input
              type="month"
              value={reportMonth}
              onChange={(e) => setReportMonth(e.target.value)}
              className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Delivery Lead</label>
            <select
              value={selectedUserId ?? ""}
              onChange={(e) => setSelectedUserId(Number(e.target.value))}
              className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
            >
              <option value="">— wybierz —</option>
              {(dashboardQuery.data?.delivery_leads ?? [])
                .filter((dl: DrDLMember) => dl.is_active)
                .map((dl: DrDLMember) => (
                  <option key={dl.id} value={dl.id}>
                    {dl.name}
                  </option>
                ))}
            </select>
          </div>
        </div>

        {selectedDL && (
          <div className="mb-3 p-2 bg-muted/40 rounded text-xs text-muted-foreground">
            Aktualne stats {selectedDL.name}: Requests {selectedDL.requests}, Placements{" "}
            {selectedDL.placements}, Hit Ratio {selectedDL.hit_ratio}%
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <NumberInput label="Requests" value={requests} onChange={setRequests} />
          <NumberInput label="Placements" value={placements} onChange={setPlacements} />
          <NumberInput label="Vacancies" value={vacancies} onChange={setVacancies} />
          <NumberInput label="Open requests" value={openRequests} onChange={setOpenRequests} />
          <NumberInput label="Open vacancies" value={openVacancies} onChange={setOpenVacancies} />
        </div>

        <div className="mt-4 flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => upsertMutation.mutate()}
            disabled={upsertMutation.isPending || selectedUserId === null}
          >
            <Save className="w-4 h-4" aria-hidden="true" />
            <span className="ml-1">Zapisz KPI</span>
          </Button>
          <Button variant="outline" size="sm" onClick={() => dashboardQuery.refetch()}>
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
          </Button>
          {saveStatus && (
            <div className={`text-sm flex items-center gap-1 ${saveStatus.type === "success" ? "text-emerald-600" : "text-rose-600"}`}>
              {saveStatus.type === "success" ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
              {saveStatus.msg}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function NumberInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="block text-xs text-muted-foreground mb-1">{label}</label>
      <input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md tabular-nums"
      />
    </div>
  );
}
