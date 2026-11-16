import type { PositionSource, StatementAccount, StatementNode } from "@/lib/api/accounting-reports";

/** Skąd pozycja konta (K8a): wpis przy koncie, przy koncie nadrzędnym, reguła po numerze. */
export const SOURCE_LABELS: Record<PositionSource, string> = {
  own: "wpis przy koncie",
  parent: "z konta nadrzędnego",
  rule: "reguła po numerze",
  excluded: "poza sprawozdaniem",
  none: "do wskazania",
};

export interface FlatRow {
  key: string;
  number: string;
  label: string;
  level: number;
  amount: number;
  accounts: StatementAccount[];
  computed: boolean;
}

/**
 * Drzewo sprawozdania → wiersze tabeli. Bez „wszystkich pozycji” zostają
 * pozycje główne (A, B…, wyniki C, F, I, L) i każda z kwotą — puste
 * podpozycje załącznika tylko zaciemniają ekran.
 */
export function flattenStatement(nodes: StatementNode[], all: boolean, parent = ""): FlatRow[] {
  const out: FlatRow[] = [];
  for (const node of nodes) {
    const key = `${parent}/${node.number}-${node.label}`;
    if (!all && node.level > 1 && node.amount === 0) continue;
    out.push({
      key,
      number: node.number,
      label: node.label,
      level: node.level,
      amount: node.amount,
      accounts: node.accounts,
      computed: Boolean(node.computed),
    });
    out.push(...flattenStatement(node.children, all, key));
  }
  return out;
}

/** Wybór z dwóch list → wartość `report_line` („KOD” albo „KOD_Wn/KOD_Ma”). */
export function reportLine(debit: string, credit: string): string | null {
  if (!debit) return null;
  return credit && credit !== debit ? `${debit}/${credit}` : debit;
}

/** „Aktywa obrotowe · … · Z tytułu dostaw i usług · o okresie spłaty do 12 miesięcy” → dwa ostatnie człony. */
export function shortLabel(label: string): string {
  return label.split(" · ").slice(-2).join(" · ");
}
