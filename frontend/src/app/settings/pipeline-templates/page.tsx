"use client";

import { PipelineTemplatesTab } from "@/components/settings/PipelineTemplatesTab";

export default function PipelineTemplatesPage() {
  return (
    <div className="min-h-screen bg-muted dark:bg-card">
      <div className="max-w-7xl mx-auto px-4 py-8">
        <PipelineTemplatesTab />
      </div>
    </div>
  );
}
