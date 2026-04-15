import React, { ReactNode, useState, memo, useMemo } from "react";
import { ChevronLeft, ChevronRight, ChevronUp, ChevronDown, Download, Loader2 } from "lucide-react";

interface Column<T = any> {
  key: string;
  label: string;
  sortable?: boolean;
  render?: (row: T) => ReactNode;
  csvValue?: (row: T) => string;
}

interface DataTableProps<T = any> {
  columns: Column<T>[];
  data: T[];
  loading?: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  onRowClick?: (row: T) => void;
  csvFilename?: string;
  showCsvExport?: boolean;
}

// Memoized row to avoid re-rendering unchanged rows during pagination/sort
const TableRow = memo(function TableRow<T>({
  row,
  index,
  columns,
  onRowClick,
}: {
  row: T;
  index: number;
  columns: Column<T>[];
  onRowClick?: (row: T) => void;
}) {
  return (
    <tr
      onClick={() => onRowClick?.(row)}
      className={`border-b border-gray-50 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${
        onRowClick ? "cursor-pointer" : ""
      }`}
    >
      {columns.map((col) => (
        <td key={col.key} className="px-4 py-3 text-gray-700 dark:text-gray-300">
          {col.render ? col.render(row) : (row as any)[col.key] ?? "—"}
        </td>
      ))}
    </tr>
  );
}) as <T>(props: { row: T; index: number; columns: Column<T>[]; onRowClick?: (row: T) => void }) => React.ReactElement;

export function DataTable<T extends { id?: number | string }>({
  columns,
  data,
  loading,
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  onRowClick,
  csvFilename = "export.csv",
  showCsvExport = false,
}: DataTableProps<T>) {
  const totalPages = Math.ceil(total / pageSize);
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sortedData = useMemo(
    () =>
      sortKey
        ? [...data].sort((a, b) => {
            const av = (a as any)[sortKey];
            const bv = (b as any)[sortKey];
            if (av == null) return 1;
            if (bv == null) return -1;
            const cmp = String(av).localeCompare(String(bv), "pl", { numeric: true });
            return sortDir === "asc" ? cmp : -cmp;
          })
        : data,
    [data, sortKey, sortDir],
  );

  const handleExportCsv = () => {
    const headerRow = columns.map((c) => `"${c.label}"`).join(",");
    const rows = sortedData.map((row) =>
      columns
        .map((c) => {
          const val = c.csvValue
            ? c.csvValue(row)
            : ((row as any)[c.key] ?? "");
          return `"${String(val).replace(/"/g, '""')}"`;
        })
        .join(",")
    );
    const csvContent = [headerRow, ...rows].join("\r\n");
    const blob = new Blob(["\uFEFF" + csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = csvFilename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      {showCsvExport && (
        <div className="flex justify-end px-4 py-2 border-b border-gray-100 dark:border-gray-700">
          <button
            onClick={handleExportCsv}
            title="Eksportuj do CSV"
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-300 transition-colors"
          >
            <Download className="w-4 h-4" />
            Eksport CSV
          </button>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
              {columns.map((col) => (
                <th
                  key={col.key}
                  onClick={() => col.sortable && handleSort(col.key)}
                  title={col.sortable ? `Sortuj po: ${col.label}` : undefined}
                  className={`text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap select-none ${
                    col.sortable ? "cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors" : ""
                  }`}
                >
                  <span className="flex items-center gap-1">
                    {col.label}
                    {col.sortable && (
                      <span className="flex flex-col">
                        <ChevronUp
                          className={`w-3 h-3 -mb-0.5 ${
                            sortKey === col.key && sortDir === "asc"
                              ? "text-blue-600"
                              : "text-gray-300 dark:text-gray-600"
                          }`}
                        />
                        <ChevronDown
                          className={`w-3 h-3 -mt-0.5 ${
                            sortKey === col.key && sortDir === "desc"
                              ? "text-blue-600"
                              : "text-gray-300 dark:text-gray-600"
                          }`}
                        />
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="text-center py-12 text-gray-400">
                  <Loader2 className="w-5 h-5 animate-spin mx-auto" />
                </td>
              </tr>
            ) : sortedData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="text-center py-12 text-gray-400 dark:text-gray-500">
                  Brak wyników
                </td>
              </tr>
            ) : (
              sortedData.map((row, i) => (
                <TableRow
                  key={(row as any).id ?? i}
                  row={row}
                  index={i}
                  columns={columns}
                  onRowClick={onRowClick}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {total === 0 ? "Brak wyników" : `Wyświetlono ${from}–${to} z ${total}`}
          </span>
          {onPageSizeChange && (
            <select
              value={pageSize}
              onChange={(e) => {
                onPageSizeChange(Number(e.target.value));
                onPageChange(1);
              }}
              className="text-xs border border-gray-200 dark:border-gray-600 rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white dark:bg-gray-700 dark:text-gray-200"
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
            </select>
          )}
        </div>
        {totalPages > 1 && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
              title="Poprzednia strona"
              className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-600 dark:text-gray-400"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-xs px-2 text-gray-600 dark:text-gray-400">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
              title="Następna strona"
              className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-600 dark:text-gray-400"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
