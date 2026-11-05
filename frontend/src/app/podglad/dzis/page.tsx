"use client";

import { TodaySection } from "@/components/phone-preview/TodaySection";
import { seesWholeTeam } from "@/components/phone-preview/access";
import { PageHeader } from "@/components/phone-preview/ui";
import { useAuthStore } from "@/store/auth";

export default function PhonePreviewTodayPage() {
  const user = useAuthStore((s) => s.user);
  return (
    <div className="pb-6">
      <PageHeader title="Dziś" sub="Tylko podgląd" />
      <TodaySection whole={seesWholeTeam(user)} />
    </div>
  );
}
