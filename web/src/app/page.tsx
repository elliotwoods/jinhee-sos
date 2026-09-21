import { fromQuery } from "@/lib/filter";
import { DEFAULT_DATASET } from "@/lib/http";
import { snapshot } from "@/lib/inventory";
import { buildModel } from "@/lib/model";
import { getStore } from "@/lib/store";
import Inventory from "./Inventory";

export const dynamic = "force-dynamic";

const TABS = ["cubes", "computers", "zones", "activity"] as const;

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const params = await searchParams;
  const store = getStore();
  const [doc, presence, reports] = await Promise.all([
    snapshot(store, DEFAULT_DATASET),
    store.presence(DEFAULT_DATASET).catch(() => []),
    store.sightings(DEFAULT_DATASET).catch(() => []),
  ]);
  const model = buildModel(DEFAULT_DATASET, doc, presence, reports);
  const tab = TABS.find((t) => t === params.tab) ?? "cubes";
  return (
    <Inventory
      model={model}
      initial={{ filters: fromQuery(params), tab, cube: params.cube ?? null, activity: params.activity ?? "" }}
    />
  );
}
