import { ArrowRight, Home } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "../components/ui/button";

export function NotFoundPage() {
  return (
    <section className="border-y" aria-labelledby="not-found-title">
      <div className="grid min-h-[520px] lg:grid-cols-[1.05fr_.95fr]">
        <div className="flex flex-col justify-center border-t-4 border-primary py-10 lg:border-r lg:px-10 lg:py-14">
          <p className="eyebrow">Грешка · 404</p>
          <h1
            id="not-found-title"
            className="mt-4 max-w-2xl text-5xl font-semibold leading-[.96] tracking-[-.04em] md:text-7xl"
          >
            Оваа страница не е пронајдена.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-7 text-muted-foreground">
            Адресата можеби е погрешно внесена, страницата е преместена или повеќе не е
            достапна.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-4">
            <Button asChild size="lg">
              <Link to="/">
                <Home className="h-5 w-5" /> На почетна
              </Link>
            </Button>
            <Link
              className="inline-flex min-h-11 items-center gap-2 font-bold text-primary underline-offset-4 hover:underline"
              to="/"
            >
              Избери општина <ArrowRight className="h-4 w-4" />
            </Link>
          </div>

          <div className="mt-12 grid max-w-xl gap-5 border-t pt-5 text-sm sm:grid-cols-2">
            <div>
              <strong className="block">Провери ја адресата</strong>
              <p className="mt-1 leading-6 text-muted-foreground">
                Провери дали врската е целосна и дали има погрешно внесен знак.
              </p>
            </div>
            <div>
              <strong className="block">Почни од општината</strong>
              <p className="mt-1 leading-6 text-muted-foreground">
                Од почетната страница можеш повторно да ја отвориш локалната услуга.
              </p>
            </div>
          </div>
        </div>

        <div
          className="relative flex min-h-[300px] items-center justify-center overflow-hidden bg-white px-4 py-12 lg:min-h-full"
          aria-hidden="true"
        >
          <div className="absolute inset-x-0 top-1/4 border-t" />
          <div className="absolute inset-x-0 bottom-1/4 border-t" />
          <div className="absolute inset-y-0 left-1/4 border-l" />
          <div className="absolute inset-y-0 right-1/4 border-l" />
          <div className="absolute left-[12%] top-[14%] h-3 w-3 bg-amber-500" />
          <div className="absolute bottom-[16%] right-[13%] h-4 w-4 bg-primary" />
          <div className="relative border-y-4 border-primary bg-background px-5 py-3 sm:px-8">
            <span className="block text-[clamp(6.5rem,24vw,13rem)] font-semibold leading-none tracking-[-.1em] text-primary">
              404
            </span>
          </div>
          <p className="absolute bottom-6 left-6 border-l-4 border-primary pl-3 text-xs font-bold uppercase tracking-[.12em] text-muted-foreground">
            Нема страница на оваа адреса
          </p>
        </div>
      </div>
    </section>
  );
}
