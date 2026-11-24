import { fetchJson, cached } from '../cache.js';
import { getConfig } from '../config.js';

// WMO weather code -> short Chinese description.
const WMO = {
  0: '晴', 1: '少云', 2: '多云', 3: '阴',
  45: '雾', 48: '雾凇',
  51: '毛毛雨', 53: '小雨', 55: '中雨',
  56: '冻毛雨', 57: '冻雨',
  61: '小雨', 63: '中雨', 65: '大雨',
  66: '冻雨', 67: '冻雨',
  71: '小雪', 73: '中雪', 75: '大雪', 77: '雪粒',
  80: '阵雨', 81: '阵雨', 82: '强阵雨',
  85: '阵雪', 86: '强阵雪',
  95: '雷阵雨', 96: '雷雹', 99: '强雷雹'
};
const wmo = (c) => WMO[c] ?? `码${c}`;

export async function getWeather() {
  const { lat, lon, city } = getConfig().weather;
  // 一次请求同时供页 1（当前天气）与页 2（日出日落 / 未来几天）使用。
  // 多取 4 天不会增加请求数，也不用为慢信息再接一个数据源。
  const url =
    `https://api.open-meteo.com/v1/forecast?latitude=${encodeURIComponent(lat)}&longitude=${encodeURIComponent(lon)}` +
    `&current=temperature_2m,weather_code,relative_humidity_2m` +
    `&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset` +
    `&timezone=auto&forecast_days=4`;
  const timezone = getConfig().display?.timezone || 'Europe/Riga';
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(new Date());
  const datePart = (type) => parts.find((p) => p.type === type)?.value;
  const localDate = `${datePart('year')}-${datePart('month')}-${datePart('day')}`;
  const offsetPart = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone, timeZoneName: 'longOffset'
  }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value || 'GMT+00:00';
  const offset = offsetPart.replace('GMT', '') || '+00:00';
  const moonUrl = `https://api.met.no/weatherapi/sunrise/3.0/moon?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}&date=${localDate}&offset=${encodeURIComponent(offset)}`;

  // 配置可在服务运行中热改。key 里必须带上坐标和城市名，否则改了城市之后的
  // 10 分钟里，画面会显示"新城市 + 老城市的温度"，还带着旧的 fetchedAt。
  return cached('weather:' + city + ':' + lat + ',' + lon, 10 * 60 * 1000, async () => {
    const [r, moonResponse] = await Promise.all([
      fetchJson(url),
      cached('moon:' + city + ':' + lat + ',' + lon + ':' + localDate, 30 * 60 * 1000,
        () => fetchJson(moonUrl, { headers: { 'User-Agent': 'DayPane/1.0 https://github.com/oleglit/daypane' } }))
    ]);
    if (!r.ok) return { ok: false, error: r.error, city };
    const moonProps = moonResponse?.ok ? (moonResponse.data?.properties || {}) : {};
    const eventTime = (event) => {
      const value = event?.time;
      return typeof value === 'string' && /^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}/.test(value)
        ? value.slice(11, 16) : null;
    };
    const c = r.data.current || {};
    const d = (r.data.daily || {});
    const num = (v) => {
      const n = Number(v);
      return v === null || v === '' || v === undefined || !Number.isFinite(n) ? null : n;
    };
    // 温度是整块天气卡的主数值：上游返回 null/字符串/"N/A" 时宁可标不可用，
    // 也不要画出 "null°C  Hnull Lnull" 这种图。
    const temp = num(c.temperature_2m);
    if (temp === null) return { ok: false, error: 'invalid weather payload', city };
    const code = num(c.weather_code);
    const times = Array.isArray(d.time) ? d.time : [];
    const clock = (value) => typeof value === 'string' && /^\d{2}:\d{2}$/.test(value.slice(11, 16))
      ? value.slice(11, 16) : null;
    const days = [];
    for (let i = 0; i < Math.min(4, times.length); i++) {
      const dayCode = num(d.weather_code?.[i]);
      days.push({
        date: String(times[i] || '').slice(5),
        code: dayCode,
        text: dayCode === null ? '' : wmo(dayCode),
        high: num(d.temperature_2m_max?.[i]),
        low: num(d.temperature_2m_min?.[i]),
        sunrise: clock(d.sunrise?.[i]),
        sunset: clock(d.sunset?.[i])
      });
    }
    return {
      ok: true,
      city,
      temp,
      humidity: num(c.relative_humidity_2m),
      code,
      text: code === null ? '' : wmo(code),
      high: num(d.temperature_2m_max?.[0]),
      low: num(d.temperature_2m_min?.[0]),
      sunrise: days[0]?.sunrise ?? null,
      sunset: days[0]?.sunset ?? null,
      moonrise: eventTime(moonProps.moonrise),
      moonset: eventTime(moonProps.moonset),
      moonPhase: Number.isFinite(Number(moonProps.moonphase?.value)) ? Number(moonProps.moonphase.value) : null,
      days,
      source: 'open-meteo'
    };
  });
}
