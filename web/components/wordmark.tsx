import React from "react";

type Props = { className?: string };

/**
 * Clawmoku wordmark: a compact wooden disc (star point + stone) next to the
 * name. Used in header, hero, and favicon placeholders.
 */
export function Wordmark({ className }: Props) {
  return (
    <svg
      viewBox="0 0 168 34"
      aria-hidden
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <radialGradient id="cm-stone" cx="35%" cy="30%" r="75%">
          <stop offset="0%" stopColor="#4a4a4a" />
          <stop offset="80%" stopColor="#0d0d0d" />
        </radialGradient>
        <radialGradient id="cm-wood" cx="30%" cy="30%" r="90%">
          <stop offset="0%" stopColor="#f1dfa9" />
          <stop offset="90%" stopColor="#b98552" />
        </radialGradient>
      </defs>
      {/* wooden puck */}
      <circle cx="17" cy="17" r="15" fill="url(#cm-wood)" stroke="#6b4a1f" strokeWidth="1.4" />
      {/* board lines */}
      <g stroke="#6b4a1f" strokeWidth="0.9" opacity="0.7">
        <line x1="5" y1="11" x2="29" y2="11" />
        <line x1="5" y1="17" x2="29" y2="17" />
        <line x1="5" y1="23" x2="29" y2="23" />
        <line x1="11" y1="5" x2="11" y2="29" />
        <line x1="17" y1="5" x2="17" y2="29" />
        <line x1="23" y1="5" x2="23" y2="29" />
      </g>
      {/* stone at tengen */}
      <circle cx="17" cy="17" r="5.2" fill="url(#cm-stone)" />
      <text
        x="40"
        y="22"
        fontFamily="'Cormorant Garamond', 'Noto Serif SC', serif"
        fontSize="20"
        fontWeight={600}
        fill="#2f1f10"
        letterSpacing="0.5"
      >
        Clawmoku
      </text>
    </svg>
  );
}
