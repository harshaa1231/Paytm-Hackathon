import { useEffect, useState } from "react";
import { ArrowLeft, BarChart3, Cpu, GraduationCap, RefreshCcw, Wifi, WifiOff } from "lucide-react";
import { api, cx, type DemoConfig } from "./lib";
import AppDemo from "./pages/AppDemo";
import UnderTheHood from "./pages/UnderTheHood";
import Proof from "./pages/Proof";
import Learning from "./pages/Learning";

const JUDGE_ROUTES = [
  { id: "proof", label: "Evidence & proof", icon: BarChart3 },
  { id: "hood", label: "Under the hood", icon: Cpu },
  { id: "learning", label: "Learning loop", icon: RefreshCcw },
] as const;
type JudgeRoute = (typeof JUDGE_ROUTES)[number]["id"];
type Route = { area: "app" } | { area: "judges"; page: JudgeRoute };

const parse = (): Route => {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h.startsWith("judges")) {
    const page = h.split("/")[1] as JudgeRoute;
    return { area: "judges", page: JUDGE_ROUTES.some((r) => r.id === page) ? page : "proof" };
  }
  return { area: "app" };
};

export default function App() {
  const [route, setRoute] = useState<Route>(parse());
  const [cfg, setCfg] = useState<DemoConfig | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [shop, setShop] = useState<string>(() => { try { return localStorage.getItem("pk_shop") || "S001"; } catch { return "S001"; } });
  const [lang, setLang] = useState<string>(() => { try { return localStorage.getItem("pk_lang") || "en"; } catch { return "en"; } });

  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    api.config().then(setCfg).catch((e) => setErr(String(e.message || e)));
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => { try { localStorage.setItem("pk_shop", shop); localStorage.setItem("pk_lang", lang); } catch { /* private mode */ } }, [shop, lang]);

  const offline = cfg?.demo_mode === "replay";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-30 bg-white/85 backdrop-blur border-b border-slate-200">
        <div className="mx-auto max-w-[1280px] px-4 sm:px-6 h-16 flex items-center gap-3">
          <a href="#/" className="flex items-center gap-2.5 shrink-0">
            <img src="/favicon.svg" alt="" className="w-8 h-8" />
            <div className="leading-tight">
              <div className="font-bold text-[17px] tracking-tight">PakkaKhata</div>
              <div className="text-[11px] text-ink-3 hidden sm:block">Other apps track who owes you. PakkaKhata shows who to trust.</div>
            </div>
          </a>
          <div className="ml-auto flex items-center gap-2 min-w-0">
            {route.area === "app" ? (
              <a href="#/judges/proof" className="btn btn-md text-ink-2 hover:bg-slate-100"><GraduationCap size={16} /> For judges</a>
            ) : (
              <>
                <nav className="flex gap-1 overflow-x-auto min-w-0">
                  {JUDGE_ROUTES.map(({ id, label, icon: Icon }) => (
                    <a key={id} href={`#/judges/${id}`}
                      className={cx("btn btn-md whitespace-nowrap", route.page === id ? "bg-navy text-white" : "text-ink-2 hover:bg-slate-100")}>
                      <Icon size={16} /> <span className="hidden md:inline">{label}</span>
                    </a>
                  ))}
                </nav>
                <a href="#/" className="btn btn-md btn-ghost whitespace-nowrap"><ArrowLeft size={16} /> <span className="hidden sm:inline">Back to the app</span></a>
              </>
            )}
            {cfg && route.area === "judges" && (
              <span title={offline ? "Replay mode: cached AI answers + rules. Works with Wi-Fi off." : `AI mode: ${cfg.demo_mode}`}
                className={cx("chip hidden xl:inline-flex", offline ? "bg-emerald-50 text-emerald-700" : "bg-sky-soft text-sky")}>
                {offline ? <WifiOff size={13} /> : <Wifi size={13} />} {offline ? "Offline mode" : `AI ${cfg.demo_mode}`}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className={cx("flex-1 w-full", route.area === "judges" && "mx-auto max-w-[1280px] px-4 sm:px-6 py-6")}>
        {err && <div className="m-6 panel panel-pad text-red-700">Can't reach the PakkaKhata service: {err}. Start it with <code>uvicorn api.main:app</code>.</div>}
        {cfg && route.area === "app" && <AppDemo cfg={cfg} shop={shop} setShop={setShop} lang={lang} setLang={setLang} />}
        {cfg && route.area === "judges" && route.page === "hood" && <UnderTheHood cfg={cfg} shop={shop} setShop={setShop} lang={lang} />}
        {cfg && route.area === "judges" && route.page === "proof" && <Proof />}
        {cfg && route.area === "judges" && route.page === "learning" && <Learning />}
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-[1280px] px-4 sm:px-6 py-4 text-xs text-ink-3 flex flex-wrap gap-x-6 gap-y-1">
          <span>{cfg?.footer ?? "Synthetic demo data."}</span>
          <span>Concept only: no real Paytm integration, no money moves, no messages sent to customers.</span>
          {route.area === "judges" && <a className="underline" href="/docs" target="_blank" rel="noreferrer">API docs</a>}
        </div>
      </footer>
    </div>
  );
}
