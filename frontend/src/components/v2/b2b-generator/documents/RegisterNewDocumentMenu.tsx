"use client";

// Menu „Nowy dokument” w wierszu rejestru umów: rodzaj dokumentu prowadzi do
// kreatora z tą umową jako bazową (`?tab=documents&new=<typ>&parent=<id>`),
// a „Zarejestruj wypowiedzenie Partnera” otwiera okno bez dokumentu.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { FilePlus2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { b2bDocumentsApi, b2bDocumentsKeys } from "@/lib/api/b2bDocuments";
import { documentsHref, typesByFamily } from "@/lib/b2b-documents";

import { PartnerNoticeDialog } from "./DocumentDialogs";

export interface RegisterNewDocumentMenuProps {
  row: {
    id: number;
    contract_number: string;
    partner_name: string | null;
  };
}

export function RegisterNewDocumentMenu({ row }: RegisterNewDocumentMenuProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [noticeOpen, setNoticeOpen] = useState(false);
  // Definicje dopiero po otwarciu menu — rejestr ma setki wierszy.
  const types = useQuery({
    queryKey: b2bDocumentsKeys.types(),
    queryFn: b2bDocumentsApi.types,
    enabled: open,
    staleTime: 10 * 60_000,
  });
  // Umowa przedwstępna poprzedza umowę — z wiersza rejestru nie ma sensu.
  const groups = typesByFamily(
    (types.data?.types ?? []).filter((t) => t.parent !== "none"),
  );
  return (
    <>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            title="Nowy dokument do tej umowy"
            aria-label={`Nowy dokument do umowy ${row.contract_number}`}
          >
            <FilePlus2 className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          {types.isPending ? (
            <div className="flex items-center gap-2 px-2 py-1.5 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Wczytuję…
            </div>
          ) : types.isError ? (
            <div className="px-2 py-1.5 text-sm text-destructive">
              Nie udało się wczytać rodzajów dokumentów.
            </div>
          ) : (
            groups.map((group) => (
              <div key={group.family}>
                <DropdownMenuLabel className="text-xs text-muted-foreground">
                  {group.label}
                </DropdownMenuLabel>
                {group.types.map((t) => (
                  <DropdownMenuItem
                    key={t.key}
                    onSelect={() =>
                      router.push(documentsHref({ newType: t.key, parentId: row.id }), {
                        scroll: false,
                      })
                    }
                  >
                    {t.label}
                  </DropdownMenuItem>
                ))}
              </div>
            ))
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setNoticeOpen(true)}>
            Zarejestruj wypowiedzenie Partnera
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {noticeOpen ? (
        <PartnerNoticeDialog
          parentId={row.id}
          contractNumber={row.contract_number}
          partnerName={row.partner_name}
          onClose={() => setNoticeOpen(false)}
        />
      ) : null}
    </>
  );
}
