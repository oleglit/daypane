import { cached } from '../cache.js';

// Основные украинские новости из открытых RSS-лент.
// Заголовки сохраняются на языке источника (украинском), без тематической фильтрации.
const SOURCES = [
  ['https://www.pravda.com.ua/rss/', 'Українська правда'],
  ['https://suspilne.media/rss/all.rss', 'Суспільне'],
  ['https://feeds.bbci.co.uk/ukrainian/rss.xml', 'BBC News Україна']
];

const ENTITIES = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  ldquo: '“', rdquo: '”', lsquo: '‘', rsquo: '’', hellip: '…',
  mdash: '—', ndash: '–', middot: '·', laquo: '«', raquo: '»'
};

function cleanTitle(raw) {
  return String(raw || '')
    .replace(/<[^>]+>/g, '')
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, code) => {
      const key = code.toLowerCase();
      if (key[0] === '#') {
        const n = key[1] === 'x' ? parseInt(key.slice(2), 16) : parseInt(key.slice(1), 10);
        if (Number.isFinite(n) && n > 0 && n <= 0x10ffff) {
          try { return String.fromCodePoint(n); } catch { return m; }
        }
        return m;
      }
      return Object.prototype.hasOwnProperty.call(ENTITIES, key) ? ENTITIES[key] : m;
    })
    .replace(/\s+/g, ' ')
    .trim();
}

function parseRss(xml, source, max) {
  const items = xml.match(/<item(?:\s[^>]*)?>[\s\S]*?<\/item>/gi) || [];
  const out = [];
  for (const item of items) {
    const title = item.match(/<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/title>/i);
    const link = item.match(/<link>([\s\S]*?)<\/link>/i);
    const value = title ? cleanTitle(title[1]) : '';
    if (value) out.push({ title: value, source, url: link ? cleanTitle(link[1]) : '' });
    if (out.length >= max) break;
  }
  return out;
}

async function fetchRss(url, source) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 9000);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; DayPane/1.0)', Accept: 'application/rss+xml, application/xml, text/xml' }
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return parseRss(await response.text(), source, 8);
  } finally {
    clearTimeout(timer);
  }
}

export function getNews() {
  return cached('news-ukraine', 10 * 60 * 1000, async () => {
    const results = await Promise.allSettled(SOURCES.map(([url, source]) => fetchRss(url, source)));
    const items = [];
    const errors = [];
    results.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        for (const item of result.value) {
          if (!items.some((existing) => existing.title === item.title)) items.push(item);
          if (items.length >= 12) break;
        }
      } else {
        errors.push(SOURCES[index][1] + ': ' + (result.reason?.message || 'feed unavailable'));
      }
    });
    return {
      ok: items.length > 0,
      items: items.slice(0, 8),
      source: 'Українська правда + Суспільне + BBC News Україна',
      error: items.length ? null : errors.join('; ')
    };
  });
}
