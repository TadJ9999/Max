/** Tiny chocolate toy poodle facing right, used in the ChatBar idle animation. */
export function PoodleSprite() {
  return (
    <svg
      viewBox="0 0 46 26"
      width="46"
      height="26"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Tail puff */}
      <circle cx="7" cy="6" r="3.5" fill="#A0522D" />
      {/* Tail stem */}
      <path d="M10 14 Q5 10 7 6" stroke="#8B4513" strokeWidth="2.5" fill="none" strokeLinecap="round" />

      {/* Body */}
      <ellipse cx="21" cy="17" rx="10.5" ry="6.5" fill="#8B4513" />

      {/* Back left leg — extended rearward */}
      <line x1="14" y1="21" x2="9"  y2="26" stroke="#7B3410" strokeWidth="2.5" strokeLinecap="round" />
      {/* Back right leg — tucked forward */}
      <line x1="18" y1="21" x2="21" y2="26" stroke="#7B3410" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="9"  cy="26" r="2.5" fill="#A0522D" />
      <circle cx="21" cy="26" r="2.5" fill="#A0522D" />

      {/* Chest puff */}
      <circle cx="30" cy="17" r="4.5" fill="#A0522D" />

      {/* Front left leg — tucked back */}
      <line x1="26" y1="21" x2="22" y2="26" stroke="#7B3410" strokeWidth="2.5" strokeLinecap="round" />
      {/* Front right leg — extended forward */}
      <line x1="30" y1="21" x2="35" y2="26" stroke="#7B3410" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="22" cy="26" r="2.5" fill="#A0522D" />
      <circle cx="35" cy="26" r="2.5" fill="#A0522D" />

      {/* Neck */}
      <ellipse cx="34" cy="12" rx="3.5" ry="5" fill="#8B4513" />

      {/* Head */}
      <circle cx="37" cy="9" r="6.5" fill="#8B4513" />

      {/* Ear — floppy, hanging toward chin */}
      <ellipse cx="35" cy="14.5" rx="2.5" ry="4.5" fill="#6B3210" transform="rotate(-12, 35, 14.5)" />

      {/* Topknot puff */}
      <circle cx="37" cy="3.5" r="4" fill="#A0522D" />

      {/* Snout */}
      <ellipse cx="42" cy="10.5" rx="2.5" ry="2" fill="#7B3410" />

      {/* Nose */}
      <ellipse cx="44" cy="10" rx="1.3" ry="1" fill="#2d1a0e" />

      {/* Eye */}
      <circle cx="39" cy="8" r="1.4" fill="#1a0800" />
      {/* Eye shine */}
      <circle cx="39.6" cy="7.4" r="0.55" fill="rgba(255,255,255,0.75)" />
    </svg>
  );
}
