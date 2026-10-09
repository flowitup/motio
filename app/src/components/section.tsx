import { ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { PanelHeader } from "@/components/studio";
import { cn } from "@/lib/utils";

/**
 * A titled block of a long form: the Studio panel (40 px mono caption strip + body) with rounded corners to sit in a
 * column. `collapsible` turns the strip into a button that folds the body; `aside` is a short readout on the right
 * (it also tells what is inside while the section is folded).
 */
export function Section({
  id,
  title,
  aside,
  children,
  collapsible,
  defaultOpen = true,
  className,
  bodyClassName,
}: {
  id?: string;
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  className?: string;
  bodyClassName?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const body = useId();
  const shown = !collapsible || open;
  return (
    <section id={id} className={cn("scroll-mt-20 overflow-hidden rounded-lg border bg-panel", className)}>
      {collapsible ? (
        <h2>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={body}
            onClick={() => setOpen((o) => !o)}
            className={cn(
              "flex h-10 w-full items-center gap-2 bg-strip px-4 text-left transition-colors hover:bg-raised focus-visible:-outline-offset-2",
              open && "border-b",
            )}
          >
            <ChevronRight aria-hidden className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
            <span className="font-mono text-xs leading-4 font-medium tracking-[0.06em] text-muted-foreground uppercase">{title}</span>
            {aside && <span className="ml-auto min-w-0 truncate pl-3 text-xs text-muted-foreground">{aside}</span>}
          </button>
        </h2>
      ) : (
        <PanelHeader aside={aside}>{title}</PanelHeader>
      )}
      <div id={body} hidden={!shown} className={cn("p-4", bodyClassName)}>
        {children}
      </div>
    </section>
  );
}
