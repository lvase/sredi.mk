import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { FormEvent } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, CircleUserRound, Clock3, House, Inbox, LogOut, Search, ShieldCheck, UserPlus, UsersRound } from "lucide-react";
import { StaffBrand } from "../components/Brand";
import { MobileNav } from "../components/shared";
import { Button } from "../components/ui/button";
import { LoadingState } from "../components/LoadingState";
import { useLogout, useSession } from "../hooks/useSession";

export function StaffLayout() {
  const session = useSession();
  const logout = useLogout();
  const { pathname, search } = useLocation();
  const navigate = useNavigate();

  if (session.isLoading) return <LoadingState />;
  if (!session.data?.isAuthenticated) return <Navigate to="/login" replace />;

  const navItems = [
    ["/staff", "Сите пријави", Inbox],
    ["/staff?mine=1", "Мои пријави", UsersRound],
    ["/staff?unassigned=1", "Недоделени", AlertTriangle],
    ["/staff?overdue=1", "Задоцнети", Clock3]
  ] as const;
  const active = (to: string) => `${pathname}${search}` === to || (to === "/staff" && pathname === "/staff" && !search);
  const role = session.data.user?.is_superuser ? "Администратор на платформата" : session.data.user?.role || "Службеник";

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = String(new FormData(event.currentTarget).get("search") || "").trim();
    navigate(query ? `/staff?search=${encodeURIComponent(query)}` : "/staff");
  }

  const nav = navItems.map(([to, label, Icon]) => <Link key={to} className="staff-nav-link" to={to} aria-current={active(to) ? "page" : undefined}><Icon className="h-4 w-4" /> {label}</Link>);

  return (
    <div className="staff-theme min-h-screen md:grid md:grid-cols-[248px_1fr]">
      <a href="#staff-content" className="skip-link">Прескокни до содржината</a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] flex-col bg-slate-900 p-4 md:flex">
        <StaffBrand />
        <nav className="mt-8 grid gap-1" aria-label="Работна навигација">{nav}</nav>
        {session.data.user?.is_superuser ? <Link className="staff-nav-link mt-2" to="/staff/users/new" aria-current={pathname === "/staff/users/new" ? "page" : undefined}><UserPlus className="h-4 w-4" /> Нов корисник</Link> : null}
        <Link className="staff-nav-link mt-auto" to="/"><House className="h-4 w-4" /> Јавен портал</Link>
      </aside>
      <div className="min-w-0 md:col-start-2">
        <header className="sticky top-0 z-20 border-b bg-white/95 backdrop-blur">
          <div className="flex h-16 items-center gap-3 px-4 lg:px-7">
            <MobileNav staff>{nav}{session.data.user?.is_superuser ? <Link to="/staff/users/new"><UserPlus className="h-4 w-4" /> Нов корисник</Link> : null}<Link to="/"><House className="h-4 w-4" /> Јавен портал</Link></MobileNav>
            <form onSubmit={submitSearch} className="relative max-w-xl flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input name="search" aria-label="Пребарај пријави" placeholder="Код, наслов или локација…" className="h-10 w-full rounded-md border bg-slate-50 pl-9 pr-3 text-sm" /></form>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild><Button variant="ghost" className="max-w-52 justify-start"><CircleUserRound className="h-5 w-5" /><span className="hidden min-w-0 text-left sm:block"><strong className="block truncate text-xs">{session.data.user?.username}</strong><small className="block truncate text-[10px] text-muted-foreground">{role}</small></span></Button></DropdownMenu.Trigger>
              <DropdownMenu.Portal><DropdownMenu.Content align="end" className="z-50 min-w-60 rounded-md border bg-white p-2 shadow-xl"><div className="border-b px-2 pb-2 text-xs text-muted-foreground">{session.data.user?.municipality?.name || "Сите општини"}</div><DropdownMenu.Item asChild><Link className="mt-1 flex w-full items-center gap-2 rounded px-2 py-2 text-sm hover:bg-muted" to="/staff/security"><ShieldCheck className="h-4 w-4" /> Безбедност</Link></DropdownMenu.Item><DropdownMenu.Item asChild><button className="flex w-full items-center gap-2 rounded px-2 py-2 text-sm hover:bg-muted" onClick={() => logout.mutate()}><LogOut className="h-4 w-4" /> Одјава</button></DropdownMenu.Item></DropdownMenu.Content></DropdownMenu.Portal>
            </DropdownMenu.Root>
            <Button variant="ghost" size="icon" aria-label="Одјава" onClick={() => logout.mutate()}><LogOut className="h-4 w-4" /></Button>
          </div>
        </header>
        <main id="staff-content" className="p-4 lg:p-7" tabIndex={-1}><Outlet /></main>
      </div>
    </div>
  );
}
