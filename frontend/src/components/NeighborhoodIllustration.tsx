/** A schematic neighborhood, not a map of reported issues or real locations. */
export function NeighborhoodIllustration() {
  return <svg className="neighborhood-illustration" viewBox="0 0 480 350" fill="none" aria-hidden="true" focusable="false">
    <rect x="20" y="20" width="440" height="310" rx="28" fill="#29473E" />
    <path d="M20 218H460M160 20V330M335 20V330" stroke="#17372F" strokeWidth="38" />
    <path d="M20 218H460M160 20V330M335 20V330" stroke="#739B86" strokeOpacity=".55" strokeWidth="2" strokeDasharray="8 10" />
    <rect x="48" y="49" width="78" height="63" rx="8" fill="#849D85" />
    <rect x="57" y="58" width="60" height="45" rx="4" fill="#B1C3A9" />
    <path d="M69 70H105M69 82H105M69 94H91" stroke="#58785E" strokeWidth="4" />
    <rect x="52" y="139" width="72" height="44" rx="7" fill="#728F78" />
    <path d="M63 150H113M63 162H113" stroke="#B1C3A9" strokeWidth="4" />
    <rect x="199" y="46" width="98" height="133" rx="16" fill="#426B50" />
    <path d="M218 159L277 65M220 66L277 159" stroke="#7B9A70" strokeWidth="9" strokeLinecap="round" />
    <g fill="#A6CB91" stroke="#426B50" strokeWidth="4"><circle cx="218" cy="73" r="19" /><circle cx="275" cy="143" r="20" /><circle cx="217" cy="143" r="16" /></g>
    <path d="M367 102L407 78L447 102" fill="#E9D8A9" />
    <path d="M374 108H440V167H374Z" fill="#D6C595" />
    <path d="M387 117V153M407 117V153M427 117V153" stroke="#29473E" strokeWidth="7" />
    <path d="M368 170H446" stroke="#E9D8A9" strokeWidth="7" strokeLinecap="round" />
    <rect x="52" y="255" width="72" height="49" rx="7" fill="#9EB29A" />
    <path d="M64 269H111M64 283H98" stroke="#58785E" strokeWidth="4" />
    <rect x="200" y="256" width="98" height="47" rx="8" fill="#849D85" />
    <path d="M214 270H283M214 285H265" stroke="#B1C3A9" strokeWidth="5" />
    <g fill="#83AE76"><circle cx="392" cy="276" r="21" /><circle cx="431" cy="291" r="15" /></g>
    <path d="M160 151V218H335V159" stroke="#BFE5CC" strokeWidth="5" strokeLinecap="round" strokeDasharray="1 12" />
    <circle cx="335" cy="159" r="10" fill="#BFE5CC" stroke="#17372F" strokeWidth="4" />
    <circle cx="160" cy="126" r="40" fill="#BFE5CC" fillOpacity=".13" />
    <path d="M160 159C160 159 185 135 185 119A25 25 0 0 0 135 119C135 135 160 159 160 159Z" fill="#BFE5CC" stroke="#17372F" strokeWidth="4" />
    <circle cx="160" cy="119" r="8" fill="#24634E" />
  </svg>;
}
