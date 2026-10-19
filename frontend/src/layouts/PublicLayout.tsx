import { Link, Outlet, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PublicBrand } from "../components/Brand";
import { MobileNav } from "../components/shared";
import { api } from "../lib/api";
import type { Municipality } from "../lib/types";

export function PublicLayout() {
  const { municipalitySlug } = useParams();
  const { pathname } = useLocation();
  const municipality = useQuery({ queryKey: ["municipality", municipalitySlug], queryFn: () => api.get<Municipality>(`/municipalities/${municipalitySlug}/`), enabled: Boolean(municipalitySlug) });
  const links = municipalitySlug && municipality.data ? [
    { to: `/${municipalitySlug}/prijavi`, label: "Пријави проблем" },
    { to: `/${municipalitySlug}/sledi`, label: "Следи пријава" },
    { to: `/${municipalitySlug}/statistika`, label: "Статистика" }
  ] : [];

  const current = (to: string) => pathname === to ? "page" as const : undefined;

  return (
    <div className="public-theme flex min-h-screen flex-col">
      <a href="#main-content" className="skip-link">Прескокни до содржината</a>
      <header className="public-header sticky top-0 z-40 border-b">
        <div className="container flex min-h-20 flex-wrap items-center py-3 justify-between gap-4">
          <PublicBrand municipality={municipality.data?.name} />
          {pathname === "/" ? (
            <>
              <nav className="hidden max-w-full flex-wrap items-center gap-2 md:flex" aria-label="Главна навигација">
                <a className="public-nav-link" href="#municipalities">Општини</a>
                <a className="public-nav-link" href="#how-it-works">Како работи</a>
                <Link className="public-nav-link public-nav-login" to="/login">Службена најава</Link>
              </nav>
              <MobileNav>
                <a href="#municipalities">Избери општина</a>
                <a href="#how-it-works">Како работи</a>
                <Link to="/login">Службена најава</Link>
              </MobileNav>
            </>
          ) : (
            <>
              <nav className="hidden max-w-full flex-wrap items-center gap-1 md:flex" aria-label="Главна навигација">
                <Link className="public-nav-link" to="/" aria-current={current("/")}>Почетна</Link>
                {links.map(({ to, label }) => <Link key={to} className="public-nav-link" to={to} aria-current={current(to)}>{label}</Link>)}
                <Link className="public-nav-link public-nav-login ml-2" to="/login" aria-current={current("/login")}>Службена најава</Link>
              </nav>
              <MobileNav>
                <Link to="/">Почетна</Link>
                {links.map(({ to, label }) => <Link key={to} to={to} aria-current={current(to)}>{label}</Link>)}
                <Link to="/login">Најава за службеници</Link>
              </MobileNav>
            </>
          )}
        </div>
      </header>
      <main id="main-content" className={pathname === "/" ? "flex-1" : "container flex-1 py-8 md:py-12"} tabIndex={-1}><Outlet /></main>
      <footer className="public-footer border-t">
        <div className="container grid gap-8 py-12 text-sm md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <div><PublicBrand municipality={municipality.data?.name} /><p className="mt-3 max-w-md text-muted-foreground">Официјален канал за пријавување и следење локални проблеми, без задолжителен кориснички профил.</p></div>
          <div><h2 className="mb-2 font-bold">Општинска услуга</h2><div className="grid gap-1.5 text-muted-foreground"><Link to="/">Избери општина</Link>{municipalitySlug && municipality.data ? <Link to={`/${municipalitySlug}/prijavi`}>Пријави проблем</Link> : null}{municipalitySlug && municipality.data ? <Link to={`/${municipalitySlug}/sledi`}>Следи пријава</Link> : null}</div></div>
          <div><h2 className="mb-2 font-bold">Правни информации</h2><div className="grid gap-1.5 text-muted-foreground"><Link to="/privatnost">Приватност</Link><Link to="/uslovi">Услови за користење</Link><Link to="/login">Службена најава</Link></div></div>
        </div>
      </footer>
    </div>
  );
}
