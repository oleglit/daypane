import { fetchJson, cached } from '../cache.js';
import { getConfig } from '../config.js';

// Free, keyless FX rates. Base is configurable (default USD).
export async function getFx() {
  const base = getConfig().fxBase;
  const url = `https://open.er-api.com/v6/latest/${encodeURIComponent(base)}`;
  return cached('fx:' + base, 5 * 60 * 1000, async () => {
    const r = await fetchJson(url);
    if (!r.ok || !r.data?.rates) return { ok: false, error: r.error, base };
    const rates = r.data.rates;
    const num = (v) => {
      const n = Number(v);
      return v === null || v === '' || v === undefined || !Number.isFinite(n) ? null : n;
    };
    const usd = num(rates.USD);
    const uah = num(rates.UAH);
    const gbp = num(rates.GBP);
    if (usd === null && uah === null && gbp === null) {
      return { ok: false, error: 'invalid FX payload', base };
    }
    return {
      ok: true,
      base,
      updated: r.data.time_last_update_utc,
      usd,
      uah,
      gbp,
      source: 'open.er-api.com'
    };
  });
}
