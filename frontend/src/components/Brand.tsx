import { Link } from "react-router-dom";
import { cn } from "../lib/utils";

export function BrandMark({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg className={cn("shrink-0", className)} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <rect width="64" height="64" rx="16" fill="currentColor" />
      <path d="M18 20h24M18 44h28V32" stroke="white" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M42 22 29 35l-7-7" stroke="#A7F3D0" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function PublicBrand({ municipality }: { municipality?: string }) {
  return (
    <Link to="/" className="brand-lockup" aria-label="sredi.mk — почетна">
      <BrandMark />
      <span>
        <strong>sredi.mk</strong>
        {municipality ? <small>{municipality}</small> : null}
      </span>
    </Link>
  );
}

export function StaffBrand() {
  return (
    <Link to="/staff" className="brand-lockup brand-lockup--staff" aria-label="Општински инбокс — работна табла">
      <BrandMark />
      <span><strong>Општински инбокс</strong><small>Службен простор</small></span>
    </Link>
  );
}
