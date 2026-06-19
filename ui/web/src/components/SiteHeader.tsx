"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type NavItem = { label: string; href: string; ready: boolean };

const NAV: NavItem[] = [
  { label: "Dashboard", href: "/", ready: true },
  { label: "Audit Chain", href: "/chain", ready: true },
  { label: "Lifecycle", href: "/lifecycle", ready: true },
  { label: "Reversibility", href: "/reversibility", ready: true },
];

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-20 border-b border-ink-600 bg-ink-900/95 backdrop-blur-0">
      <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3 px-5 py-3 sm:px-8">
        <Link href="/" className="group flex items-baseline gap-3">
          {/* Fraunces — ceremonial: the wordmark */}
          <span className="font-display text-[22px] font-semibold leading-none tracking-tight text-fg">
            Castellan
          </span>
          <span className="font-sans text-[10px] uppercase tracking-[0.28em] text-fg-faint">
            Mission Control
          </span>
        </Link>

        <nav aria-label="Primary" className="flex flex-wrap items-center gap-1">
          {NAV.map((item) => {
            const active = pathname === item.href;
            if (!item.ready) {
              return (
                <span
                  key={item.href}
                  aria-disabled="true"
                  title="Coming after the chain is approved"
                  className="flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-[13px] text-fg-faint/70"
                >
                  {item.label}
                  <span className="font-mono text-[9px] uppercase tracking-wider text-fg-faint/60">
                    soon
                  </span>
                </span>
              );
            }
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={[
                  "rounded-sm px-3 py-1.5 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-brass/10 text-brass-bright"
                    : "text-fg-muted hover:text-fg",
                ].join(" ")}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
