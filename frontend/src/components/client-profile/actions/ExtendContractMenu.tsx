"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";

interface Props {
  contractId: number;
  clientId: number;
}

const DURATIONS = [3, 6, 12];

export function ExtendContractMenu({ contractId, clientId }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const mutation = useMutation({
    mutationFn: (months: number) =>
      api.post(
        `/api/contracts/bulk-extend?ids=${contractId}&months=${months}`,
        {}
      ),
    onSuccess: (_data, months) => {
      queryClient.invalidateQueries({ queryKey: ["client-profile", clientId] });
      queryClient.invalidateQueries({ queryKey: ["client-contracts", clientId] });
      showSuccess(`Kontrakt przedłużony o ${months} mc`);
      setOpen(false);
    },
    onError: () => showError("Nie udało się przedłużyć kontraktu"),
  });

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={mutation.isPending}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-900/30 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 rounded-md transition-colors disabled:opacity-50"
      >
        {mutation.isPending ? "..." : "Extend"}
        <ChevronDown className="w-3 h-3" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 bg-card dark:bg-muted border border-border dark:border-border rounded-lg shadow-lg z-10 min-w-[120px] py-1">
          {DURATIONS.map((m) => (
            <button
              key={m}
              onClick={() => mutation.mutate(m)}
              className={cn(
                "block w-full text-left px-3 py-1.5 text-xs hover:bg-emerald-50 dark:hover:bg-emerald-900/30 text-foreground dark:text-muted-foreground"
              )}
            >
              + {m} miesięcy
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
