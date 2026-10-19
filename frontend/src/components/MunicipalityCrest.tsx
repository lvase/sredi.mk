import konceCrest from "../assets/municipalities/konce-coat-of-arms.png";
import radovisCrest from "../assets/municipalities/radovis-coat-of-arms.png";
import type { Municipality } from "../lib/types";

const bundledCrests: Partial<Record<string, string>> = {
  konce: konceCrest,
  radovis: radovisCrest
};

type MunicipalityCrestProps = {
  municipality: Municipality;
  size?: "hero" | "list";
  decorative?: boolean;
};

function municipalityCrestSource(municipality: Municipality) {
  return municipality.official_coat_of_arms_url || bundledCrests[municipality.slug] || null;
}

export function MunicipalityCrest({
  municipality,
  size = "hero",
  decorative = false
}: MunicipalityCrestProps) {
  const source = municipalityCrestSource(municipality);
  const imageClass = size === "hero"
    ? "block max-h-28 max-w-28 object-contain"
    : "block max-h-14 max-w-14 object-contain";

  if (!source) {
    return (
      <span
        aria-hidden="true"
        className={size === "hero" ? "text-6xl font-black" : "text-2xl font-black"}
        style={{ color: municipality.public_accent_color || "#176B52" }}
      >
        {municipality.name.slice(0, 1)}
      </span>
    );
  }

  return (
    <img
      src={source}
      alt={decorative ? "" : `Официјален грб — ${municipality.name}`}
      className={imageClass}
      decoding="async"
      loading={size === "list" ? "lazy" : "eager"}
    />
  );
}
