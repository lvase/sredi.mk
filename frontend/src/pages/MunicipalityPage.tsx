import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BarChart3, CheckCircle2, Clock3, Mail, PlusCircle, Search, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import type { Municipality, PublicStatisticsPayload } from "../lib/types";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { MetricCard } from "../components/shared";
import { formatDate } from "../lib/utils";

export function MunicipalityPage() {
  const { municipalitySlug = "" } = useParams();
  const municipality = useQuery({ queryKey: ["municipality", municipalitySlug], queryFn: () => api.get<Municipality>(`/municipalities/${municipalitySlug}/`) });
  const statistics = useQuery({ queryKey: ["statistics-summary", municipalitySlug], queryFn: () => api.get<PublicStatisticsPayload>(`/municipalities/${municipalitySlug}/statistics/?period=90`) });

  if (municipality.isLoading || statistics.isLoading) return <LoadingState />;
  if (municipality.isError || !municipality.data) return <ErrorState message="Општината не е пронајдена." />;
  const stats = statistics.data?.stats;
  const accent = municipality.data.public_accent_color || "#176B52";

  return (
    <div className="space-y-12">
      <section className="grid items-center gap-8 rounded-2xl border bg-white p-6 md:p-9 lg:grid-cols-[1fr_360px]" style={{ borderTopColor: accent, borderTopWidth: 5 }}>
        <div><div className="flex items-center gap-3">{municipality.data.official_coat_of_arms_url ? <img src={municipality.data.official_coat_of_arms_url} alt={`Официјален грб — ${municipality.data.name}`} className="h-14 w-14 object-contain" /> : <CheckCircle2 className="h-10 w-10" style={{ color: accent }} />}<p className="eyebrow">Среди · официјална општинска услуга</p></div><h1 className="mt-4 text-5xl font-extrabold tracking-tight md:text-6xl">{municipality.data.name}</h1><p className="mt-4 max-w-2xl text-lg text-muted-foreground">Кажи ни што треба да се среди. Ќе добиеш приватен код за следење, без задолжителна регистрација.</p><Button asChild size="lg" className="mt-7 min-w-60" style={{ backgroundColor: accent }}><Link to={`/${municipalitySlug}/prijavi`}><PlusCircle className="h-5 w-5" /> Пријави проблем</Link></Button><div className="mt-4 flex flex-wrap gap-2"><Button asChild variant="outline"><Link to={`/${municipalitySlug}/sledi`}><Search className="h-4 w-4" /> Следи пријава</Link></Button><Button asChild variant="outline"><Link to={`/${municipalitySlug}/statistika`}><BarChart3 className="h-4 w-4" /> Јавна статистика</Link></Button></div></div>
        <Card className="bg-emerald-50/50"><CardContent className="p-6"><ShieldCheck className="mb-4 h-9 w-9 text-primary" /><h2 className="text-xl font-bold">Твојот код е приватен</h2><p className="mt-2 text-sm text-muted-foreground">Зачувај го по поднесувањето. Јавната статистика не содржи наслови, описи, локации, фотографии или контакт податоци.</p></CardContent></Card>
      </section>

      <section><h2 className="mb-4 text-2xl font-extrabold">Последни 90 дена</h2><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><MetricCard label="Вкупно пријави" value={stats?.total ?? "—"} /><MetricCard label="Активни" value={stats?.open ?? municipality.data.active_report_count} tone="info" /><MetricCard label="Решени" value={stats?.resolved ?? "—"} tone="success" /><MetricCard label="Чекаат проверка" value={stats?.pending ?? "—"} tone="warning" /></div></section>

      <section className="grid gap-5 lg:grid-cols-[1.25fr_.75fr]"><div><p className="eyebrow">Како работи</p><h2 className="mt-2 text-3xl font-extrabold">Три јасни чекори</h2><div className="mt-5 grid gap-4 md:grid-cols-3">{[["1", "Пријави", "Одбери место и категорија, опиши го проблемот и по желба додај фотографии."], ["2", "Општината постапува", "Службениците ја проверуваат и ја доделуваат пријавата на надлежниот тим."], ["3", "Следи го исходот", "Со приватниот код го гледаш тековниот статус и јавните ажурирања."]].map(([step, title, text]) => <Card key={step}><CardContent className="p-5"><span className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 font-extrabold text-primary">{step}</span><h3 className="mt-4 font-bold">{title}</h3><p className="mt-2 text-sm text-muted-foreground">{text}</p></CardContent></Card>)}</div></div><Card><CardContent className="p-6"><Mail className="h-7 w-7 text-primary" /><h2 className="mt-3 text-xl font-bold">Треба помош?</h2><p className="mt-2 text-sm text-muted-foreground">За итна опасност јави се кај надлежните служби. За помош со порталот испрати е-пошта.</p><a className="mt-4 inline-flex items-center gap-1 text-sm font-bold text-primary" href={`mailto:info@${municipalitySlug}.gov.mk`}>Контакт со општината <ArrowRight className="h-4 w-4" /></a></CardContent></Card></section>

      {municipality.data.latest_public_notice ? <section><Card><CardContent className="p-6 md:p-8"><div className="flex gap-3"><Clock3 className="h-6 w-6 shrink-0 text-primary" /><div><p className="eyebrow">Последно известување · {formatDate(municipality.data.latest_public_notice.published_at)}</p><h2 className="mt-2 text-2xl font-extrabold">{municipality.data.latest_public_notice.title}</h2><p className="mt-3 text-muted-foreground">{municipality.data.latest_public_notice.summary}</p><details className="mt-4"><summary className="cursor-pointer font-bold text-primary">Прочитај повеќе</summary><p className="mt-3 whitespace-pre-line text-sm leading-7">{municipality.data.latest_public_notice.body}</p></details></div></div></CardContent></Card></section> : null}
    </div>
  );
}
