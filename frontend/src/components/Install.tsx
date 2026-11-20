import { useEffect, useState } from "react";
import { Download, Share, X } from "lucide-react";
import { canPrompt, isIOS, isStandalone, onInstallChange, promptInstall } from "../lib/pwa";
import { useToast } from "./ui";

const KEY = "dma_install_dismissed";
const dismissed = () => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } };

function useInstallable() {
  const [, force] = useState(0);
  useEffect(() => onInstallChange(() => force((n) => n + 1)), []);
  return { prompt: canPrompt(), ios: isIOS(), installed: isStandalone() };
}

/** Phone banner on the queue: "Install the app" (Android/Chrome) or Add-to-Home-Screen steps (iPhone). */
export function InstallBanner() {
  const { prompt, ios, installed } = useInstallable();
  const toast = useToast();
  const [hidden, setHidden] = useState(dismissed());
  if (installed || hidden || (!prompt && !ios)) return null;
  const close = () => { try { localStorage.setItem(KEY, "1"); } catch { /* private mode */ } setHidden(true); };
  return (
    <div className="mt-6 flex items-start gap-3 rounded-2xl bg-ink-900 px-4 py-3.5 text-sm text-white md:hidden">
      <img src="/icons/icon-192.png" alt="" className="size-10 shrink-0 rounded-xl" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold">Install the app</div>
        {ios ? (
          <div className="mt-0.5 text-white/70">Tap <Share className="inline size-3.5 align-[-2px]" /> <b>Share</b>, then <b>Add to Home Screen</b> – it opens full-screen like an app.</div>
        ) : (
          <>
            <div className="mt-0.5 text-white/70">One tap from your home screen, full-screen, no address bar.</div>
            <button onClick={() => promptInstall().then((ok) => ok && toast("ok", "Installed – find Krypsos Agent on your home screen"))}
              className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-xs font-bold text-ink-900"><Download className="size-3.5" /> Install</button>
          </>
        )}
      </div>
      <button onClick={close} aria-label="Dismiss" className="-mr-1 -mt-1 grid size-8 place-items-center text-white/50 hover:text-white"><X className="size-4" /></button>
    </div>
  );
}

/** Desktop sidebar link (Chrome / Edge offer installing desktop apps too). */
export function InstallLink() {
  const { prompt, installed } = useInstallable();
  if (installed || !prompt) return null;
  return (
    <button onClick={() => promptInstall()} className="flex items-center gap-1.5 hover:text-white">
      <Download className="size-3" /> Install app
    </button>
  );
}
