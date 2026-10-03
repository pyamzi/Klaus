import { getConfigJson, setConfigJson } from "@generated/backend";

/** A Collection config value stored as JSON; `fallback` when it is unset. */
export async function getJson<T>(key: string, fallback: T): Promise<T> {
  const json = await getConfigJson({ val: key });
  return JSON.parse(new TextDecoder().decode(json.json)) ?? fallback;
}

export function setJson(key: string, value: unknown) {
  return setConfigJson({ key, valueJson: new TextEncoder().encode(JSON.stringify(value)), undoable: false });
}
