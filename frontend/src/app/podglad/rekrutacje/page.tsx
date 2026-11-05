"use client";

import { RecruitmentsSection } from "@/components/phone-preview/RecruitmentsSection";
import { seesAllRecruitments } from "@/components/phone-preview/access";
import { PageHeader } from "@/components/phone-preview/ui";
import { useAuthStore } from "@/store/auth";

export default function PhonePreviewRecruitmentsPage() {
  const user = useAuthStore((s) => s.user);
  return (
    <div className="pb-6">
      <PageHeader title="Rekrutacje" sub="Tylko podgląd" />
      <RecruitmentsSection all={seesAllRecruitments(user)} />
    </div>
  );
}
