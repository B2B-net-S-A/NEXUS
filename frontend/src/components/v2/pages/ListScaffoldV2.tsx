"use client";

import * as React from"react";
import { Search } from"lucide-react";
import { cn } from"@/lib/utils";
import { Button } from"@/components/ui/button";
import { Input } from"@/components/ui/input";

/**
 * ListScaffoldV2 — shared header + toolbar pattern for v2 list pages
 * (Clients / Jobs / Contracts / Talents / Contacts).
 *
 * Wrap the entity-specific content (table, grid, filters) as children.
 * The scaffold handles:
 * - Dynaminds eyebrow + H1 + subtitle + action buttons (header)
 * - Optional search input (toolbar slot)
 * - Optional filter slot
 * - Consistent max-width + spacing
 *
 * Usage:
 * <ListScaffoldV2
 * eyebrow="Delivery · Klienci"
 * title="Klienci"
 * subtitle={`${total} firm`}
 * actions={<Button>Nowy klient</Button>}
 * search={{ value, onChange, placeholder:"…" }}
 * filters={<MyFilters />}
 * >
 * <MyTable />
 * </ListScaffoldV2>
 */

export interface ListScaffoldV2Props {
 /** Burgundy uppercase eyebrow above H1. */
 eyebrow: string;
 /** Main H1 title (Poppins extrabold). */
 title: string;
 /** Optional subtitle / count. */
 subtitle?: React.ReactNode;
 /** Buttons shown on the right side of the header. */
 actions?: React.ReactNode;
 /** Optional main search bar. */
 search?: {
 value: string;
 onChange: (v: string) => void;
 placeholder?: string;
 };
 /** Optional custom toolbar (select filters, etc.). Rendered next to search. */
 toolbar?: React.ReactNode;
 /** Optional banner above main content (e.g. expiring alerts). */
 banner?: React.ReactNode;
 /** Main content (table / grid / etc.). */
 children: React.ReactNode;
 /** Optional footer / bulk action area. */
 footer?: React.ReactNode;
 /** Container width override; default max-w-[1400px]. */
 maxWidthClass?: string;
}

export function ListScaffoldV2({
 eyebrow,
 title,
 subtitle,
 actions,
 search,
 toolbar,
 banner,
 children,
 footer,
 maxWidthClass ="max-w-[1400px]",
}: ListScaffoldV2Props) {
 return (
 <div className={cn("mx-auto space-y-4", maxWidthClass)}>
 {/* Header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 {eyebrow}
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-[-0.02em] text-foreground mt-1">
 {title}
 </h1>
 {subtitle !== undefined && (
 <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>
 )}
 </div>
 {actions && <div className="flex items-center gap-2">{actions}</div>}
 </div>

 {/* Banner slot */}
 {banner}

 {/* Toolbar: search + filters */}
 {(search || toolbar) && (
 <div className="flex items-center gap-2 flex-wrap">
 {search && (
 <div className="flex-1 min-w-[240px] max-w-lg">
 <Input
 leadingIcon={<Search className="h-4 w-4" />}
 placeholder={search.placeholder ??"Szukaj…"}
 value={search.value}
 onChange={(e) => search.onChange(e.target.value)}
 />
 </div>
 )}
 {toolbar}
 </div>
 )}

 {/* Main */}
 {children}

 {/* Footer */}
 {footer}
 </div>
 );
}

/**
 * SimplePagination — reusable pagination block for list pages.
 */
export interface SimplePaginationProps {
 page: number;
 totalPages: number;
 onChange: (page: number) => void;
 extra?: React.ReactNode;
}

export function SimplePagination({
 page,
 totalPages,
 onChange,
 extra,
}: SimplePaginationProps) {
 if (totalPages <= 1 && !extra) return null;
 return (
 <div className="flex items-center justify-between gap-3 text-sm">
 <span className="text-muted-foreground">
 Strona <strong className="text-foreground">{page}</strong> z{""}
 {totalPages}
 {extra && <>{" ·"}{extra}</>}
 </span>
 <div className="flex gap-2">
 <Button
 size="sm"
 variant="outline"
 disabled={page <= 1}
 onClick={() => onChange(Math.max(1, page - 1))}
 >
 Poprzednia
 </Button>
 <Button
 size="sm"
 variant="outline"
 disabled={page >= totalPages}
 onClick={() => onChange(page + 1)}
 >
 Następna
 </Button>
 </div>
 </div>
 );
}
