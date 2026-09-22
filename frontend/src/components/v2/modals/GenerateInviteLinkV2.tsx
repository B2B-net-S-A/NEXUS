"use client";

/**
 * Okno „Udostępnij rekrutację" (Kariera Dynaminds).
 *
 * Dwie zakładki: „Link do tej rekrutacji" (opis publiczny + kontrola przed
 * publikacją + link) i „Mój link ogólny" (stały adres rekrutera, statystyki,
 * widoczność rekrutacji, historia linków). Nazwa eksportu i propsy zostają
 * dotychczasowe — okno montuje pięć miejsc (QuickActions, lista rekrutacji,
 * lista kandydatów, karta rekrutacji, panel zamówienia).
 */

import { useCallback, useEffect, useState } from "react";
import { Share2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GeneralLinkTab } from "@/components/v2/career-share/GeneralLinkTab";
import { JobShareTab } from "@/components/v2/career-share/JobShareTab";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Wstępnie wybrana rekrutacja (np. okno otwarte z karty rekrutacji).
   * Użytkownik może ją zmienić.
   */
  defaultJobId?: number;
}

type ShareTab = "job" | "general";

export function GenerateInviteLinkV2({ open, onOpenChange, defaultJobId }: Props) {
  const [tab, setTab] = useState<ShareTab>("job");
  const [jobTitle, setJobTitle] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setTab("job");
      setJobTitle(null);
    }
  }, [open]);

  const handleJobChange = useCallback((title: string | null) => setJobTitle(title), []);

  const description =
    tab === "general"
      ? "Twój stały link do bazy — do profilu LinkedIn, stopki i postów."
      : jobTitle
        ? `${jobTitle} — nazwa klienta i stawki nie trafią na stronę.`
        : "Opis publiczny i link dla kandydatów — bez nazwy klienta i bez stawek.";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" aria-describedby="career-share-description">
        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as ShareTab)}
          className="flex min-h-0 flex-1 flex-col"
        >
          <DialogHeader className="gap-3 pb-0">
            <div className="space-y-1">
              <DialogTitle className="flex items-center gap-2">
                <Share2 className="h-5 w-5 text-primary" aria-hidden="true" />
                Udostępnij rekrutację
              </DialogTitle>
              <DialogDescription id="career-share-description">{description}</DialogDescription>
            </div>
            <TabsList className="border-b-0">
              <TabsTrigger value="job">Link do tej rekrutacji</TabsTrigger>
              <TabsTrigger value="general">Mój link ogólny</TabsTrigger>
            </TabsList>
          </DialogHeader>

          <TabsContent value="job" className="mt-0 flex min-h-0 flex-1 flex-col">
            <JobShareTab
              enabled={open && tab === "job"}
              defaultJobId={defaultJobId}
              onJobChange={handleJobChange}
            />
          </TabsContent>
          <TabsContent value="general" className="mt-0 flex min-h-0 flex-1 flex-col">
            <GeneralLinkTab enabled={open && tab === "general"} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
