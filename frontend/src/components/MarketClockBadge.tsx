/**
 * Live US equities session clock, sourced from Alpaca via the backend.
 */

import { useCallback, useEffect, useState } from 'react';
import { Clock } from 'lucide-react';
import apiClient from '@/api/client';
import { formatMarketTimeShort } from '@/utils/marketTime';
import type { MarketClock } from '@/types';

export function MarketClockBadge() {
  const [clock, setClock] = useState<MarketClock | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiClient.getMarketClock();
      setClock(data);
    } catch (err) {
      console.error('Failed to load market clock:', err);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  if (!clock) return null;

  const next = clock.is_open
    ? clock.next_close
      ? `Closes ${formatMarketTimeShort(clock.next_close)}`
      : null
    : clock.next_open
      ? `Opens ${formatMarketTimeShort(clock.next_open)}`
      : null;

  return (
    <div
      className="flex flex-col items-end text-right"
      title={clock.source === 'alpaca' ? 'Alpaca market clock' : 'NY wall clock (Alpaca unavailable)'}
    >
      <span className="flex items-center gap-1.5 text-xs text-gray-300">
        <Clock size={12} className="text-primary-400 shrink-0" />
        {formatMarketTimeShort(clock.timestamp)}
        <span
          className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
            clock.is_open
              ? 'bg-green-500/15 text-green-300'
              : 'bg-gray-500/20 text-gray-400'
          }`}
        >
          {clock.is_open ? 'Open' : 'Closed'}
        </span>
      </span>
      {next && <span className="text-[10px] text-gray-500 mt-0.5">{next}</span>}
    </div>
  );
}
