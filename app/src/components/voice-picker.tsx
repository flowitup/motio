import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Choice } from "@/components/form";
import type { Api } from "@/lib/api";
import { t } from "@/i18n";

/** Chọn giọng của nhà cung cấp đang dùng (hoặc `provider` nếu truyền); "" = lựa chọn mặc định (`autoLabel`). */
export function VoicePicker({
  api,
  value,
  onChange,
  hasKey,
  autoLabel = t.settings.voiceAuto,
  provider = "",
}: {
  api: Api;
  value: string;
  onChange: (v: string) => void;
  hasKey: boolean;
  autoLabel?: string;
  provider?: string;
}) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["voices", provider],
    queryFn: () => api.voices(provider),
    enabled: hasKey,
    staleTime: 5 * 60_000,
  });
  if (!hasKey) return <p className="text-sm text-muted-foreground">{t.settings.voiceNeedKey}</p>;
  if (error) return <p className="text-sm text-destructive">{error.message}</p>;
  if (isLoading) return <Loader2 className="size-4 animate-spin" />;
  const options: [string, string][] = [
    ["", autoLabel],
    ...(data ?? []).map((v): [string, string] => [
      v.id,
      [v.name, v.labels.language, v.labels.accent, v.labels.gender, v.labels.style].filter(Boolean).join(" · "),
    ]),
  ];
  return <Choice value={value} onChange={onChange} options={options} />;
}
