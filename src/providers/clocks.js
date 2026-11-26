import { getConfig } from '../config.js';

// Pure local computation — no network needed.
// Intl.DateTimeFormat 构造很贵（要加载 tzdata），每次看板请求为 4 个城市重建
// 8 个实例纯属浪费；按时区缓存即可，配置改了时区也只是多一个 key。
const formatters = new Map();

function forZone(tz) {
  let f = formatters.get(tz);
  if (!f) {
    f = {
      time: new Intl.DateTimeFormat('ru-RU', {
        timeZone: tz, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
      }),
      date: new Intl.DateTimeFormat('zh-CN', {
        timeZone: tz, month: '2-digit', day: '2-digit', weekday: 'short'
      })
    };
    formatters.set(tz, f);
  }
  return f;
}

function timeIn(tz) {
  const f = forZone(tz);
  const now = new Date();
  return { time: f.time.format(now), date: f.date.format(now) };
}

export function getClocks() {
  const items = getConfig().clocks.map((c) => {
    const base = { city: c.city, tz: c.tz };
    try {
      return { ...base, ...timeIn(c.tz) };
    } catch (e) {
      // config.json 里写错一个时区，以前会让整个 /api/dashboard 抛错。
      // 单个时钟坏掉应该只坏它自己那一行。
      return { ...base, ok: false, time: '--:--', date: '--', error: e.message };
    }
  });
  return { ok: true, items };
}
