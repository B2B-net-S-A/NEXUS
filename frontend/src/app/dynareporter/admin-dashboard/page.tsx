"use client";

/**
 * DynaReporter Admin Panel – port z artur-t-96/InfraReporter.
 *
 * Sales + Przetargi są usunięte (per user 2026-05-19) – Nexus nie ma
 * top-level dashboardów Sales / Przetargi, więc admin entry dla tych
 * modułów nie ma sensu.
 *
 * Modules (10 zaimplementowane):
 *  1. body_leasing – KPI działu Rekrutacja
 *  2. delivery_lead – Hit Ratio i Placements
 *  3. board_data – Dane miesięczne Rady Nadzorczej
 *  4. employees – Lista userów + seniority + toggle active
 *  5. recruitment_team – Members + TAC↔DL + Sourcer↔Category
 *  6. dl_clients – Delivery Lead ↔ Klient assignments
 *  7. master_data – Centralna baza klientów + konsultantów
 *  8. hall_of_fame – Zarządzanie zwycięzcami
 *  9. settings – Champions League scoring config
 * 10. history – Upload history + audit log
 *
 * Tylko rola `admin` może wyświetlać.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  FileSpreadsheet,
  Building2,
  Target,
  DollarSign,
  Users,
  Database,
  Trophy,
  Settings,
  History,
  Upload,
} from "lucide-react";
import {
  dynareporterAdminApi,
} from "@/lib/api";
import { useAuthStore, hasRole } from "@/store/auth";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BodyLeasingDataEntry } from "./_modules/BodyLeasingDataEntry";
import { BoardDataEntry } from "./_modules/BoardDataEntry";
import { DeliveryLeadDataEntry } from "./_modules/DeliveryLeadDataEntry";
import { ScoringConfig } from "./_modules/ScoringConfig";
import { HallOfFameManager } from "./_modules/HallOfFameManager";
import { MasterDataManager } from "./_modules/MasterDataManager";
import { EmployeesManager } from "./_modules/EmployeesManager";
import { RecruitmentTeamManager } from "./_modules/RecruitmentTeamManager";
import { DLClientManager } from "./_modules/DLClientManager";

// Sales + Przetargi usunięte z Admin DR (per user request 2026-05-19) – nie mamy
// głównych dashboardów Sales / Przetargi w Nexusie, więc admin entry dla nich
// nie jest potrzebny. SalesDataEntry.tsx + PrzetargiDataEntry.tsx zachowane na
// dysku ale nie wpięte tutaj – można usunąć w follow-up cleanup.

type ModuleType =
  | "body_leasing"
  | "delivery_lead"
  | "board_data"
  | "employees"
  | "recruitment_team"
  | "dl_clients"
  | "master_data"
  | "hall_of_fame"
  | "settings"
  | "history";

type ModuleCard = {
  type: ModuleType;
  title: string;
  description: string;
  color: "blue" | "green" | "orange" | "indigo" | "purple" | "amber" | "teal" | "cyan" | "violet" | "yellow" | "gray" | "rose";
  icon: React.ComponentType<{ className?: string }>;
};

const MODULE_CARDS: ModuleCard[] = [
  { type: "body_leasing", title: "Rekrutacja", description: "KPI działu Rekrutacja", color: "blue", icon: Building2 },
  { type: "delivery_lead", title: "Delivery Lead", description: "Hit Ratio i Placements", color: "orange", icon: Target },
  { type: "board_data", title: "Rada Nadzorcza", description: "Dane miesięczne dla Rady", color: "purple", icon: DollarSign },
  { type: "employees", title: "Pracownicy i konta", description: "Zarządzanie pracownikami i kontami", color: "amber", icon: Users },
  { type: "recruitment_team", title: "Zespół Rekrutacji", description: "Przypisania sourcerów i TAC", color: "teal", icon: Users },
  { type: "dl_clients", title: "DL - Klienci", description: "Przypisania DL do klientów", color: "cyan", icon: Building2 },
  { type: "master_data", title: "Klienci i Konsultanci", description: "Centralna baza danych", color: "violet", icon: Database },
  { type: "hall_of_fame", title: "Hall of Fame", description: "Zarządzanie zwycięzcami", color: "yellow", icon: Trophy },
  { type: "settings", title: "Ustawienia", description: "Konfiguracja systemu", color: "gray", icon: Settings },
  { type: "history", title: "Historia uploadów", description: "Audit log + uploads", color: "rose", icon: History },
];

// Mapowanie color → Tailwind classes (1:1 z DR).
const COLOR_CLASSES: Record<ModuleCard["color"], { border: string; bg: string; text: string; iconText: string }> = {
  blue: { border: "border-blue-500", bg: "bg-blue-50 dark:bg-blue-900/20", text: "text-blue-700 dark:text-blue-300", iconText: "text-blue-600" },
  green: { border: "border-green-500", bg: "bg-green-50 dark:bg-green-900/20", text: "text-green-700 dark:text-green-300", iconText: "text-green-600" },
  orange: { border: "border-orange-500", bg: "bg-orange-50 dark:bg-orange-900/20", text: "text-orange-700 dark:text-orange-300", iconText: "text-orange-600" },
  indigo: { border: "border-indigo-500", bg: "bg-indigo-50 dark:bg-indigo-900/20", text: "text-indigo-700 dark:text-indigo-300", iconText: "text-indigo-600" },
  purple: { border: "border-purple-500", bg: "bg-purple-50 dark:bg-purple-900/20", text: "text-purple-700 dark:text-purple-300", iconText: "text-purple-600" },
  amber: { border: "border-amber-500", bg: "bg-amber-50 dark:bg-amber-900/20", text: "text-amber-700 dark:text-amber-300", iconText: "text-amber-600" },
  teal: { border: "border-teal-500", bg: "bg-teal-50 dark:bg-teal-900/20", text: "text-teal-700 dark:text-teal-300", iconText: "text-teal-600" },
  cyan: { border: "border-cyan-500", bg: "bg-cyan-50 dark:bg-cyan-900/20", text: "text-cyan-700 dark:text-cyan-300", iconText: "text-cyan-600" },
  violet: { border: "border-violet-500", bg: "bg-violet-50 dark:bg-violet-900/20", text: "text-violet-700 dark:text-violet-300", iconText: "text-violet-600" },
  yellow: { border: "border-yellow-500", bg: "bg-yellow-50 dark:bg-yellow-900/20", text: "text-yellow-700 dark:text-yellow-300", iconText: "text-yellow-600" },
  gray: { border: "border-gray-500", bg: "bg-gray-50 dark:bg-gray-900/20", text: "text-gray-700 dark:text-gray-300", iconText: "text-gray-600" },
  rose: { border: "border-rose-500", bg: "bg-rose-50 dark:bg-rose-900/20", text: "text-rose-700 dark:text-rose-300", iconText: "text-rose-600" },
};

function formatDate(d: string): string {
  try {
    return new Date(d).toLocaleString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return d;
  }
}

export default function AdminDashboardPage() {
  const { user, hydrated } = useAuthStore();
  const [activeModule, setActiveModule] = useState<ModuleType>("body_leasing");

  if (!hydrated) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie sesji…</div>;
  }
  if (!user) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Zaloguj się żeby zobaczyć DynaReporter Admin.
      </div>
    );
  }
  // Multi-role aware – `hasRole` sprawdza primary + secondary roles
  // (multi-role schema z PR #207). Bez tego user z secondary=admin
  // (np. po AAD group sync) by był blokowany mimo posiadania uprawnień.
  if (!hasRole(user, "admin")) {
    return (
      <div className="p-8">
        <Card>
          <CardContent className="py-8">
            <h2 className="font-semibold text-destructive">Brak dostępu</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              DynaReporter Admin wymaga roli <code>admin</code>. Twoja rola:{" "}
              <code>{user.role}</code>.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 sm:p-6">
      {/* Header – gradient match DR */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-foreground flex items-center gap-2">
          <FileSpreadsheet className="w-7 h-7" />
          Panel Admina – Zarządzanie Danymi
        </h2>
      </div>

      {/* Module Selector – 11 cards w grid 2/4 col, color-coded selection (1:1 z DR) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 sm:gap-4">
        {MODULE_CARDS.map((card) => {
          const Icon = card.icon;
          const cs = COLOR_CLASSES[card.color];
          const isActive = activeModule === card.type;
          return (
            <button
              key={card.type}
              onClick={() => setActiveModule(card.type)}
              aria-pressed={isActive}
              aria-label={`${card.title}: ${card.description}`}
              className={`p-4 rounded-xl border-2 transition-all text-left ${
                isActive
                  ? `${cs.border} ${cs.bg}`
                  : "border-border hover:border-border/80 bg-card"
              }`}
            >
              <div className="flex items-center gap-3 mb-2">
                <Icon
                  className={`w-6 h-6 ${
                    isActive ? cs.iconText : "text-muted-foreground"
                  }`}
                />
                <span
                  className={`font-semibold ${
                    isActive ? "text-foreground" : "text-foreground/70"
                  }`}
                >
                  {card.title}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">{card.description}</p>
            </button>
          );
        })}
      </div>

      {/* Module content */}
      {activeModule === "body_leasing" && <BodyLeasingDataEntry />}
      {activeModule === "board_data" && <BoardDataEntry />}
      {activeModule === "delivery_lead" && <DeliveryLeadDataEntry />}
      {activeModule === "settings" && <ScoringConfig />}
      {activeModule === "hall_of_fame" && <HallOfFameManager />}
      {activeModule === "master_data" && <MasterDataManager />}
      {activeModule === "history" && <HistorySection />}
      {activeModule === "employees" && <EmployeesManager />}
      {activeModule === "recruitment_team" && <RecruitmentTeamManager />}
      {activeModule === "dl_clients" && <DLClientManager />}
    </div>
  );
}


