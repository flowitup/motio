import type { ReactNode } from "react";
import { openExternal } from "@/lib/engine";
import { cn } from "@/lib/utils";

/** Link mở bằng trình duyệt hệ thống. */
export function ExternalA({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className={cn("cursor-pointer hover:underline", className)}
      onClick={(e) => {
        e.preventDefault();
        openExternal(href);
      }}
    >
      {children}
    </a>
  );
}
