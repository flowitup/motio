import { t } from "@/i18n";

/** Save a file the engine serves (`api.mediaUrl`) through the browser: works for a local and a remote engine, and never
 * navigates the app window away from itself. The file is read whole, which suits a 90 s video. */
export async function saveFile(url: string, name: string): Promise<void> {
  let r: Response;
  try {
    r = await fetch(url);
  } catch {
    throw new Error(t.common.noEngine);
  }
  if (!r.ok) throw new Error(r.status === 404 ? t.files.missing : r.statusText);
  const href = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 30_000);
}

/** A file name from a title: letters and digits kept (accents dropped), the rest becomes "-". */
export const fileSlug = (title: string, fallback: string) =>
  title
    .normalize("NFD")
    .replace(/\p{M}+/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || fallback;
