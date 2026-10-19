import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { api, isNotFoundError } from "../lib/api";
import type { Municipality, PublicStatisticsPayload } from "../lib/types";
import { Button } from "../components/ui/button";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { StatStrip } from "../components/shared";
import { MunicipalityCrest } from "../components/MunicipalityCrest";
import { formatDate } from "../lib/utils";
import { NotFoundPage } from "./NotFoundPage";

export function MunicipalityPage() {
  const { municipalitySlug = "" } = useParams();
  const municipality = useQuery({ queryKey: ["municipality", municipalitySlug], queryFn: () => api.get<Municipality>(`/municipalities/${municipalitySlug}/`) });
  const statistics = useQuery({ queryKey: ["statistics-summary", municipalitySlug], queryFn: () => api.get<PublicStatisticsPayload>(`/municipalities/${municipalitySlug}/statistics/?period=90`) });

  if (municipality.isLoading || statistics.isLoading) return <LoadingState />;
  if (isNotFoundError(municipality.error)) return <NotFoundPage />;
  if (municipality.isError || !municipality.data) return <ErrorState message="Општината не е пронајдена." />;
  const stats = statistics.data?.stats;

  return <div className="space-y-10 md:space-y-12">
    <section className="municipality-hero">
      <div className="municipality-hero__crest">
        <MunicipalityCrest municipality={municipality.data} />
      </div>
      <div>
        <p className="eyebrow">Официјална општинска услуга</p>
        <h1 className="display-title">{municipality.data.name}</h1>
        <p className="municipality-hero__lead">Пријави локален проблем и следи како постапува општината. Не е потребна регистрација.</p>
        <div className="hero-actions"><Button asChild size="lg" className="hero-primary"><Link to={`/${municipalitySlug}/prijavi`}>Пријави проблем <ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0" /></Link></Button><Link className="hero-text-link" to={`/${municipalitySlug}/sledi`}>Следи пријава</Link><Link className="hero-text-link" to={`/${municipalitySlug}/statistika`}>Јавна статистика</Link></div>
        <p className="municipality-hero__privacy">По поднесувањето ќе добиеш приватен код. Јавната статистика не прикажува описи, точни локации, фотографии или контактни податоци. <Link className="font-semibold underline underline-offset-4" to="/privatnost">Како ги користиме податоците</Link></p>
      </div>
    </section>

    <div><h2 className="mb-5 text-2xl font-semibold">Последни 90 дена</h2><StatStrip label="Основни показатели" items={[
      { label: "Вкупно пријави", value: stats?.total ?? "—" },
      { label: "Активни", value: stats?.open ?? municipality.data.active_report_count, tone: "info" },
      { label: "Решени", value: stats?.resolved ?? "—", tone: "success" },
      { label: "Чекаат проверка", value: stats?.pending ?? "—", tone: "warning" }
    ]} /></div>

    <section className="grid gap-10 lg:grid-cols-[1fr_320px]">
      <div><p className="eyebrow">Како работи</p><h2 className="mt-2 text-3xl font-semibold">Од пријава до исход</h2><ol className="mt-7 divide-y border-y">{[
        ["01", "Опиши го проблемот", "Одбери место и категорија, внеси локација и краток опис на проблемот."],
        ["02", "Општината го презема случајот", "Службениците ја проверуваат пријавата и ја упатуваат до надлежниот тим."],
        ["03", "Следи го постапувањето", "Со приватниот код го гледаш тековниот статус и јавните ажурирања."]
      ].map(([number, title, text]) => <li key={number} className="grid gap-3 py-6 sm:grid-cols-[56px_1fr]"><span className="font-mono text-sm font-bold text-primary">{number}</span><div><h3 className="text-lg font-bold">{title}</h3><p className="mt-1 max-w-2xl text-muted-foreground">{text}</p></div></li>)}</ol></div>
      <aside className="self-start rounded-lg border bg-white p-6"><h2 className="text-xl font-semibold">Важно</h2><p className="mt-3 text-sm leading-6 text-muted-foreground">За непосредна опасност или итен случај јави се кај надлежната служба. Овој портал е за редовни локални и комунални проблеми.</p><Link className="mt-5 inline-flex min-h-11 items-center font-semibold text-primary" to="/uslovi">Услови за користење →</Link></aside>
    </section>

    {municipality.data.latest_public_notice ? <section className="border-y py-7"><p className="eyebrow">Општинско известување · {formatDate(municipality.data.latest_public_notice.published_at)}</p><h2 className="mt-3 text-3xl font-semibold">{municipality.data.latest_public_notice.title}</h2><p className="mt-3 max-w-3xl text-lg text-muted-foreground">{municipality.data.latest_public_notice.summary}</p><details className="mt-5 max-w-3xl"><summary className="cursor-pointer font-bold text-primary">Прочитај го целото известување</summary><p className="mt-4 whitespace-pre-line leading-7">{municipality.data.latest_public_notice.body}</p></details></section> : null}
  </div>;
}
