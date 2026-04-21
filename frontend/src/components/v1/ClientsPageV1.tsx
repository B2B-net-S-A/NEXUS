"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { DataTable } from "@/components/DataTable";
import { SearchBar } from "@/components/SearchBar";
import { AddClientModal } from "@/components/AppShell";
import { RequireRole } from "@/components/RequireRole";
import { Building2, Plus, CheckCircle, XCircle } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  inactive: "bg-gray-100 text-gray-600",
  prospect: "bg-blue-100 text-blue-700",
};

export function ClientsPageV1() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [showAddModal, setShowAddModal] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["clients", search, page, pageSize],
    queryFn: () =>
      api.get("/api/clients", { params: { q: search || undefined, page, page_size: pageSize } }).then((r) => r.data),
  });

  const columns = [
    { key: "name", label: "Firma", sortable: true },
    { key: "industry", label: "Branża", sortable: true },
    { key: "contact_person", label: "Kontakt" },
    { key: "contact_email", label: "Email" },
    {
      key: "status",
      label: "Status",
      sortable: true,
      render: (row: any) => (
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[row.status] || ""}`}>
          {row.status}
        </span>
      ),
      csvValue: (row: any) => row.status,
    },
    {
      key: "nda_signed",
      label: "NDA",
      render: (row: any) =>
        row.nda_signed ? (
          <CheckCircle className="w-4 h-4 text-green-500" />
        ) : (
          <XCircle className="w-4 h-4 text-gray-300" />
        ),
      csvValue: (row: any) => row.nda_signed ? "Tak" : "Nie",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold dark:text-gray-100">Klienci</h1>
          <p className="text-sm text-gray-500">{data?.total ?? 0} firm</p>
        </div>
        {/* TacPlus guard — create client wymaga admin/delivery_lead/tac. */}
        <RequireRole roles={["admin", "delivery_lead", "tac"]}>
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium"
          >
            <Plus className="w-4 h-4" />
            Nowy klient
          </button>
          {showAddModal && (
            <AddClientModal
              onClose={() => setShowAddModal(false)}
              onSuccess={() => {
                queryClient.invalidateQueries({ queryKey: ["clients"] });
                setShowAddModal(false);
              }}
            />
          )}
        </RequireRole>
      </div>

      <SearchBar value={search} onChange={setSearch} placeholder="Szukaj klientów..." />

      <DataTable
        columns={columns}
        data={data?.items ?? []}
        loading={isLoading}
        page={page}
        pageSize={pageSize}
        total={data?.total ?? 0}
        onPageChange={setPage}
        onPageSizeChange={setPageSize}
        onRowClick={(row) => router.push(`/clients/${row.id}`)}
        showCsvExport
        csvFilename="klienci.csv"
      />
    </div>
  );
}
