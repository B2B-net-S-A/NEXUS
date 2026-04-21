import { cookies } from "next/headers";
import { readUiFlagFromCookies } from "@/lib/ui-flag";
import { DashboardV1 } from "@/components/v1/DashboardV1";
import { DashboardV2 } from "@/components/v2/pages/DashboardV2";

export default async function DashboardPage() {
  const cookieStore = await cookies();
  const ui = readUiFlagFromCookies(cookieStore);
  return ui === "v2" ? <DashboardV2 /> : <DashboardV1 />;
}
