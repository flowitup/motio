import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import type { Api } from "@/lib/api";
import { t } from "@/i18n";

/** Hỏi lại trước khi xoá một dự án (video, giọng, phụ đề, bài đăng). */
export function DeleteProjectDialog({
  api,
  id,
  title,
  open,
  onOpenChange,
  onDeleted,
}: {
  api: Api;
  id: number;
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted?: () => void;
}) {
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => api.deleteProject(id),
    onSuccess: () => {
      onOpenChange(false);
      // Không removeQueries(["project", id]): trang chi tiết còn đang mở sẽ tải lại và gặp 404. Id không bao giờ dùng lại.
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["trends"] });
      onDeleted?.();
    },
  });
  return (
    <AlertDialog
      open={open}
      onOpenChange={(o) => {
        if (!o) del.reset();
        onOpenChange(o);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t.projects.deleteTitle(id)}</AlertDialogTitle>
          <div className="line-clamp-2 font-medium">{title}</div>
          <AlertDialogDescription>{t.projects.deleteBody}</AlertDialogDescription>
        </AlertDialogHeader>
        {del.error && <p className="text-sm text-destructive">{del.error.message}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel>{t.projects.deleteCancel}</AlertDialogCancel>
          <Button variant="destructive" onClick={() => del.mutate()} disabled={del.isPending}>
            {del.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />}
            {t.projects.deleteConfirm}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
