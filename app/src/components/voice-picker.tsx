import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Choice } from "@/components/form";
import type { Api } from "@/lib/api";
import { t } from "@/i18n";

/** Chọn giọng ElevenLabs; "" = lựa chọn mặc định (`autoLabel`). */
export function VoicePicker({
  api,
  value,
  onChange,
  hasKey,
  autoLabel = t.settings.voiceAuto,
}: {
  api: Api;
  value: string;
  onChange: (v: string) => void;
  hasKey: boolean;
  autoLabel?: string;
}) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["voices"],
    queryFn: () => api.voices(),
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
      [v.name, v.labels.language, v.labels.accent, v.labels.gender].filter(Boolean).join(" · "),
    ]),
  ];
  return <Choice value={value} onChange={onChange} options={options} />;
}
