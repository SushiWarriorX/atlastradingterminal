/**
 * When the server's SEC contact setting is missing, the full instruction (which setting, where to put it) is shown ONCE, in the SEC filings card.
 * The other stock cards point to it instead of repeating it: the same five lines three or four times on one screen is noise a beginner has to wade through.
 */
export const SEC_OFF_POINTER = "It needs the SEC contact setting. The steps are in the SEC filings card above.";

/** True for the server's "SEC contact is not set" message, in either of its wordings. */
export const isSecOff = (message: string | null | undefined): boolean => !!message && /ATLAS_SEC_CONTACT is not set/.test(message);

/** An error list without the "SEC contact is not set" message (it is explained once, elsewhere). */
export const withoutSecOff = (errors: string[]): string[] => errors.filter((e) => !isSecOff(e));
