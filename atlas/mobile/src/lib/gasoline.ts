// Words for the gasoline card's crude oil sentence. Every number comes from the server (it checks the gasoline price against crude and works out the gap); this only writes them out.
import type { GasolinePricesData } from "../api/types";
import { ymdLabel } from "./format";

type Crude = NonNullable<GasolinePricesData["crude"]>;

const usd2 = (x: number) => `$${x.toFixed(2)}`;

/** The gasoline price against crude. EIA posts the Monday gasoline price on Tuesday and the crude prices once a week, on Wednesday, so for about a day a week the crude price is that of the Tuesday before: then the sentence says on which day it was (`priceDate` is the Monday, `crude.date` the day of the crude price; with no date, or the same day, nothing is added). */
export function crudeText(crude: Crude, priceDate: string | undefined): string {
  const older = crude.date != null && priceDate != null && crude.date !== priceDate;
  const when = older ? ` (the price of ${ymdLabel(crude.date)}, the newest there is: crude prices come once a week, after the gasoline price)` : "";
  return `That is ${usd2(crude.per_barrel)} a barrel-equivalent (the price times 42 gallons) against WTI crude at ${usd2(crude.wti)} a barrel${when}: a gap of ${usd2(crude.gap)} for refining, distribution, marketing and taxes.`;
}
