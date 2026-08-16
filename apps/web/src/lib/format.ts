/**
 * Formatting helpers.
 *
 * Every date is rendered in UTC with an explicit locale. These pages are
 * server-rendered, so relying on the runtime's locale or timezone would make
 * the output depend on which machine happened to render it — and would show a
 * US legislative date shifted by the reader's offset.
 */

const DATE = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

const DATETIME = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  timeZoneName: "short",
});

export function formatDate(value?: string | Date | null): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return Number.isNaN(d.getTime()) ? "—" : DATE.format(d);
}

export function formatDateTime(value?: string | Date | null): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return Number.isNaN(d.getTime()) ? "—" : DATETIME.format(d);
}

/** "H.R. 3424", "S. 331" — the citation form readers recognise. */
export function formatBillNumber(billType: string, number: number): string {
  const pretty: Record<string, string> = {
    hr: "H.R.",
    s: "S.",
    hjres: "H.J.Res.",
    sjres: "S.J.Res.",
    hconres: "H.Con.Res.",
    sconres: "S.Con.Res.",
    hres: "H.Res.",
    sres: "S.Res.",
  };
  return `${pretty[billType] ?? billType.toUpperCase()} ${number}`;
}

export function billHref(congress: number, billType: string, number: number): string {
  return `/bills/${congress}/${billType}/${number}`;
}

/** "119th", "120th" — ordinal Congress numbering. */
export function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  return `${n}${{ 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th"}`;
}

export function formatChamber(chamber?: string | null): string {
  if (!chamber) return "—";
  return { house: "House", senate: "Senate", joint: "Joint" }[chamber] ?? chamber;
}

/** House members have a district; senators do not (PRD §3). */
export function formatSeat(
  chamber?: string | null,
  state?: string | null,
  district?: number | null,
): string {
  if (!state) return formatChamber(chamber);
  if (chamber === "senate" || district === null || district === undefined) {
    return `${state} · ${formatChamber(chamber)}`;
  }
  return `${state}-${district === 0 ? "At Large" : district}`;
}
