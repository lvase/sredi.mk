import { Link, Outlet, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, House, LogIn, PlusCircle, Search } from "lucide-react";
import { PublicBrand } from "../components/Brand";
import { MobileNav } from "../components/shared";
import { api } from "../lib/api";
import type { Municipality } from "../lib/types";

export function PublicLayout() {
  const { municipalitySlug } = useParams();
  const { pathname } = useLocation();
  const municipality = useQuery({ queryKey: ["municipality", municipalitySlug], queryFn: () => api.get<Municipality>(`/municipalities/${municipalitySlug}/`), enabled: Boolean(municipalitySlug) });
  const links = municipalitySlug ? [
    { to: `/${municipalitySlug}/prijavi`, label: "Пријави", icon: PlusCircle },
    { to: `/${municipalitySlug}/sledi`, label: "Следи", icon: Search },
    { to: `/${municipalitySlug}/statistika`, label: "Статистика", icon: BarChart3 }
  ] : [];

  const current = (to: string) => pathname === to ? "page" as const : undefined;

  return (
    <div className="public-theme flex min-h-screen flex-col">
      <a href="#main-content" className="skip-link">Прескокни до содржината</a>
      <header className="sticky top-0 z-40 border-b border-white/60 bg-white/[0.88] shadow-sm backdrop-blur-md">
        <div className="container flex h-[72px] items-center justify-between gap-4">
          <PublicBrand municipality={municipality.data?.name} />
          {pathname === "/" ? (
            <Link className="public-nav-link border" to="/login"><LogIn className="h-4 w-4" /> Службена најава</Link>
          ) : (
            <>
              <nav className="hidden items-center gap-1 md:flex" aria-label="Главна навигација">
                <Link className="public-nav-link" to="/" aria-current={current("/")}><House className="h-4 w-4" /> Почетна</Link>
                {links.map(({ to, label, icon: Icon }) => <Link key={to} className="public-nav-link" to={to} aria-current={current(to)}><Icon className="h-4 w-4" /> {label}</Link>)}
                <Link className="public-nav-link ml-1 border" to="/login" aria-current={current("/login")}><LogIn className="h-4 w-4" /> Службена најава</Link>
              </nav>
              <MobileNav>
                <Link to="/"><House className="h-5 w-5" /> Почетна</Link>
                {links.map(({ to, label, icon: Icon }) => <Link key={to} to={to} aria-current={current(to)}><Icon className="h-5 w-5" /> {label}</Link>)}
                <Link to="/login"><LogIn className="h-5 w-5" /> Најава за службеници</Link>
              </MobileNav>
            </>
          )}
        </div>
      </header>
      <main id="main-content" className="container flex-1 py-8 md:py-12" tabIndex={-1}><Outlet /></main>
      <footer className="border-t bg-emerald-50/70">
        <div className="container grid gap-8 py-9 md:grid-cols-[1.4fr_1fr_1fr]">
          <div><PublicBrand /><p className="mt-3 max-w-md text-sm text-muted-foreground">Дигитална општинска услуга за пријавување, следење и јавна отчетност — без отворање кориснички профил.</p></div>
          <div><h2 className="mb-3 text-sm font-bold">За граѓани</h2><div className="grid gap-2 text-sm text-muted-foreground"><Link to="/">Избери општина</Link>{municipalitySlug ? <Link to={`/${municipalitySlug}/prijavi`}>Пријави проблем</Link> : null}</div></div>
          <div><h2 className="mb-3 text-sm font-bold">Информации</h2><div className="grid gap-2 text-sm text-muted-foreground"><Link to="/privatnost">Приватност</Link><Link to="/uslovi">Услови за користење</Link><Link to="/login">Службена најава</Link></div></div>
        </div>
      </footer>
    </div>
  );
}
