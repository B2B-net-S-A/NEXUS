"use client";

import { TeamSection } from "@/components/phone-preview/TeamSection";
import { seesAttention } from "@/components/phone-preview/access";
import { PageHeader } from "@/components/phone-preview/ui";
import { useAuthStore } from "@/store/auth";

export default function PhonePreviewTeamPage() {
  const user = useAuthStore((s) => s.user);
  return (
    <div className="pb-6">
      <PageHeader title="Zespół" sub="Tylko podgląd, bez kwot" />
      <TeamSection withAttention={seesAttention(user)} />
    </div>
  );
}
