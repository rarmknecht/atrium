import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { RunEventsProvider } from "./api/useRunEvents";
import { AuthGate } from "./components/AuthGate";
import { ThemeProvider } from "./theme/ThemeProvider";

import "./theme/tokens.css";
import "./theme/base.css";
import "./theme/components.css";
import "./theme/markdown.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5000, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthGate>
          <RunEventsProvider>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </RunEventsProvider>
        </AuthGate>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
