"use client";

import { useParams } from "next/navigation";

import { TrainingDetailScreen } from "@/components/consultant-portal/TrainingDetail";

/** Panel konsultanta: szkolenie, które konsultant prowadzi jako trener. Link z maili prowadzi tutaj. */
export default function Page() {
  const params = useParams<{ id: string }>();
  return <TrainingDetailScreen id={Number(params.id)} />;
}
