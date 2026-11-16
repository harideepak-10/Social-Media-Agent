import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { auth } from "./lib/api";
import Layout from "./components/Layout";
import { ToastProvider, WakeBanner } from "./components/ui";
import Queue from "./pages/Queue";
import ItemDetail from "./pages/ItemDetail";
import Create from "./pages/Create";
import Login from "./pages/Login";
import Schedule from "./pages/Schedule";
import Settings from "./pages/Settings";

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
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Queue />} />
        <Route path="items/:id" element={<ItemDetail />} />
        <Route path="item/:id" element={<ItemDetail />} />
        <Route path="create" element={<Create />} />
        <Route path="schedule" element={<Schedule />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <WakeBanner />
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
