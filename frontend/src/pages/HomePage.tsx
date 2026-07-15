import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BarChart3, Building2, CheckCircle2, LockKeyhole, MapPin, Search, Send, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import type { Municipality } from "../lib/types";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { formatDate } from "../lib/utils";

export function HomePage() {
  const [query, setQuery] = useState("");
  const municipalities = useQuery({ queryKey: ["municipalities"], queryFn: () => api.get<Municipality[]>("/municipalities/") });
  const filtered = useMemo(() => (municipalities.data || []).filter((item) => item.name.toLowerCase().includes(query.toLowerCase())), [municipalities.data, query]);

  if (municipalities.isLoading) return <LoadingState />;
  if (municipalities.isError) return <ErrorState />;

  const showSearch = (municipalities.data?.length || 0) >= 8;

  return (
    <div className="space-y-14">
      <section className="map-motif grid min-h-[360px] items-center gap-8 overflow-hidden rounded-2xl border bg-emerald-50/60 px-6 py-12 md:px-10 lg:grid-cols-[1fr_360px]">
        <div><p className="eyebrow">Дигитална услуга на вашата општина</p><h1 className="mt-3 max-w-3xl text-5xl font-extrabold tracking-tight md:text-6xl">Пријави. Следи. Среди.</h1><p className="mt-5 max-w-2xl text-lg text-muted-foreground">Избери општина за да пријавиш локален проблем, да го следиш со приватен код или да ја видиш јавната статистика.</p></div>
        {showSearch ? <div><label htmlFor="municipality-search" className="mb-2 block text-sm font-semibold">Пребарај општина</label><div className="relative"><Search className="absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" /><Input id="municipality-search" className="h-12 bg-white pl-10" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Име на општина" /></div></div> : <div className="rounded-xl border bg-white/80 p-5"><ShieldCheck className="h-8 w-8 text-primary" /><strong className="mt-3 block">Официјален општински канал</strong><p className="mt-1 text-sm text-muted-foreground">Пријавата оди директно во работниот простор на избраната општина.</p></div>}
      </section>

      <section aria-labelledby="municipalities-title"><div className="mb-5"><p className="eyebrow">Достапни општини</p><h2 id="municipalities-title" className="mt-2 text-3xl font-extrabold">Избери каде е проблемот</h2></div><div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {filtered.map((municipality) => <Link key={municipality.id} to={`/${municipality.slug}`} className="group rounded-lg"><Card className="h-full transition-colors group-hover:border-primary/50"><CardContent className="flex h-full gap-4 p-6"><span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-primary">{municipality.official_coat_of_arms_url ? <img src={municipality.official_coat_of_arms_url} alt="" className="h-9 w-9 object-contain" /> : <MapPin className="h-6 w-6" />}</span><div className="flex min-w-0 flex-1 flex-col"><h3 className="text-xl font-bold">{municipality.name}</h3><p data-visual-mask className="mt-2 text-sm text-muted-foreground">{municipality.active_report_count} активни {municipality.active_report_count === 1 ? "пријава" : "пријави"}</p><p className="mt-1 text-xs text-muted-foreground">{municipality.latest_public_notice ? `Последно известување: ${formatDate(municipality.latest_public_notice.published_at)}` : "Сè уште нема јавно известување"}</p><span className="mt-5 inline-flex items-center gap-1 text-sm font-bold text-primary">Отвори ја општинската услуга <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" /></span></div></CardContent></Card></Link>)}
        <a href="mailto:partneri@sredi.mk?subject=Интерес%20за%20приклучување%20на%20општина" className="group rounded-lg"><Card className="h-full border-dashed"><CardContent className="flex gap-4 p-6"><span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-800"><Building2 className="h-6 w-6" /></span><div><h3 className="text-xl font-bold">Вашата општина не е тука?</h3><p className="mt-2 text-sm text-muted-foreground">Испратете е-пошта за интерес. Платформата не собира податоци преку оваа врска.</p><span className="mt-4 inline-flex items-center gap-1 text-sm font-bold text-primary">Контактирај нè <ArrowRight className="h-4 w-4" /></span></div></CardContent></Card></a>
      </div></section>

      <section className="grid gap-4 rounded-xl border bg-white p-5 md:grid-cols-3" aria-label="Доверба и приватност">
        {[[LockKeyhole, "Без профил", "Пријави и следи без корисничка сметка."], [CheckCircle2, "Приватен код", "Само лицето со кодот го отвора својот статус."], [BarChart3, "Агрегирана отчетност", "Јавно се прикажуваат групирани податоци, не пријави."]].map(([Icon, title, text]) => { const TrustIcon = Icon as typeof Send; return <div key={String(title)} className="flex gap-3 p-2"><TrustIcon className="h-6 w-6 shrink-0 text-primary" /><div><strong>{String(title)}</strong><p className="mt-1 text-sm text-muted-foreground">{String(text)}</p></div></div>; })}
      </section>
    </div>
  );
}
