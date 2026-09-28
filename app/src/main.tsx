import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router";
import App from "./App";
import { useLang } from "./i18n";
import { EngineProvider } from "./lib/engine";
import { UpdaterProvider } from "./lib/updater";
import "./index.css";

// Theo chế độ sáng / tối của hệ điều hành.
const dark = window.matchMedia("(prefers-color-scheme: dark)");
const applyTheme = () => document.documentElement.classList.toggle("dark", dark.matches);
applyTheme();
dark.addEventListener("change", applyTheme);

/** Switching language rebuilds the screens so every string is read again. */
function Root() {
  const lang = useLang();
  return <App key={lang} />;
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 } },
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <EngineProvider>
        <UpdaterProvider>
          <HashRouter>
            <Root />
          </HashRouter>
        </UpdaterProvider>
      </EngineProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
