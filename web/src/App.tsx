import { useEffect, useState } from "react";
import { BarChart3, Cpu, RefreshCcw, Smartphone, WifiOff, Wifi } from "lucide-react";
import { api, cx, type DemoConfig } from "./lib";
import Shopkeeper from "./pages/Shopkeeper";
import UnderTheHood from "./pages/UnderTheHood";
import Proof from "./pages/Proof";
import Learning from "./pages/Learning";

const ROUTES = [
  { id: "shopkeeper", label: "Shopkeeper", icon: Smartphone },
  { id: "hood", label: "Under the hood", icon: Cpu },
  { id: "proof", label: "Proof", icon: BarChart3 },
  { id: "learning", label: "Learning loop", icon: RefreshCcw },
] as const;
type Route = (typeof ROUTES)[number]["id"];

const routeFromHash = (): Route => {
  const h = window.location.hash.replace("#/", "") as Route;
  return ROUTES.some((r) => r.id === h) ? h : "shopkeeper";
};

export default function App() {
  const [route, setRoute] = useState<Route>(routeFromHash());
  const [cfg, setCfg] = useState<DemoConfig | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [shop, setShop] = useState<string>(() => localStorage.getItem("pk_shop") || "S001");
  const [lang, setLang] = useState<string>(() => localStorage.getItem("pk_lang") || "en");

  useEffect(() => {
    const on = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", on);
    api.config().then(setCfg).catch((e) => setErr(String(e.message || e)));
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => { try { localStorage.setItem("pk_shop", shop); localStorage.setItem("pk_lang", lang); } catch { /* private mode */ } }, [shop, lang]);

  const go = (r: Route) => { window.location.hash = `#/${r}`; };
  const offline = cfg?.demo_mode === "replay";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-30 bg-white/85 backdrop-blur border-b border-slate-200">
        <div className="mx-auto max-w-[1280px] px-4 sm:px-6 h-16 flex items-center gap-4">
          <a href="#/shopkeeper" className="flex items-center gap-2.5 shrink-0">
            <img src="/favicon.svg" alt="" className="w-8 h-8" />
            <div className="leading-tight">
              <div className="font-bold text-[17px] tracking-tight">PakkaKhata</div>
              <div className="text-[11px] text-ink-3 hidden sm:block">Other apps track who owes you. PakkaKhata shows who to trust.</div>
            </div>
          </a>
          <nav className="ml-auto flex gap-1 overflow-x-auto">
            {ROUTES.map(({ id, label, icon: Icon }) => (
              <button key={id} onClick={() => go(id)}
                className={cx("btn btn-md whitespace-nowrap", route === id ? "bg-navy text-white" : "text-ink-2 hover:bg-slate-100")}>
                <Icon size={16} /> <span className="hidden md:inline">{label}</span>
              </button>
            ))}
          </nav>
          {cfg && (
            <span title={offline ? "Replay mode: cached LLM answers + rules. Works with Wi-Fi off." : `LLM mode: ${cfg.demo_mode}`}
              className={cx("chip hidden lg:inline-flex", offline ? "bg-emerald-50 text-emerald-700" : "bg-sky-soft text-sky")}>
              {offline ? <WifiOff size={13} /> : <Wifi size={13} />} {offline ? "Offline-safe" : `LLM ${cfg.demo_mode}`}
            </span>
          )}
        </div>
      </header>

      <main className="flex-1 mx-auto w-full max-w-[1280px] px-4 sm:px-6 py-6">
        {err && <div className="panel panel-pad text-red-700">Can't reach the PakkaKhata service: {err}. Start it with <code>uvicorn api.main:app</code>.</div>}
        {cfg && route === "shopkeeper" && <Shopkeeper cfg={cfg} shop={shop} setShop={setShop} lang={lang} setLang={setLang} />}
        {cfg && route === "hood" && <UnderTheHood cfg={cfg} shop={shop} setShop={setShop} lang={lang} />}
        {cfg && route === "proof" && <Proof />}
        {cfg && route === "learning" && <Learning />}
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-[1280px] px-4 sm:px-6 py-4 text-xs text-ink-3 flex flex-wrap gap-x-6 gap-y-1">
          <span>{cfg?.footer ?? "Synthetic demo data."}</span>
          <span>Concept only: no real Paytm integration, no money moves.</span>
          <a className="underline" href="/docs" target="_blank" rel="noreferrer">API docs</a>
        </div>
      </footer>
    </div>
  );
}
