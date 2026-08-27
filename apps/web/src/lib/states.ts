/**
 * State FIPS codes and names.
 *
 * The Census keys everything by FIPS; every table in this project stores the
 * two-letter postal code. Anything that turns one into the other goes through
 * here, so a district page and the address lookup cannot end up disagreeing
 * about which state a GEOID belongs to.
 *
 * Territories are included because they hold congressional districts too —
 * Delegate and Resident Commissioner seats, which the boundary loader
 * currently skips (their CD code '98' is outside the `district` table's CHECK)
 * but whose GEOIDs a reader can still arrive at.
 */

export const STATE_BY_FIPS: Record<string, string> = {
  "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
  "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
  "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
  "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
  "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
  "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
  "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
  "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
  "54": "WV", "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP",
  "72": "PR", "78": "VI",
};

export const STATE_NAMES: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas",
  CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware",
  DC: "District of Columbia", FL: "Florida", GA: "Georgia", HI: "Hawaii",
  ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas",
  KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
  MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma",
  OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah",
  VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia",
  WI: "Wisconsin", WY: "Wyoming", AS: "American Samoa", GU: "Guam",
  MP: "Northern Mariana Islands", PR: "Puerto Rico", VI: "U.S. Virgin Islands",
};

/**
 * The state a district GEOID belongs to, or null if the leading two digits are
 * not a FIPS code.
 *
 * This is what separates "a district we have not loaded" from "not a district
 * at all", which the district page has to tell apart: the first is a coverage
 * limit to explain and the second is a 404.
 */
export function stateFromGeoid(geoid: string): string | null {
  return STATE_BY_FIPS[geoid.slice(0, 2)] ?? null;
}
