/**
 * Format timestamps in US equities market time (America/New_York).
 * Naive ISO strings (no Z / offset) are treated as UTC, matching how the
 * backend historically stored datetimes.
 */

export const MARKET_TIMEZONE = 'America/New_York';

const MARKET_TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  timeZone: MARKET_TIMEZONE,
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
};

const MARKET_TIME_SHORT_OPTIONS: Intl.DateTimeFormatOptions = {
  timeZone: MARKET_TIMEZONE,
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
};

export function parseTimestamp(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const trimmed = iso.trim();
  const hasTz = /Z$/i.test(trimmed) || /[+-]\d{2}:\d{2}$/.test(trimmed);
  const d = new Date(hasTz ? trimmed : `${trimmed}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatMarketTime(iso: string | null | undefined): string {
  const d = parseTimestamp(iso);
  if (!d) return '';
  return d.toLocaleString('en-US', MARKET_TIME_OPTIONS);
}

export function formatMarketTimeShort(iso: string | null | undefined): string {
  const d = parseTimestamp(iso);
  if (!d) return '';
  return d.toLocaleString('en-US', MARKET_TIME_SHORT_OPTIONS);
}
