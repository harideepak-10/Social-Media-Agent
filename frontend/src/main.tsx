import { StrictMode, Suspense, lazy, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { auth } from "./lib/api";
import Layout from "./components/Layout";
import { ToastProvider, WakeBanner } from "./components/ui";
import Queue from "./pages/Queue";
import ItemDetail from "./pages/ItemDetail";
const Create = lazy(() => import("./pages/Create"));
import Login from "./pages/Login";
// less-used pages load on first visit, so the app opens fast on phones
const Schedule = lazy(() => import("./pages/Schedule"));
const Settings = lazy(() => import("./pages/Settings"));
const Results = lazy(() => import("./pages/Results"));
const Setup = lazy(() => import("./pages/Setup"));
import { registerServiceWorker } from "./lib/pwa";
import WakeGate from "./components/WakeGate";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: (n, e) => n < 2 && (e as { status?: number }).status !== 401, refetchOnWindowFocus: true } },
});

function App() {
  const [loggedIn, setLoggedIn] = useState(!!auth.token);
  useEffect(() => {
    const out = () => { setLoggedIn(false); queryClient.clear(); };
    window.addEventListener("dma:logout", out);
    return () => window.removeEventListener("dma:logout", out);
  }, []);

  if (!loggedIn) return <Login onLogin={() => setLoggedIn(true)} />;
  return (
    <Suspense fallback={<div className="grid h-full place-items-center text-sm text-stone-400">Loading…</div>}>
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Queue />} />
        <Route path="items/:id" element={<ItemDetail />} />
        <Route path="item/:id" element={<ItemDetail />} />
        <Route path="create" element={<Create />} />
        <Route path="schedule" element={<Schedule />} />
        <Route path="settings" element={<Settings />} />
        <Route path="results" element={<Results />} />
        <Route path="setup" element={<Setup />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
    </Suspense>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <WakeBanner />
        <WakeGate>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </WakeGate>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);

registerServiceWorker();
