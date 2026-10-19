import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowRight, Check, Search, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import type { Municipality } from "../lib/types";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { MunicipalityCrest } from "../components/MunicipalityCrest";
import { NeighborhoodIllustration } from "../components/NeighborhoodIllustration";
import { formatDate } from "../lib/utils";

const steps = [
  ["01", "Забележи проблем.", "Улично светло, отпад или оштетен пат? Избери ја општината во која се наоѓа проблемот."],
  ["02", "Кажи што треба да се среди.", "Додај локација и краток опис за општината да може да го пронајде проблемот."],
  ["03", "Следи го одговорот.", "Зачувај го приватниот код. Со него го проверуваш статусот и одговорот од општината."]
];

export function HomePage() {
  const [query, setQuery] = useState("");
  const municipalities = useQuery({ queryKey: ["municipalities"], queryFn: () => api.get<Municipality[]>("/municipalities/") });
  const filtered = useMemo(() => (municipalities.data || []).filter((item) => item.name.toLowerCase().includes(query.toLowerCase())), [municipalities.data, query]);
  const showSearch = (municipalities.data?.length || 0) >= 8;

  return <div className="home-page">
    <section className="civic-hero" aria-labelledby="home-title">
      <div className="container civic-hero__grid">
        <div>
          <p className="eyebrow">Твоето место. Твојот глас.</p>
          <h1 id="home-title">Пријави проблем.<br /><span>Ние ќе го средиме.</span></h1>
          <p className="civic-hero__lead">Подобра општина почнува со една пријава. Кажи што треба да се среди и следи како постапува општината.</p>
          <div className="hero-actions">
            <Button asChild size="lg" className="hero-primary"><a href="#municipalities">Избери општина <ArrowRight aria-hidden="true" className="h-5 w-5 shrink-0" /></a></Button>
            <a className="hero-text-link" href="#how-it-works">Како работи <ArrowDown aria-hidden="true" className="h-4 w-4 shrink-0" /></a>
          </div>
          <p className="hero-assurance"><Check aria-hidden="true" className="h-4 w-4 shrink-0" /> Без регистрација. Директно до општината.</p>
        </div>
        <div className="neighborhood-panel">
          <div className="neighborhood-panel__heading"><span className="neighborhood-dot" />За местата што ни значат.</div>
          <NeighborhoodIllustration />
          <p>Твојата улица. Твојот парк.<br /><strong>Нашата заедничка грижа.</strong></p>
        </div>
      </div>
    </section>

    <section id="how-it-works" className="steps-band" aria-labelledby="steps-title">
      <div className="container">
        <h2 id="steps-title" className="eyebrow">Од забележан проблем до општинска пријава</h2>
        <ol className="home-steps">{steps.map(([number, title, description]) => <li key={number}>
          <span className="step-number" aria-hidden="true">{number}</span>
          <h3>{title}</h3><p>{description}</p>
        </li>)}</ol>
      </div>
    </section>

    <section id="municipalities" className="home-section" aria-labelledby="municipalities-title">
      <div className="container">
        <div className="mb-8 flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div><p className="eyebrow">Почни од твоето место</p><h2 id="municipalities-title" className="section-title">Избери општина.</h2><p className="mt-4 max-w-xl text-muted-foreground">Пријави нов проблем, следи постоечка пријава или разгледај ги јавните показатели.</p></div>
          {showSearch ? <div className="w-full md:max-w-xs"><label htmlFor="municipality-search" className="mb-1 block text-sm font-semibold">Пребарај општина</label><div className="relative"><Search aria-hidden="true" className="absolute left-3 top-4 h-4 w-4 text-muted-foreground" /><Input id="municipality-search" className="pl-9" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Име на општина" /></div></div> : null}
        </div>
        {municipalities.isLoading ? <LoadingState /> : municipalities.isError ? <ErrorState /> : <div className="municipality-list">
          {filtered.map((municipality) => <Link key={municipality.id} to={`/${municipality.slug}`} className="municipality-row">
            <div className="municipality-row__crest" aria-hidden="true"><MunicipalityCrest municipality={municipality} size="list" decorative /></div>
            <div><h3>{municipality.name}</h3><p data-visual-mask className="mt-2 text-sm text-muted-foreground">{municipality.active_report_count} активни {municipality.active_report_count === 1 ? "пријава" : "пријави"} · {municipality.latest_public_notice ? `известување од ${formatDate(municipality.latest_public_notice.published_at)}` : "нема ново известување"}</p><span className="row-action mt-4">Отвори ја услугата <ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0" /></span></div>
          </Link>)}
          {!filtered.length ? <p className="px-6 py-10 text-muted-foreground">{query ? "Не е пронајдена општина со тоа име." : "Моментално нема достапни општини."}</p> : null}
        </div>}
        <div className="partnership-note"><div><h3 className="font-semibold">Вашата општина сè уште не е достапна?</h3><p className="mt-1 text-sm text-muted-foreground">Приклучете ја на официјалната услуга за граѓани.</p></div><a href="mailto:partneri@sredi.mk?subject=Интерес%20за%20приклучување%20на%20општина" className="inline-flex min-h-11 items-center gap-3 font-semibold text-primary">Контакт за приклучување <ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0" /></a></div>
      </div>
    </section>

    <section className="privacy-band" aria-labelledby="privacy-title">
      <div className="container privacy-band__grid">
        <div><ShieldCheck aria-hidden="true" className="mb-5 h-8 w-8" /><h2 id="privacy-title" className="section-title">Јавна отчетност.<br /><span>Лична приватност.</span></h2><Link className="hero-text-link mt-6" to="/privatnost">Како ги користиме податоците <ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0" /></Link></div>
        <div className="privacy-principles">
          <div><h3>Без кориснички профил</h3><p>Пријавувањето и следењето не бараат регистрација.</p></div>
          <div><h3>Твој приватен код</h3><p>Кодот за следење е само за тебе. Зачувај го внимателно.</p></div>
          <div><h3>Показатели за сите</h3><p>Јавната статистика не прикажува лични податоци, фотографии или точни локации.</p></div>
        </div>
      </div>
    </section>
  </div>;
}
