import { t } from "@/i18n";

/** fal picture models the owner can pick (Settings → AI pictures); mirrors `images.FAL_MODELS` in the engine. */
export const FAL_MODELS = ["qwen", "flux-schnell", "flux-dev", "flux-pro", "seedream"] as const;
export type FalModel = (typeof FAL_MODELS)[number];
/** Estimated USD per picture (1088×1920). */
export const FAL_PICTURE_USD: Record<FalModel, number> = {
  qwen: 0.042,
  "flux-schnell": 0.006,
  "flux-dev": 0.052,
  "flux-pro": 0.084,
  seedream: 0.03,
};
export const CLEARED_FAL_MODELS: FalModel[] = ["qwen"]; // the only model cleared for a monetized channel
const SCENES = 12; // a typical AI video

export const isFalModel = (m: string | undefined): m is FalModel => !!m && (FAL_MODELS as readonly string[]).includes(m);

/** The engine's provider name for the settings: `fal`, `fal:<model>`, `modal` or `placeholder`. */
export function providerName(provider: string | undefined, model: string | undefined): string {
  const p = provider || "fal";
  return p === "fal" && isFalModel(model) && model !== "qwen" ? `fal:${model}` : p;
}

/** Estimated picture cost of a 12-scene video for a provider name, as a string like "0.50". */
export function videoPicturesUsd(name: string): string {
  if (name === "modal") return "0.11";
  if (name === "placeholder") return "0";
  const m = name.startsWith("fal:") ? name.slice(4) : "qwen";
  return (SCENES * (isFalModel(m) ? FAL_PICTURE_USD[m] : FAL_PICTURE_USD.qwen)).toFixed(2);
}

/** A provider name (`fal`, `fal:<model>`, `modal`…) as the UI language words it. */
export function imageProviderLabel(name: string): string {
  if (name.startsWith("fal:")) {
    const m = name.slice(4);
    return isFalModel(m) ? `fal (${t.ai.falModels[m]})` : name;
  }
  return t.ai.providers[name] ?? name;
}
