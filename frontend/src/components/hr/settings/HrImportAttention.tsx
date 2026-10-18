"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { HrImportModuleReport } from "@/lib/api/hr-import";

/**
 * Pozycje do wyjaśnienia i konflikty — zwinięte, bo bywa ich setki (statusy
 * obecności, które import świadomie pomija). Najpierw powody z liczbami,
 * potem identyfikatory Compassa; e-mail osoby widzi tylko administrator.
 */
export function HrImportAttention({ modules }: { modules: HrImportModuleReport[] }) {
  const [open, setOpen] = useState(false);
  const withItems = modules.filter((module) => module.attention_total > 0);
  const total = withItems.reduce((sum, module) => sum + module.attention_total, 0);
  if (total === 0) {
    return <p className="text-sm text-muted-foreground">Nic do wyjaśnienia.</p>;
  }

  return (
    <div className="rounded-lg border border-border">
      <Button
        variant="ghost"
        className="w-full justify-start gap-2"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? (
          <ChevronDown className="h-4 w-4" aria-hidden />
        ) : (
          <ChevronRight className="h-4 w-4" aria-hidden />
        )}
        Do wyjaśnienia i konflikty ({total})
      </Button>
      {open ? (
        <div className="max-h-[50dvh] space-y-4 overflow-y-auto border-t border-border p-4 text-sm">
          {withItems.map((module) => {
            const items = module.attention ?? [];
            return (
              <section key={module.module} aria-label={`Do wyjaśnienia: ${module.label}`}>
                <h3 className="font-medium text-foreground">
                  {module.label} · {module.attention_total}
                </h3>
                <ul className="mt-1 text-xs text-muted-foreground">
                  {Object.entries(module.reasons).map(([reason, count]) => (
                    <li key={reason}>
                      {reason} — {count}
                    </li>
                  ))}
                </ul>
                <ul className="mt-2 divide-y divide-border/60">
                  {items.map((item) => (
                    <li
                      key={item.source_id}
                      className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5"
                    >
                      <span className="text-foreground">{item.reason}</span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {item.source_id}
                      </span>
                      {item.email ? (
                        <span className="text-xs text-muted-foreground">{item.email}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
                {module.attention_total > items.length ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Pokazano {items.length} z {module.attention_total} — pełna lista jest
                    w partii modułu.
                  </p>
                ) : null}
              </section>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
