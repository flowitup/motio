import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router";
import App from "./App";
import { useLang } from "./i18n";
import { EngineProvider } from "./lib/engine";
import { UpdaterProvider } from "./lib/updater";
import "./index.css";

// The look (data-theme + .dark on <html>) is set when lib/theme loads, before the first paint.
import "./lib/theme";

/** Switching language rebuilds the screens so every string is read again. */
function Root() {
  const lang = useLang();
  return <App key={lang} />;
}

// A data router (not <HashRouter>) so a page with unsaved changes can block leaving it (useBlocker).
const router = createHashRouter([{ path: "*", element: <Root /> }]);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 } },
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <EngineProvider>
        <UpdaterProvider>
          <RouterProvider router={router} />
        </UpdaterProvider>
      </EngineProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
