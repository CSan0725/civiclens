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

/** Citation prefixes, keyed by the `bill_type` enum. */
const BILL_TYPE_PREFIX: Record<string, string> = {
  hr: "H.R.",
  s: "S.",
  hjres: "H.J.Res.",
  sjres: "S.J.Res.",
  hconres: "H.Con.Res.",
  sconres: "S.Con.Res.",
  hres: "H.Res.",
  sres: "S.Res.",
};

/** What each measure actually is, for a filter menu where the prefix alone is opaque. */
const BILL_TYPE_NAME: Record<string, string> = {
  hr: "House bill",
  s: "Senate bill",
  hjres: "House joint resolution",
  sjres: "Senate joint resolution",
  hconres: "House concurrent resolution",
  sconres: "Senate concurrent resolution",
  hres: "House simple resolution",
  sres: "Senate simple resolution",
};

/** "H.R. 3424", "S. 331" — the citation form readers recognise. */
export function formatBillNumber(billType: string, number: number): string {
  return `${BILL_TYPE_PREFIX[billType] ?? billType.toUpperCase()} ${number}`;
}

/** "H.R. — House bill", for the /bills type filter. */
export function formatBillTypeOption(billType: string): string {
  const prefix = BILL_TYPE_PREFIX[billType] ?? billType.toUpperCase();
  const name = BILL_TYPE_NAME[billType];
  return name ? `${prefix} — ${name}` : prefix;
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

/**
 * "Senate", or "House · Extensions of Remarks" — chamber and Congressional
 * Record section, without saying the same word twice.
 *
 * For House and Senate granules the section label IS the chamber label, so
 * rendering both reads as a bug ("Senate · Senate"). Extensions of Remarks is
 * the case that needs both: it is a House section, and a reader looking at a
 * member's statements should be able to tell a floor remark from one inserted
 * into the Extensions.
 */
export function formatSpeechContext(
  chamber?: string | null,
  section?: string | null,
): string {
  const chamberLabel = formatChamber(chamber);
  if (!section) return chamberLabel;
  if (section === chamberLabel) return chamberLabel;
  if (chamberLabel === "—") return section;
  return `${chamberLabel} · ${section}`;
}

/**
 * "CA-11", "WY-AL" — how a congressional district is written.
 *
 * At-large seats are the reason this is a function and not a template string
 * in three places: the district number is 0, and "CA-0" is not how anyone
 * writes it. Shared between the map panel and the district page so the two
 * cannot drift into naming the same seat differently.
 */
export function formatDistrictLabel(
  state?: string | null,
  cdNumber?: number | null,
  atLarge?: boolean,
): string {
  const code = state ?? "??";
  if (atLarge || cdNumber === 0) return `${code}-AL`;
  if (cdNumber === null || cdNumber === undefined) return code;
  return `${code}-${String(cdNumber).padStart(2, "0")}`;
}

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

/**
 * A campaign-finance amount, or an em dash when the FEC has no figure.
 *
 * Rounded to whole dollars for reading; the exact cents are in the linked
 * source. A MISSING value renders as "—" and a real zero renders as "$0" —
 * "this committee reported nothing" and "the FEC has no report" are different
 * facts and must not collapse into the same cell.
 *
 * The column is `numeric(16,2)`, which the driver hands over as a STRING to
 * avoid the precision loss of a float. Parsing it here is the only place that
 * number becomes a JS number, and it is for display only.
 */
export function formatMoney(value?: string | number | null): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(n) ? USD.format(n) : "—";
}

/**
 * FEC party codes, expanded for display.
 *
 * The FEC writes three-letter codes ("DEM"), Congress.gov writes names
 * ("Democratic"), and the same party chip renders both — so without this a
 * candidate reads as a grey "DEM" on the same page where the member holding
 * the seat reads as "D — Democratic".
 *
 * Expanding a code to the party's own name is not interpretation (PRD FC-1);
 * it is the same fact spelled out. Which is why the map covers only codes with
 * one unambiguous expansion. The FEC's own field is far messier than its
 * documentation suggests — measured over the loaded states it also contains
 * "GOP", "R", "UN", "UNK", "OTH", "NON", "NNE" and the literal "18" — and
 * anything not listed here is rendered verbatim rather than guessed at.
 */
const FEC_PARTY: Record<string, { letter: string; name: string }> = {
  DEM: { letter: "D", name: "Democratic" },
  REP: { letter: "R", name: "Republican" },
  IND: { letter: "I", name: "Independent" },
  LIB: { letter: "L", name: "Libertarian" },
  GRE: { letter: "G", name: "Green" },
  CON: { letter: "C", name: "Constitution" },
  PAF: { letter: "P", name: "Peace and Freedom" },
  PFP: { letter: "P", name: "Peace and Freedom" },
  AIP: { letter: "A", name: "American Independent" },
};

/** `PartyChip` props for an FEC party code, expanded where that is unambiguous. */
export function fecParty(code?: string | null): {
  code: string | null;
  name: string | null;
} {
  if (!code) return { code: null, name: null };
  const known = FEC_PARTY[code.toUpperCase()];
  return known
    ? { code: known.letter, name: known.name }
    : { code, name: null };
}
