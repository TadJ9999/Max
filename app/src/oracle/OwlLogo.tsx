// Owl of Athena — Oracle's mark. Minimalist line-art owl (wisdom / prophecy),
// drawn with currentColor so it inherits the neon house style and a subtle glow.
// Used in the Hub tab strip, the launcher button, and the view header.

export function OwlLogo({ size = 20, glow = false }: { size?: number; glow?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={glow ? "owl-logo owl-logo--glow" : "owl-logo"}
      aria-hidden="true"
    >
      {/* head + ear tufts */}
      <path
        d="M5 9 C5 5.5 8 3 12 3 C16 3 19 5.5 19 9"
        stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"
      />
      <path d="M5.5 8 L4 4.5 M18.5 8 L20 4.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      {/* body */}
      <path
        d="M5 9 C5 15 7.5 21 12 21 C16.5 21 19 15 19 9"
        stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"
      />
      {/* facial disc / brow */}
      <path d="M12 6.5 L12 12 M7.5 8.5 C9 7 10.7 7.2 12 8.4 C13.3 7.2 15 7 16.5 8.5"
        stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
      {/* the two big knowing eyes */}
      <circle cx="9" cy="10.4" r="2.05" stroke="currentColor" strokeWidth="1.15" />
      <circle cx="15" cy="10.4" r="2.05" stroke="currentColor" strokeWidth="1.15" />
      <circle cx="9" cy="10.4" r="0.7" fill="currentColor" />
      <circle cx="15" cy="10.4" r="0.7" fill="currentColor" />
      {/* beak */}
      <path d="M12 12 L11 13.4 L12 14 L13 13.4 Z" stroke="currentColor" strokeWidth="0.9" strokeLinejoin="round" />
      {/* folded wings */}
      <path d="M6.5 12 C7.5 14.5 8 16.5 8.2 18.5 M17.5 12 C16.5 14.5 16 16.5 15.8 18.5"
        stroke="currentColor" strokeWidth="0.9" strokeLinecap="round" opacity="0.7" />
      {/* talons on a branch */}
      <path d="M9 21 L9 22.4 M12 21 L12 22.6 M15 21 L15 22.4 M6.5 22.6 L17.5 22.6"
        stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.8" />
    </svg>
  );
}
