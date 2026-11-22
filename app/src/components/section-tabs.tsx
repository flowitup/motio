import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router";
import { Segmented } from "@/components/studio";
import { useApi } from "@/lib/api";
import { t, type Messages } from "@/i18n";

/** One menu entry that holds several pages as tabs: the pages keep their own routes (links and bookmarks still work). */
export type SectionKey = "discover" | "tools";
type Tab = { to: string; label: keyof Messages["nav"] };

export const SECTIONS: Record<SectionKey, { home: string; tabs: Tab[] }> = {
  discover: {
    home: "/trends",
    tabs: [
      { to: "/trends", label: "trends" },
      { to: "/news", label: "news" }, // only while NEWS_TOPICS is on
      { to: "/clips", label: "clips" },
      { to: "/scan", label: "scan" },
    ],
  },
  tools: {
    home: "/tools",
    tabs: [
      { to: "/tools", label: "quickJobs" },
      { to: "/delogo", label: "delogo" },
    ],
  },
};

/** The tab whose route holds `pathname` (`/clips/12` is the Followed tab), if any. */
function tabFor(section: SectionKey, pathname: string) {
  return SECTIONS[section].tabs.find((tab) => pathname === tab.to || pathname.startsWith(`${tab.to}/`));
}

/** True while `pathname` is a page of the section: the menu entry is lit. */
export function inSection(section: SectionKey, pathname: string) {
  return !!tabFor(section, pathname);
}

/** The tab strip a page of a section shows next to its title. */
export function SectionTabs({ section }: { section: SectionKey }) {
  const api = useApi();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { data: state } = useQuery({ queryKey: ["state"], queryFn: () => api!.state(), enabled: !!api, refetchInterval: 30_000 });
  const tabs = SECTIONS[section].tabs.filter((tab) => tab.to !== "/news" || !!state?.news_topics);
  const current = tabFor(section, pathname)?.to ?? tabs[0].to;
  return (
    <Segmented
      tabs
      label={t.nav[section]}
      value={current}
      onChange={(to) => navigate(to)}
      options={tabs.map((tab) => ({ value: tab.to, label: t.nav[tab.label] }))}
      className="h-9 shrink-0"
    />
  );
}
