import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Loader2, Trash2 } from "lucide-react";
import { useRef } from "react";
import { Section } from "@/components/section";
import { Button } from "@/components/ui/button";
import type { Api } from "@/lib/api";
import { t } from "@/i18n";

/** Thư viện logo của người dùng: dùng để phủ lên chữ in sẵn / watermark của nguồn (thẻ Giấu chữ trên trang dự án). */
export function LogosCard({ api }: { api: Api }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const { data: logos = [], error } = useQuery({ queryKey: ["logos"], queryFn: () => api.logos() });
  const done = () => qc.invalidateQueries({ queryKey: ["logos"] });
  const add = useMutation({ mutationFn: (f: File) => api.addLogo(f), onSuccess: done });
  const remove = useMutation({ mutationFn: (id: string) => api.deleteLogo(id), onSuccess: done });
  const failed = error ?? add.error ?? remove.error;
  return (
    <Section id="logos" title={t.logos.title} aside={logos.length || undefined} bodyClassName="grid gap-3 text-[13px]">
      <p className="text-xs leading-[18px] text-muted-foreground">{t.logos.hint}</p>
      {logos.length ? (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-2">
          {logos.map((lg) => (
            <li key={lg.id} className="grid gap-1.5 rounded-lg border p-2">
              {/* nền ô cờ để thấy phần trong suốt của logo */}
              <div className="grid h-20 place-items-center rounded bg-[repeating-conic-gradient(#8884_0_25%,transparent_0_50%)] bg-[length:16px_16px]">
                <img src={api.mediaUrl(lg.media)} alt={lg.name} className="max-h-18 max-w-full object-contain" />
              </div>
              <div className="flex min-w-0 items-center gap-1">
                <span className="min-w-0 flex-1 truncate text-xs" title={lg.name}>
                  {lg.name}
                </span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => remove.mutate(lg.id)}
                  disabled={remove.isPending}
                  aria-label={t.logos.remove(lg.name)}
                >
                  <Trash2 />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">{t.logos.none}</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) add.mutate(f);
            e.target.value = "";
          }}
        />
        <Button variant="secondary" onClick={() => input.current?.click()} disabled={add.isPending}>
          {add.isPending ? <Loader2 className="animate-spin" /> : <ImagePlus />}
          {t.logos.add}
        </Button>
        {failed && <p className="text-destructive">{failed.message}</p>}
      </div>
    </Section>
  );
}
