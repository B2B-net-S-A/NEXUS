import { cookies } from "next/headers";
import { readUiFlagFromCookies } from "@/lib/ui-flag";
import { JobsPageV1 } from "@/components/v1/JobsPageV1";
import { JobsListV2 } from "@/components/v2/pages/JobsListV2";

export default async function JobsPage() {
  const cookieStore = await cookies();
  const ui = readUiFlagFromCookies(cookieStore);
  return ui === "v2" ? <JobsListV2 /> : <JobsPageV1 />;
}
