export function Logo({ size = 40 }: { size?: number }) {
  return (
    <div
      className="rounded-2xl bg-gradient-to-br from-indigo-400 to-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/30 shrink-0"
      style={{ width: size, height: size }}
    >
      <svg
        width={size * 0.55}
        height={size * 0.55}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"
          fill="white"
          opacity="0.95"
        />
        <circle cx="12" cy="9" r="3" fill="url(#pinGrad)" />
        <defs>
          <linearGradient id="pinGrad" x1="9" y1="6" x2="15" y2="12" gradientUnits="userSpaceOnUse">
            <stop stopColor="#818cf8" />
            <stop offset="1" stopColor="#4f46e5" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  )
}
