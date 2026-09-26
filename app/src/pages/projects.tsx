import { useQuery } from "@tanstack/react-query";
import { Film } from "lucide-react";
import { Link } from "react-router";
import { StatusChip } from "@/components/status-chip";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi } from "@/lib/api";
import { t } from "@/i18n";

export default function ProjectsPage() {
  const api = useApi()!;
  const { data, isLoading, error } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.projects(),
    refetchInterval: 4_000,
  });

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <h1 className="text-2xl font-semibold tracking-tight">{t.projects.title}</h1>
      {error && <p className="text-sm text-destructive">{error.message}</p>}
      {data?.length === 0 && <p className="py-12 text-center text-muted-foreground">{t.projects.empty}</p>}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
        {isLoading && Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="aspect-[9/16] rounded-xl" />)}
        {data?.map((p) => (
          <Link key={p.id} to={`/projects/${p.id}`} className="group">
            <Card className="gap-0 overflow-hidden p-0 transition-shadow group-hover:shadow-md">
              <div className="relative aspect-[9/16] bg-muted">
                {p.meta.thumb ? (
                  <img
                    src={api.mediaUrl(p.meta.thumb, p.updated_at)}
                    alt=""
                    className="size-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <Film className="absolute inset-0 m-auto size-10 text-muted-foreground/50" />
                )}
                <StatusChip status={p.status} className="absolute top-2 left-2" />
              </div>
              <div className="space-y-2 p-3">
                <div className="line-clamp-2 text-sm font-medium leading-snug">{p.meta.title || p.title}</div>
                {(p.status === "running" || p.status === "queued") && (
                  <>
                    <Progress value={p.pct} />
                    <div className="text-xs text-muted-foreground">{p.step}</div>
                  </>
                )}
                <div className="text-xs text-muted-foreground">
                  #{p.id} · {t.age(p.updated_at)}
                </div>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
