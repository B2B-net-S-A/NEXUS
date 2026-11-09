import { redirect } from "next/navigation";

import { salesLandingPath, type SalesSearchParams } from "@/components/sales/my-day";

export default async function SalesIndexPage({
  searchParams,
}: {
  searchParams: Promise<SalesSearchParams>;
}) {
  redirect(salesLandingPath(await searchParams));
}
