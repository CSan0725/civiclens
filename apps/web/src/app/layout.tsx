import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "CivicLens",
    template: "%s · CivicLens",
  },
  description:
    "US Congress activity from official public-domain sources. Raw records only — no ratings, no ideology scores.",
};

/**
 * P0 scaffolding nav.
 *
 * Its only job right now is to make every route in PRD §10 reachable so the
 * placeholder pages can be verified. The real shell — global search, country
 * switcher (FR-D4), freshness indicator, footer provenance line — is P5.
 */
const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/members", label: "Members" },
  { href: "/bills", label: "Bills" },
  { href: "/votes", label: "Votes" },
  { href: "/districts", label: "Districts" },
  { href: "/rankings", label: "Rankings" },
  { href: "/speeches", label: "Speeches" },
  { href: "/methodology", label: "Methodology" },
] as const;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} antialiased`}>
        <div className="flex min-h-dvh flex-col">
          <header className="border-b">
            <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-4">
              <Link href="/" className="font-semibold tracking-tight">
                CivicLens
              </Link>
              <nav aria-label="Main">
                <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
                  {NAV.map((item) => (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className="hover:text-foreground focus-visible:text-foreground"
                      >
                        {item.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </nav>
            </div>
          </header>

          <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
            {children}
          </main>

          <footer className="border-t">
            <div className="mx-auto max-w-6xl px-6 py-6 text-sm text-muted-foreground">
              Built on official public-domain sources. CivicLens does not rate
              or evaluate legislators or legislation.
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
