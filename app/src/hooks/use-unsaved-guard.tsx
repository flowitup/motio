import { useEffect, type ReactNode } from "react";
import { useBlocker } from "react-router";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { t } from "@/i18n";

/**
 * Ask before leaving a page that holds unsaved changes (a route change, or closing / reloading the window).
 * Render the returned element anywhere in the page: it is the "Leave without saving?" dialog.
 */
export function useUnsavedGuard(dirty: boolean): ReactNode {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search),
  );
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  return (
    <ConfirmDialog
      open={blocker.state === "blocked"}
      onOpenChange={(open) => {
        if (!open && blocker.state === "blocked") blocker.reset();
      }}
      title={t.confirm.leaveTitle}
      description={t.confirm.leaveBody}
      confirmLabel={t.confirm.leave}
      cancelLabel={t.confirm.stay}
      onConfirm={() => blocker.state === "blocked" && blocker.proceed()}
    />
  );
}
