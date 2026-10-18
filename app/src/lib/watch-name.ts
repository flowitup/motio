import { t } from "@/i18n";

/** A trending target ("bilibili:ranking:181", "bilibili:category:ai", "bilibili:tag:礼仪") named in the UI language. */
export function listName(target: string): string | undefined {
  const fixed = t.watches.lists[target];
  if (fixed) return fixed;
  const tag = target.match(/^bilibili:tag:(.+)$/);
  return tag ? t.watches.tagName(tag[1]) : undefined;
}

export const isCategory = (target?: string | null) => !!target && /^(bilibili:(category|tag):|(kuaishou:featured|douyin:feed|weibo:hot)$)/.test(target);
