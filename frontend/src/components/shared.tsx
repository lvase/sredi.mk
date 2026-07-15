import * as Dialog from "@radix-ui/react-dialog";
import { Children, isValidElement } from "react";
import { Menu, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "./ui/button";
import { Card, CardContent } from "./ui/card";
import { cn } from "../lib/utils";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <header className="page-header">
      <div>{eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}<h1>{title}</h1>{description ? <p>{description}</p> : null}</div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}

export function MetricCard({ label, value, detail, href, tone = "default" }: { label: string; value: React.ReactNode; detail?: string; href?: string; tone?: "default" | "info" | "warning" | "danger" | "success" }) {
  const body = <Card className={cn("metric-card", `metric-card--${tone}`)}><CardContent><p>{label}</p><strong>{value}</strong>{detail ? <small>{detail}</small> : null}</CardContent></Card>;
  return href ? <Link className="metric-card-link" to={href}>{body}</Link> : body;
}

export function EmptyState({ icon, title, description, action }: { icon?: React.ReactNode; title: string; description?: string; action?: React.ReactNode }) {
  return <div className="empty-state">{icon}<h3>{title}</h3>{description ? <p>{description}</p> : null}{action}</div>;
}

export type TimelineStage = { key: string; label: string; state: "complete" | "current" | "upcoming" };
export function StatusTimeline({ stages, exception }: { stages: TimelineStage[]; exception?: string | null }) {
  return (
    <div>
      <ol className="status-timeline" aria-label="Тек на пријавата">
        {stages.map((stage) => <li key={stage.key} data-state={stage.state}><span aria-hidden="true" /><div><strong>{stage.label}</strong><small>{stage.state === "complete" ? "Завршено" : stage.state === "current" ? "Тековно" : "Следно"}</small></div></li>)}
      </ol>
      {exception ? <div className="exception-outcome" role="status">{exception}</div> : null}
    </div>
  );
}

export function MobileNav({ label = "Отвори мени", children, staff = false }: { label?: string; children: React.ReactNode; staff?: boolean }) {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild><Button variant={staff ? "secondary" : "outline"} size="icon" className="mobile-nav-trigger" aria-label={label}><Menu className="h-5 w-5" /></Button></Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className={cn("drawer", staff && "drawer--staff")} aria-describedby={undefined}>
          <div className="drawer__header"><Dialog.Title>{staff ? "Општински инбокс" : "Мени"}</Dialog.Title><Dialog.Close asChild><Button variant="ghost" size="icon" aria-label="Затвори мени"><X className="h-5 w-5" /></Button></Dialog.Close></div>
          <nav>{Children.toArray(children).map((child, index) => isValidElement(child) ? <Dialog.Close asChild key={child.key || index}>{child}</Dialog.Close> : child)}</nav>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
