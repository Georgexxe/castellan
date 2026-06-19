import type { Metadata } from "next";
import { Fraunces, Archivo, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { SiteHeader } from "@/components/SiteHeader";

// Fraunces — the seal. Used only at ceremonial/record moments (wordmark, head-hash
// verdict, chain title). opsz/SOFT/WONK give it an engraved, authoritative cut.
const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  axes: ["opsz", "SOFT", "WONK"],
  display: "swap",
});

// Archivo — the workhorse. All UI furniture: headers, labels, nav, buttons, body.
const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  display: "swap",
});

// IBM Plex Mono — the proof tissue. All hashes, ids, JSON.
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Castellan Mission Control",
  description:
    "A sealed operations ledger for the Castellan autonomous cloud-security remediation pipeline.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${archivo.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-ink-800 text-fg">
        <SiteHeader />
        <main className="flex-1 w-full">{children}</main>
        <footer className="border-t border-ink-600 px-5 py-3 text-[11px] uppercase tracking-[0.14em] text-fg-faint sm:px-8">
          <span className="font-mono">read-only bridge</span> · the audit is the
          authority — the UI only shows what the proven functions compute
        </footer>
      </body>
    </html>
  );
}