function HistorySection() {
  const uploadsQuery = useQuery({
    queryKey: ["dr-admin-uploads"],
    queryFn: () => dynareporterAdminApi.uploadHistory(),
    staleTime: 60_000,
  });
  const auditQuery = useQuery({
    queryKey: ["dr-admin-audit"],
    queryFn: () => dynareporterAdminApi.auditLog(),
    staleTime: 60_000,
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
            <Upload className="w-5 h-5" />
            Upload history ({uploadsQuery.data?.length ?? "…"})
          </h3>
          {uploadsQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
          ) : uploadsQuery.error ? (
            <p className="text-sm text-destructive py-6 text-center">
              Błąd ładowania upload history.
            </p>
          ) : uploadsQuery.data?.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              Brak uploadów w bazie.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-muted/40">
                  <tr>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Plik
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Typ
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Uploadowany przez
                    </th>
                    <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                      Rekordów
                    </th>
                    <th className="px-3 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Status
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Data
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {(uploadsQuery.data ?? []).map((u) => (
                    <tr key={u.id} className="hover:bg-muted/40">
                      <td className="px-3 py-2 text-sm font-medium">{u.file_name}</td>
                      <td className="px-3 py-2 text-sm">
                        <Badge variant="neutral" size="sm">
                          {u.file_type}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-sm text-muted-foreground">
                        {u.uploaded_by_name}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-sm">
                        {u.records_count}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <Badge
                          variant={u.status === "success" ? "success" : "danger"}
                          size="sm"
                        >
                          {u.status}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {formatDate(u.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
            <History className="w-5 h-5" />
            Audit log ({auditQuery.data?.length ?? "…"})
          </h3>
          {auditQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
          ) : auditQuery.error ? (
            <p className="text-sm text-destructive py-6 text-center">
              Błąd ładowania audit log.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-muted/40">
                  <tr>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Tabela
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Akcja
                    </th>
                    <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                      Rekordów
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Przez
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Kiedy
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {(auditQuery.data ?? []).map((a) => (
                    <tr key={a.id} className="hover:bg-muted/40">
                      <td className="px-3 py-2 text-sm font-mono">{a.table_name}</td>
                      <td className="px-3 py-2 text-sm">
                        <Badge
                          variant={a.action.includes("DELETE") ? "danger" : "neutral"}
                          size="sm"
                        >
                          {a.action}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-sm">
                        {a.records_count}
                      </td>
                      <td className="px-3 py-2 text-sm text-muted-foreground">
                        {a.performed_by_name ?? "–"}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {formatDate(a.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
