import { useQuery } from "@tanstack/react-query";
import { OctagonAlert, TriangleAlert } from "lucide-react";
import { Link } from "react-router";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

/** What Motio needs before it can make a video, read from the engine's health: Claude, a voice, FFmpeg. Nothing when all is set. */
export function SetupCard({ className }: { className?: string }) {
  const api = useApi()!;
  const { data: h } = useQuery({ queryKey: ["health"], queryFn: () => api.health(), refetchInterval: 30_000, staleTime: 15_000 });
  if (!h) return null;
  const missing: { id: string; title: string; text: string }[] = [];
  if (h.providers.llm.key === false) missing.push({ id: "llm", ...t.setup.llm });
  if (!h.providers.tts) missing.push({ id: "tts", ...t.setup.tts });
  if (!h.ffmpeg) missing.push({ id: "ffmpeg", ...t.setup.ffmpeg });
  if (!missing.length) return null;
  return (
    <section aria-label={t.setup.title} className={cn("shrink-0 border-b border-amber/60 bg-amber/8", className)}>
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3 px-6 py-3">
        <div className="flex min-w-0 flex-1 basis-[22rem] items-start gap-3">
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-amber" aria-hidden />
          <div className="min-w-0 space-y-1.5">
            <h2 className="text-[15px] leading-[22px] font-semibold">{t.setup.title}</h2>
            <ul className="space-y-1">
              {missing.map((m) => (
                <li key={m.id} className="text-[13px] leading-5">
                  <span className="font-semibold">{m.title}</span>
                  <span className="text-muted-foreground"> · {m.text}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <Link to="/settings" className="inline-flex h-10 items-center font-medium">
          {t.setup.open}
        </Link>
      </div>
    </section>
  );
}

/** The month's spending is at 80 % of the budget set in Settings, or over it (the Stats numbers, shown where videos are started). */
export function BudgetNotice({ className }: { className?: string }) {
  const api = useApi()!;
  const { data } = useQuery({ queryKey: ["stats"], queryFn: () => api.stats(), staleTime: 60_000 });
  const b = data?.budget;
  if (!b || (b.state !== "warn" && b.state !== "over")) return null;
  const over = b.state === "over";
  const Icon = over ? OctagonAlert : TriangleAlert;
  return (
    <section
      aria-label={t.stats.title}
      className={cn("flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b px-6 py-2.5 text-[13px] leading-5", over ? "border-coral/60 bg-coral/10" : "border-amber/60 bg-amber/8", className)}
    >
      <Icon className={cn("size-4 shrink-0", over ? "text-coral" : "text-amber")} aria-hidden />
      <span className="font-medium">{over ? t.stats.budgetOver(b.usd) : t.stats.budgetWarn(Math.round(b.ratio * 100), b.usd)}</span>
      {over && <span className="text-muted-foreground">{t.setup.overNote}</span>}
      <Link to="/stats" className="ml-auto font-medium">
        {t.nav.stats}
      </Link>
    </section>
  );
}
