import { Link } from "react-router-dom";
export function PublicBrand({ municipality }: { municipality?: string }) {
  return (
    <Link to="/" className="brand-lockup" aria-label="sredi.mk — почетна">
      <span>
        <strong><span>sredi</span>.mk</strong>
        {municipality ? <small>{municipality}</small> : null}
      </span>
    </Link>
  );
}

export function StaffBrand() {
  return (
    <Link to="/staff" className="brand-lockup brand-lockup--staff" aria-label="Општински инбокс — работна табла">
      <span><strong>Општински инбокс</strong><small>Работен простор</small></span>
    </Link>
  );
}
