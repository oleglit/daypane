# -*- coding: utf-8 -*-
"""DayPane 整屏渲染器（PC 端出图，Kindle 端只显示）。

把 /api/dashboard JSON 渲染成 1072x1448 印刷布告栏风整屏图，
16 级灰度（GRAY=128 / LIGHT_GRAY=200）最终 Floyd-Steinberg 抖动转 1-bit PNG。
静态数据（句子库）从 data/ 读；新闻/节日/时钟/额度均由服务端提供。
"""
import sys, os, json, math, re, time, urllib.request, argparse
from datetime import datetime
from zoneinfo import ZoneInfo
try:
    from layout import load_layout
    import slowinfo
except ModuleNotFoundError:
    from tools.layout import load_layout
    from tools import slowinfo
LAYOUT = None

def display_now():
    return datetime.now(ZoneInfo(LAYOUT["timezone"])) if LAYOUT and LAYOUT.get("timezone") else datetime.now()
from PIL import Image, ImageDraw, ImageFont

# Language defaults to Chinese for backward-compatible personal deployments.
LANG = 'ru'
LABELS = {
    '今日新闻 · AI': 'AI News', '新闻源暂不可用': 'News unavailable',
    'AI 用量': 'AI Usage', 'AI 用量 · 电脑离线': 'AI Usage · PC offline',
    'WorkBuddy 用量': 'WorkBuddy usage', 'WorkBuddy 用量 · 电脑离线': 'WorkBuddy usage · PC offline',
    '上下文': 'Context', '已消耗': 'Spent', '本周活动': '7d activity', '·旧': '·stale',
    'Codex 文件': 'Codex files',
    # 单位也要翻译：以前 '2 次' / '42 条 · 4 会话' 是硬编码在格式串里的，
    # 标签翻成英文、单位还留着中文。
    '次': 'times', '条': 'msgs', '会话': 'sessions',
    '剩余': 'Remaining',
    '未安装': 'Not installed', '不可用': 'Unavailable', '天气': 'Weather',
    '天气不可用': 'Weather unavailable', '市场': 'Markets', '世界时钟': 'World Clocks',
    '时钟不可用': 'Clocks unavailable', 'MLB · 道奇 / 教士': 'MLB · LAD / SD (UTC+8)',
    '赛程暂不可用': 'Schedule unavailable', '胜': 'W', '负': 'L',
    '无近期战报': 'No recent game', '今日一句': 'Daily Thought',
    '（编辑 data/quotes.txt）': '(Edit data/quotes.en.txt)',
    # 页 2「慢信息」与页 3「闲读」。固定标签走 tr()，动态句子按 LANG 分叉，
    # 这样英文版永远不会有中文漏到画布上（render() 末尾有 CJK 关卡）。
    '慢信息': 'Slow info', '日光': 'Daylight', '往后几天': 'Coming days',
    '闲读': 'A moment to read', '节气': 'Solar term', '月相': 'Moon phase',
    '日出日落暂不可用': 'Sun times unavailable',
    '未来天气暂不可用': 'Forecast unavailable',
    '天气暂不可用': 'Weather unavailable',
    '节气信息暂不可用': 'Solar terms unavailable',
    '（编辑句子库）': '(Edit the quote files in data/)',
    '左右滑换页': 'Swipe to turn', '顶部点按退出': 'Top to exit',
}

# 记录画上去的文本：英文版里混进中文就说明漏翻译，在渲染时直接拦住。
# （以前只靠人眼看图，于是 '2 次' / '42 条' 这种硬编码在格式串里的单位一直没被发现。）
_DRAWN = []


def _record_texts(draw):
    """包装 draw.text，把画上去的文本记下来，供英文版的 CJK 自检使用。"""
    original = draw.text

    def text(xy, content, *args, **kwargs):
        _DRAWN.append(str(content))
        return original(xy, content, *args, **kwargs)

    draw.text = text
    return draw


def _cjk_leak():
    """返回本次渲染画上去的、含中日韩统一表意文字的文本片段。"""
    return sorted({t for t in _DRAWN if any('\u4e00' <= ch <= '\u9fff' for ch in t)})
CITY_EN = {'深圳':'Shenzhen', '伦敦':'London', '洛杉矶':'Los Angeles', '纽约':'New York', '德里':'Delhi'}
TEAM_EN = dict(zip(
    '响尾蛇 勇士 金莺 红袜 小熊 白袜 红人 守护者 洛基 老虎 太空人 皇家 天使 道奇 马林鱼 酿酒人 双城 大都会 洋基 运动家 费城人 海盗 教士 巨人 水手 红雀 光芒 游骑兵 蓝鸟 国民'.split(),
    'ARI ATL BAL BOS CHC CWS CIN CLE COL DET HOU KC LAA LAD MIA MIL MIN NYM NYY OAK PHI PIT SD SF SEA STL TB TEX TOR WSH'.split()))
WEATHER_EN = {0:'Clear',1:'Mostly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Rime fog',
    51:'Drizzle',53:'Drizzle',55:'Drizzle',56:'Freezing drizzle',57:'Freezing drizzle',
    61:'Rain',63:'Rain',65:'Heavy rain',66:'Freezing rain',67:'Freezing rain',
    71:'Snow',73:'Snow',75:'Heavy snow',77:'Snow grains',80:'Showers',81:'Showers',82:'Heavy showers',
    85:'Snow showers',86:'Snow showers',95:'Thunderstorm',96:'Hailstorm',99:'Hailstorm'}

def tr(text):
    if LANG == 'en':
        return LABELS.get(text, text)
    if LANG == 'ru':
        return {
            '今日新闻 · AI': 'Новости Украины',
            '新闻源暂不可用': 'Новостные источники недоступны',
            '天气': 'Погода',
            '天气不可用': 'Погода недоступна',
            '市场': 'Рынки',
            '世界时钟': 'Мировое время',
            '时钟不可用': 'Время недоступно',
            '慢信息': 'Календарь и природа',
            '日光': 'Световой день',
            '往后几天': 'Прогноз на 3 дня',
            '日出日落暂不可用': 'Нет данных о восходе и закате',
            '未来天气暂不可用': 'Нет прогноза',
            '左右滑换页': 'Листайте экран',
        }.get(text, text)
    return text

def localized_data(data):
    """Translate built-in labels without mutating the Chinese payload."""
    import copy
    d = copy.deepcopy(data)
    if LANG == 'ru':
        w = d.get('weather') or {}
        weather_ru = {0:'Ясно',1:'Преимущественно ясно',2:'Переменная облачность',3:'Пасмурно',
            45:'Туман',48:'Изморозь',51:'Морось',53:'Небольшой дождь',55:'Сильная морось',
            56:'Ледяная морось',57:'Ледяной дождь',61:'Небольшой дождь',63:'Дождь',65:'Сильный дождь',
            66:'Ледяной дождь',67:'Ледяной дождь',71:'Небольшой снег',73:'Снег',75:'Сильный снег',
            77:'Снежная крупа',80:'Ливень',81:'Ливень',82:'Сильный ливень',85:'Снегопад',
            86:'Сильный снегопад',95:'Гроза',96:'Гроза с градом',99:'Сильная гроза с градом'}
        w['text'] = weather_ru.get(w.get('code'), 'Нет описания')
        for day in (w.get('days') or []):
            day['text'] = weather_ru.get(day.get('code'), '—')
        return d
    if LANG != 'en':
        return d
    d['news'] = d.get('newsEn') or {'ok': False, 'items': []}
    w = d.get('weather') or {}
    w['city'] = w.get('cityEn') or CITY_EN.get(w.get('city'), w.get('city', ''))
    w['text'] = WEATHER_EN.get(w.get('code'), 'Unknown')
    # 页 2 的未来几天也自带中文天气描述，英文出图必须一起换掉。
    for day in (w.get('days') or []):
        day['text'] = WEATHER_EN.get(day.get('code'), 'Unknown')
    for stock in (d.get('stocks') or {}).get('items', []):
        stock['label'] = stock.get('labelEn') or stock.get('sym', '')
    for clock in (d.get('clocks') or {}).get('items', []):
        clock['city'] = clock.get('cityEn') or CITY_EN.get(clock.get('city'), clock.get('tz', '').split('/')[-1].replace('_', ' '))
        date = clock.get('date', '')
        for zh, en in zip('一二三四五六日', ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']):
            date = date.replace('周' + zh, en)
        clock['date'] = date.replace('月','/').replace('日','')
    for team in (d.get('mlb') or {}).get('items', []):
        team['cn'] = team.get('abbr', '')
        for key in ('last', 'next'):
            game = team.get(key)
            if game:
                game['opp'] = TEAM_EN.get(game.get('opp'), game.get('opp', ''))
                if game.get('live'): game['time'] = 'Live'
    return d

# ---------- 屏幕与设计常量 ----------
SCREEN_W, SCREEN_H = 1072, 1448
PAD = 40
CONTENT_W = SCREEN_W - 2 * PAD
BLACK, GRAY, LIGHT_GRAY, WHITE = 0, 128, 200, 255

# 字体：本机用微软雅黑，Linux/CI 用开源 Noto Sans CJK。
# 优先级：环境变量 > 候选路径 > 默认值。找不到时 f() 会退回 load_default（不显示中文）。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
LINUX_REG = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf',
    os.path.join(_ROOT, 'fonts', 'NotoSansSC-Regular.otf'),
    os.path.join(_ROOT, 'fonts', 'NotoSansCJKsc-Regular.otf'),
]
LINUX_BOLD = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf',
    os.path.join(_ROOT, 'fonts', 'NotoSansSC-Bold.otf'),
    os.path.join(_ROOT, 'fonts', 'NotoSansCJKsc-Bold.otf'),
]
WIN_REG = r"C:/Windows/Fonts/msyh.ttc"
WIN_BOLD = r"C:/Windows/Fonts/msyhbd.ttc"


def _pick_font(env_key, candidates, fallback):
    p = os.environ.get(env_key)
    if p and os.path.exists(p):
        return p
    for c in candidates:
        if os.path.exists(c):
            return c
    return fallback


def _font_candidates():
    # 两套都留着：Windows 本机可能只有雅黑，CI/容器里只有 Noto CJK。
    # 兜底必须是候选里的第一个，不能在 Linux 上退回一个 Windows 绝对路径。
    return LINUX_REG + [WIN_REG], LINUX_BOLD + [WIN_BOLD]


_REG_CANDS, _BOLD_CANDS = _font_candidates()
FONT_REG = _pick_font('SHAWN_FONT_REG', _REG_CANDS, _REG_CANDS[0])
FONT_BOLD = _pick_font('SHAWN_FONT_BOLD', _BOLD_CANDS, _BOLD_CANDS[0])

F_DATE = 96
F_MONTH = 46
F_TIME = 72
F_TITLE = 40
F_BIG = 56
F_BODY = 34
F_SMALL = 27
F_FOOT = 24

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, '..', 'data')

# ---------- 字体缓存 ----------
# 注意：字体加载失败绝不能静默回退 —— load_default() 渲染不出中文，
# 整屏会变成空白/方块，而在 CI 上极难察觉。这里记录状态并允许 --check-fonts 直接报错。
_fc = {}
_font_errors = []


def f(size, bold=False):
    k = (size, bold)
    if k in _fc:
        return _fc[k]
    p = FONT_BOLD if bold else FONT_REG
    try:
        _fc[k] = ImageFont.truetype(p, size)
    except Exception as e:
        msg = '字体加载失败 %s: %s -> 退回 load_default（中文会渲染不出来）' % (p, e)
        if msg not in _font_errors:
            _font_errors.append(msg)
        print('[render] ERROR ' + msg, file=sys.stderr, flush=True)
        _fc[k] = ImageFont.load_default()
    return _fc[k]


def check_fonts():
    """真正加载一次并测量中日韩字符，确认能渲染中文。返回 (ok, 详情列表)。"""
    info = []
    ok = True
    for tag, path in (('regular', FONT_REG), ('bold', FONT_BOLD)):
        if not os.path.exists(path):
            info.append('%s: 文件不存在 %s' % (tag, path))
            ok = False
            continue
        try:
            ft = ImageFont.truetype(path, 34)
        except Exception as e:
            info.append('%s: 加载失败 %s (%s)' % (tag, path, e))
            ok = False
            continue
        # 用中文实测：宽度异常小说明字形缺失（豆腐/空白）
        img = Image.new('L', (1200, 80), 255)
        d = ImageDraw.Draw(img)
        # fill 必须显式给 0：默认是白色，画在白底上会量到 0 墨迹
        d.text((0, 10), '中文测试道奇教士', font=ft, fill=0)
        bb = d.textbbox((0, 10), '中文测试道奇教士', font=ft)
        wpx = bb[2] - bb[0]
        # 直方图是 C 实现；以前逐像素 1200*80 次 Python 循环只为数墨迹。
        ink = sum(img.histogram()[:128])
        good = wpx >= 200 and ink > 200
        info.append('%s: %s  中文8字宽=%dpx 墨迹=%d  %s'
                    % (tag, os.path.basename(path), wpx, ink, 'OK' if good else '字形缺失!'))
        if not good:
            ok = False
    return ok, info

# ---------- 工具 ----------
def tw(draw, s, font):
    b = draw.textbbox((0, 0), s, font=font)
    return b[2] - b[0]

def clip(draw, s, font, max_w):
    """按像素宽度截断；二分找最长前缀，别每删一个字就重排一次文本。

    以前是 while s: s = s[:-1]，每个字符都要跑一次 PIL 的 textbbox（含字体
    shaping）。长标题 O(n²) 次，整屏渲染里这是最贵的一段纯 Python 循环。
    """
    if tw(draw, s, font) <= max_w:
        return s
    ell = '…'
    if tw(draw, ell, font) > max_w:
        return ''
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tw(draw, s[:mid] + ell, font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo] + ell

# 自然断句：在标点/空格后切分（零宽 lookbehind，标点保留在前一段末尾）
_SENT_SPLIT = re.compile(r'(?<=[，,。；;！？!?、：:\s])')

def clip_sentence(draw, s, font, max_w):
    """一句话新闻截断：优先在自然标点处收尾，保证整句可读且不超页宽。

    1) 整句能放下 -> 原样返回
    2) 否则按标点分段累加，取能放下的最长前缀（结尾是标点，不再加省略号）
    3) 首段就超宽 / 断出来太短没信息量 -> 退化为硬截断加省略号
    """
    s = ' '.join((s or '').split())
    if not s:
        return s
    if tw(draw, s, font) <= max_w:
        return s
    parts = [p for p in _SENT_SPLIT.split(s) if p]
    out = ''
    idx = 0
    for i, p in enumerate(parts):
        cand = out + p
        if tw(draw, cand, font) <= max_w:
            out = cand
            idx = i + 1
        else:
            break
    # 断句结果要有足够信息量，否则宁可硬截断
    if not out or len(out.strip()) < 6:
        return clip(draw, s, font, max_w)
    # 截在逗号/顿号上、后面还有内容时，用剩余宽度把下一截填满（避免"…放榜，"这种半句）
    if idx < len(parts) and out.rstrip()[-1] not in '。！？!?':
        budget = max_w - tw(draw, out, font)
        # 至少放得下 3 个字 + 省略号，否则补进去只会得到 "To…" 这种碎片
        if budget >= 140:
            frag = clip(draw, ''.join(parts[idx:]), font, budget)
            if frag:
                out = out + frag
    return out.rstrip()

def hline(draw, y, color=GRAY, width=1):
    draw.line([(PAD, y), (SCREEN_W - PAD, y)], fill=color, width=width)

def thickline(draw, y, color=BLACK, width=4):
    draw.line([(PAD, y), (SCREEN_W - PAD, y)], fill=color, width=width)

def fnum(v):
    if v is None: return '?'
    if isinstance(v, float):
        return '%.0f' % v if abs(v) >= 1000 else '%.1f' % v
    return str(v)

def fmt_pct(v):
    if v is None: return '?'
    return '%.1f' % abs(v)

# ---------- 数据 ----------
def fetch_dashboard(url='http://127.0.0.1:8787/api/dashboard'):
    """本机服务偶发 ECONNREFUSED（刚重启、正在重建缓存）不该让整次出图失败。

    出图失败 = Kindle 拿不到新图 = 退回旧缓存，用户要等下一个半小时。
    这里只重试一次、间隔 1 秒；真挂了仍然快速失败。
    """
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kindle-dash/1.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last = e
            if attempt == 0:
                print('[render] dashboard fetch failed, retrying once: %s' % e, file=sys.stderr, flush=True)
                time.sleep(1)
    raise last

def load_quotes():
    p = os.path.join(DATA_DIR, 'quotes.en.txt' if LANG == 'en' else 'quotes.txt')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as source:
            return [x.strip() for x in source.read().splitlines() if x.strip()]
    return []

# ---------- 模块 ----------
def draw_header(draw, d, y):
    now = display_now()
    if LANG == 'ru':
        months = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря']
        weekdays = ['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье']
        date_label = f"{now.day} {months[now.month - 1]} {now.year}"
        weekday_label = weekdays[now.weekday()]
    else:
        date_label = now.strftime('%d.%m.%Y')
        weekday_label = now.strftime('%A')
    fd = f(F_DATE, bold=True)
    fw = f(F_BODY + 3, bold=True)
    date_x = (SCREEN_W - tw(draw, date_label, fd)) // 2
    weekday_x = (SCREEN_W - tw(draw, weekday_label, fw)) // 2
    draw.text((date_x, y), date_label, fill=BLACK, font=fd)
    draw.text((weekday_x, y + F_DATE + F_BODY + 20), weekday_label, fill=BLACK, font=fw)
    return y + round(190 * (LAYOUT["fontScale"] if LAYOUT else 1))

def stamp_label(src):
    """把模块数据里的 fetchedAt 变成右上角的时间标注。

    stale（本次拉取失败、用的是上次成功数据）时标成「缓存 HH:MM」。
    拿不到时间就返回 None，标题栏保持原样。
    """
    # User requested a time-free dashboard: never print fetch timestamps.
    return None
    if not isinstance(src, dict):
        return None
    ts = src.get('fetchedAt')
    if not ts:
        return None
    try:
        t = datetime.fromtimestamp(float(ts) / 1000.0, ZoneInfo(LAYOUT['timezone']) if LAYOUT and LAYOUT.get('timezone') else None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    hhmm = t.strftime('%H:%M')
    return (('Cached %s' if LANG == 'en' else '缓存 %s') % hhmm) if src.get('stale') else hhmm


def draw_title(draw, y, text, src=None):
    """模块标题。传 src（该模块的数据）时，右上角显示数据的获取时间。"""
    draw.text((PAD, y), text, fill=BLACK, font=f(F_TITLE, bold=True))
    label = stamp_label(src)
    if label:
        fs = f(F_SMALL)
        # 右对齐到内容区右边界；小字按标题基线附近排，视觉上跟标题齐平
        draw.text((SCREEN_W - PAD - tw(draw, label, fs), y + (F_TITLE - F_SMALL)),
                  label, fill=GRAY, font=fs)
    return y + F_TITLE + 8

def draw_month_calendar(draw, d, y):
    """Компактная сетка текущего месяца, неделя начинается с понедельника."""
    y = draw_title(draw, y, 'Календарь')
    now = display_now()
    months = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь']
    weekdays = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
    title = '%s %d' % (months[now.month - 1], now.year)
    draw.text((PAD, y), title, fill=BLACK, font=f(F_BODY, bold=True))
    y += F_BODY + 14
    colw = CONTENT_W // 7
    for i, label in enumerate(weekdays):
        x = PAD + i * colw
        draw.text((x + (colw - tw(draw, label, f(F_SMALL))) // 2, y), label, fill=GRAY, font=f(F_SMALL, bold=True))
    y += F_SMALL + 12
    import calendar as _calendar
    weeks = _calendar.monthcalendar(now.year, now.month)
    cell_h = 48
    for row_index, week in enumerate(weeks):
        for col, day in enumerate(week):
            x = PAD + col * colw
            top = y + row_index * cell_h
            left, right = x + 3, x + colw - 3
            bottom = top + cell_h - 4
            if day == now.day:
                draw.rectangle([left, top, right, bottom], fill=BLACK, outline=BLACK, width=2)
            else:
                draw.rectangle([left, top, right, bottom], outline=GRAY, width=2)
            if day:
                label = str(day)
                font = f(F_BODY, bold=(day == now.day))
                color = WHITE if day == now.day else BLACK
                draw.text((x + (colw - tw(draw, label, font)) // 2, top + 3), label, fill=color, font=font)
    y += len(weeks) * cell_h + 16

    # Природная строка под календарём: восход, закат и фаза Луны.
    weather = d.get('weather') or {}
    sunrise = weather.get('sunrise') or '—'
    sunset = weather.get('sunset') or '—'
    phase_names = {
        '新月': 'Новолуние', '蛾眉月': 'Молодая Луна',
        '上弦月': 'Первая четверть', '盈凸月': 'Растущая Луна',
        '满月': 'Полнолуние', '亏凸月': 'Убывающая Луна',
        '下弦月': 'Последняя четверть', '残月': 'Старая Луна',
    }
    (phase_zh, _), moon_age = slowinfo.moon_phase(now.date(), (LAYOUT or {}).get('timezone') or 'Europe/Riga')
    phase_label = phase_names.get(phase_zh, 'Фаза Луны')

    # Тонкий разделитель отделяет календарную сетку от природной информации.
    hline(draw, y, GRAY, 1)
    y += 18
    icon_y = y + 2
    icon_color = BLACK

    def sun_icon(cx, cy):
        r = 10
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=icon_color, width=3)
        for angle in range(0, 360, 45):
            a = math.radians(angle)
            x1, yy1 = cx + math.cos(a)*15, cy + math.sin(a)*15
            x2, yy2 = cx + math.cos(a)*21, cy + math.sin(a)*21
            draw.line([(int(x1), int(yy1)), (int(x2), int(yy2))], fill=icon_color, width=3)
        draw.line([(cx-22, cy+17), (cx+22, cy+17)], fill=icon_color, width=3)

    def moon_icon(cx, cy, age):
        # Рисуем лунный диск и светлую часть без emoji-шрифта — надёжно для Kindle.
        period = 29.530588853
        illumination = (1 - math.cos(2 * math.pi * age / period)) / 2
        waxing = age < period / 2
        r = 18
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=BLACK)
        if illumination < 0.04:
            draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=BLACK, width=2)
            return
        if illumination > 0.96:
            draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=BLACK)
            return
        if abs(illumination - 0.5) < 0.09:
            if waxing:
                draw.rectangle([cx, cy-r, cx+r, cy+r], fill=WHITE)
            else:
                draw.rectangle([cx-r, cy-r, cx, cy+r], fill=WHITE)
            draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=BLACK, width=2)
            return
        offset = int((1 - 2 * illumination) * r) if waxing else int((2 * illumination - 1) * r)
        draw.ellipse([cx-r+offset, cy-r, cx+r+offset, cy+r], fill=WHITE)
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=BLACK, width=2)

    # Три равные зоны: восход | закат | лунная фаза.
    zone_w = CONTENT_W // 3
    sun_icon(PAD + 24, icon_y + 20)
    draw.text((PAD + 56, y + 2), 'Восход', fill=GRAY, font=f(F_SMALL))
    draw.text((PAD + 56, y + 31), sunrise, fill=BLACK, font=f(F_BODY, bold=True))

    x2 = PAD + zone_w
    sun_icon(x2 + 24, icon_y + 20)
    draw.text((x2 + 56, y + 2), 'Закат', fill=GRAY, font=f(F_SMALL))
    draw.text((x2 + 56, y + 31), sunset, fill=BLACK, font=f(F_BODY, bold=True))

    x3 = PAD + 2 * zone_w
    moon_icon(x3 + 22, icon_y + 20, moon_age)
    phase_font = f(F_SMALL, bold=True)
    draw.text((x3 + 52, y + 2), 'Луна', fill=GRAY, font=f(F_SMALL))
    draw.text((x3 + 52, y + 31), clip(draw, phase_label, phase_font, SCREEN_W - PAD - (x3 + 52)), fill=BLACK, font=phase_font)

    return y + F_BODY + 48

def draw_news(draw, d, y):
    """今日新闻 · AI：中文一句话，按自然标点断句，绝不超页宽"""
    y = draw_title(draw, y, tr('今日新闻 · AI'), d.get('news'))
    items = (d.get('news') or {}).get('items', [])
    ff = f(F_BODY)
    fs = f(F_SMALL)
    if not items:
        draw.text((PAD, y), tr('新闻源暂不可用'), fill=GRAY, font=fs)
        return y + F_SMALL
    n = min(len(items), 3)
    for i in range(n):
        line = '· ' + (items[i].get('title') or '')
        draw.text((PAD, y + i * (F_BODY + 8)), (clip(draw, line, ff, CONTENT_W) if LANG == 'en' else clip_sentence(draw, line, ff, CONTENT_W)),
                  fill=BLACK, font=ff)
    return y + n * (F_BODY + 8)

def draw_ai(draw, d, y):
    """AI 用量：上下文水位 / 真实消耗 / 活动量。

    注意：WorkBuddy 的 used/size 是「当前会话上下文水位 / 模型窗口」，
    会在自动压缩时暴跌，绝不是账户余额 —— 所以这里只叫"上下文"，
    真正的"花掉多少"另起一行用 credit（单调累加，不受压缩影响）。
    Claude/Codex 只有活动量（cap 是 config 里的手写参考值），不画成剩余额度。
    """
    q = d.get('quotas', {})
    ff = f(F_BODY)
    fs = f(F_SMALL)
    bar_h, bar_w, gap = 10, 300, 6

    rows = []  # (行名, 右侧数值, 进度条百分比 or None)
    wb = q.get('workbuddy') or {}
    if wb.get('ok'):
        ctx = wb.get('context') or {}
        c_used = ctx.get('used') if ctx.get('used') is not None else wb.get('used')
        c_size = ctx.get('size') if ctx.get('size') is not None else wb.get('cap')
        c_pct = ctx.get('percent') if ctx.get('percent') is not None else wb.get('percent')
        if c_used is not None and c_size is not None:
            if ctx:
                val = '%s / %s' % (fnum(c_used), fnum(c_size))       # 已用上下文 / 窗口
                label, pct = tr('上下文'), c_pct
            else:
                # 云端拿到的旧 quotas.json 没有 context 字段，那它只有"剩余"这一个口径。
                # 标签和进度条必须跟着换，否则会画出"上下文 254392/300000"却按已用率填充
                # 进度条这种自相矛盾的行。
                rem = wb.get('remaining')
                val = '%s / %s' % (fnum(rem), fnum(c_size)) if rem is not None else '%s / %s' % (fnum(c_used), fnum(c_size))
                label = tr('剩余')
                pct = (100 - c_pct) if isinstance(c_pct, (int, float)) else None
            if wb.get('stale'):
                val += ' ' + tr('·旧')
            rows.append((label, val, pct))
        cr = wb.get('credit') or {}
        if cr.get('used') is not None:
            rows.append((tr('已消耗'), '%s credits · %s %s' % (fnum(cr.get('used')), fnum(cr.get('count')), tr('次')), None))
    cc = q.get('claudecode') or {}
    if cc.get('ok'):
        rows.append((tr('本周活动'), '%s %s · %s %s' % (fnum(cc.get('used7d')), tr('条'), fnum(cc.get('sessions7d')), tr('会话')), None))
    cx = q.get('codex') or {}
    if cx.get('ok'):
        rows.append((tr('Codex 文件'), '%s / %s' % (fnum(cx.get('used7d')), fnum(cx.get('cap'))), None))
    if not rows:
        rows.append((tr('AI'), tr('不可用'), None))

    # 标题点名 WorkBuddy：这三行都是它的数据（活动量也读自 WorkBuddy 的 transcript）。
    # 只有确实装了别的工具（Codex）时才退回泛指的"AI 用量"。
    # cloud 模式下若本机久未上报，标题直接点明"电脑离线"，不拿旧值假装新鲜
    offline = not d.get('pcOnline', True)
    if cx.get('ok'):
        title = tr('AI 用量 · 电脑离线') if offline else tr('AI 用量')
    else:
        title = tr('WorkBuddy 用量 · 电脑离线') if offline else tr('WorkBuddy 用量')
    y = draw_title(draw, y, title, d.get('quotas'))

    for i, (name, val, pct) in enumerate(rows):
        ry = y + i * (F_BODY + bar_h + gap)
        draw.text((PAD, ry), name, fill=BLACK, font=ff)
        right = SCREEN_W - PAD if pct is None else SCREEN_W - PAD - bar_w - 20
        draw.text((right - tw(draw, val, fs), ry + 4), val, fill=GRAY, font=fs)
        if pct is None:
            continue
        bx = SCREEN_W - PAD - bar_w
        by = ry + 6
        r = bar_h // 2
        draw.rounded_rectangle([bx, by, bx + bar_w, by + bar_h], radius=r, fill=LIGHT_GRAY, outline=BLACK, width=1)
        # 旧云端快照会算出 100 - percent，percent 本身又可能是脏值 → 负数或
        # >100 会让填充条画出边框；而 max(bar_h, ...) 让 0% 也画一截实心黑。
        ratio = min(100.0, max(0.0, float(pct) if isinstance(pct, (int, float)) else 0.0))
        fw = min(bar_w, int(bar_w * ratio / 100.0))
        if fw > 0:
            draw.rounded_rectangle([bx, by, bx + fw, by + bar_h], radius=r, fill=BLACK)
    return y + len(rows) * (F_BODY + bar_h + gap)

def draw_weather_icon(draw, x, y, code, size=34):
    """Компактные монохромные пиктограммы: Kindle-friendly, без emoji."""
    code = int(code) if isinstance(code, (int, float)) else -1
    sun = code in (0, 1, 2)
    cloud = code in (2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)
    snow = code in (71, 73, 75, 77, 85, 86)
    rain = code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99)
    thunder = code in (95, 96, 99)
    fog = code in (45, 48)
    cx, cy = x + size // 2, y + size // 2
    if sun:
        r = 7
        draw.ellipse((cx-r, cy-r-3, cx+r, cy+r-3), outline=BLACK, width=2)
        for dx, dy in ((0,-15),(0,15),(-15,0),(15,0),(-11,-11),(11,-11),(-11,11),(11,11)):
            draw.line((cx+dx//2, cy-3+dy//2, cx+dx, cy-3+dy), fill=BLACK, width=2)
    if cloud:
        # Three overlapping circles plus a baseline form a clear cloud silhouette.
        base_y = y + 24
        draw.arc((x+5, y+11, x+23, y+29), 180, 350, fill=BLACK, width=2)
        draw.arc((x+13, y+3, x+31, y+27), 190, 350, fill=BLACK, width=2)
        draw.arc((x+22, y+12, x+39, y+29), 190, 350, fill=BLACK, width=2)
        draw.line((x+10, base_y, x+34, base_y), fill=BLACK, width=2)
    if fog:
        for yy in (y+13, y+21, y+29):
            draw.line((x+4, yy, x+36, yy), fill=BLACK, width=2)
    elif thunder:
        draw.line((cx+1, y+23, cx-5, y+33, cx+1, y+33, cx-3, y+40), fill=BLACK, width=3)
    elif rain:
        for dx in (13, 23, 33):
            draw.line((x+dx, y+29, x+dx-4, y+37), fill=BLACK, width=2)
    elif snow:
        for dx in (13, 25, 35):
            draw.line((x+dx-3, y+32, x+dx+3, y+38), fill=BLACK, width=2)
            draw.line((x+dx+3, y+32, x+dx-3, y+38), fill=BLACK, width=2)
    if code not in range(0, 100):
        draw.ellipse((x+12, y+12, x+28, y+28), outline=BLACK, width=2)
        draw.text((x+17, y+10), "?", fill=BLACK, font=f(F_SMALL))


def draw_weather(draw, d, y):
    w = d.get('weather', {})
    y = draw_title(draw, y, tr('天气'), w)
    if w.get('ok'):
        t1 = '%s°%s' % (fnum(w.get('temp')), LAYOUT['temperatureUnit'] if LAYOUT else 'C')
        ft = f(F_BIG, bold=True)
        draw.text((PAD, y), t1, fill=BLACK, font=ft)
        tw1 = tw(draw, t1, ft)
        det = ('%s  H%s L%s  RH%s%%' if LANG == 'en' else ('%s  макс. %s° мин. %s°  влажн. %s%%' if LANG == 'ru' else '%s  高%s 低%s  湿%s%%')) % (w.get('text', ''), fnum(w.get('high')), fnum(w.get('low')), w.get('humidity', '?'))
        detail_font = f(F_SMALL + 3, bold=True)
        draw.text((PAD + tw1 + 24, y + 14), clip(draw, det, detail_font, CONTENT_W - tw1 - 24), fill=BLACK, font=detail_font)
        bottom = draw.textbbox((PAD, y), t1, font=ft)[3] + 8
        days = (w.get('days') or [])[1:4]
        if days:
            ff = f(round(F_SMALL * 1.4), bold=True)  # уменьшено на 30%
            row_y = bottom + 16
            for i, day in enumerate(days):
                raw = str(day.get('date') or '')
                try:
                    parts = [int(x) for x in raw.split('-') if x.isdigit()]
                    month, dom = parts[-2], parts[-1]
                    weekday_index = _date_weekday(today_year(), month, dom)
                    weekday = 'ПнВтСрЧтПтСбВс'[weekday_index*2:weekday_index*2+2] if LANG == 'ru' else WEEKDAY_EN[weekday_index]
                    date_label = '%02d.%02d %s' % (dom, month, weekday) if LANG == 'ru' else '%s %d' % (weekday, dom)
                except (ValueError, IndexError):
                    date_label = raw or '—'
                condition = day.get('text') or '—'
                temps = '%s° / %s°' % (fnum(day.get('high')), fnum(day.get('low')))
                ry = row_y + i * 62  # компактнее после уменьшения прогноза
                draw.text((PAD, ry), date_label, fill=BLACK, font=ff)
                icon_x, icon_y = PAD + 205, ry - 12
                icon_base = Image.new('L', (48, 48), WHITE)
                draw_weather_icon(ImageDraw.Draw(icon_base), 0, 0, day.get('code'), size=44)
                icon_large = icon_base.resize((62, 62), Image.Resampling.NEAREST)
                draw._image.paste(icon_large, (icon_x, icon_y))
                draw.text((PAD + 315, ry), clip(draw, condition, ff, 330), fill=GRAY, font=ff)
                draw.text((SCREEN_W - PAD - tw(draw, temps, ff), ry), temps, fill=BLACK, font=ff)
            bottom = row_y + len(days) * (F_SMALL * 2 + 18)
        return bottom
    else:
        draw.text((PAD, y), tr('天气不可用'), fill=GRAY, font=f(F_SMALL))
        return y + F_SMALL + 8

def draw_market(draw, d, y):
    st = (d.get('stocks') or {}).get('items', [])
    y = draw_title(draw, y, tr('市场'), d.get('stocks'))
    ff = f(F_BODY)
    colw = CONTENT_W // 2
    rows = math.ceil(len(st) / 2)
    for i in range(0, len(st), 2):
        ry = y + (i // 2) * (F_BODY + 6)
        for j, s in enumerate(st[i:i+2]):
            x = PAD + j * colw
            if s.get('ok'):
                sign = '+' if (s.get('changePct') or 0) >= 0 else '-'
                cell = '%s %s %s%s%%' % (s.get('label') or s.get('sym'), fnum(s.get('price')), sign, fmt_pct(s.get('changePct')))
            else:
                cell = '%s --' % (s.get('label') or s.get('sym'))
            draw.text((x, ry), clip(draw, cell, ff, colw - 8), fill=BLACK, font=ff)
    return y + rows * (F_BODY + 6)

def draw_fx(draw, d, y):
    """Курсы валют относительно базовой валюты EUR."""
    fx = d.get('fx') or {}
    y = draw_title(draw, y, 'Курсы валют', fx)
    if not fx.get('ok'):
        draw.text((PAD, y), 'Курсы валют временно недоступны', fill=GRAY, font=f(F_SMALL))
        return y + F_SMALL
    base = fx.get('base') or 'EUR'
    base_symbol = '€' if base == 'EUR' else ('$' if base == 'USD' else '')
    rows = [('USD', '$', fx.get('usd')), ('UAH', '₴', fx.get('uah'))]
    ff = f(F_BODY)
    for i, (code, symbol, value) in enumerate(rows):
        rate = ('%.4f' % value).rstrip('0').rstrip('.') if isinstance(value, (int, float)) else '—'
        line = '1 %s = %s %s' % (base_symbol or base, rate, symbol)
        draw.text((PAD, y + i * (F_BODY + 6)), line, fill=BLACK, font=ff)
    cross = fx.get('usdUah')
    rate = ('%.4f' % cross).rstrip('0').rstrip('.') if isinstance(cross, (int, float)) else '—'
    draw.text((PAD, y + len(rows) * (F_BODY + 6)), '1 $ = ' + rate + ' ₴', fill=BLACK, font=ff)
    return y + (len(rows) + 1) * (F_BODY + 6)


def draw_clocks(draw, d, y):
    """世界时钟（两列）"""
    y = draw_title(draw, y, tr('世界时钟'))
    cl = (d.get('clocks') or {}).get('items', [])
    ff = f(F_BODY)
    fs = f(F_SMALL)
    colw = CONTENT_W // 2
    if not cl:
        draw.text((PAD, y), tr('时钟不可用'), fill=GRAY, font=fs)
        return y + F_SMALL
    for i in range(0, len(cl), 2):
        ry = y + (i // 2) * (F_BODY + 8)
        for j, c in enumerate(cl[i:i+2]):
            x = PAD + j * colw
            city = c.get('city', '')
            if LANG == 'en':
                city = clip(draw, city, ff, colw - 150)
            tme = c.get('time', '')[:5]
            draw.text((x, ry), city, fill=BLACK, font=ff)
            cw = tw(draw, city, ff)
            draw.text((x + cw + 12, ry + 2), tme, fill=BLACK, font=ff)
            dw2 = tw(draw, tme, ff)
            date_s = '' if LANG == 'en' else (c.get('date') or '').replace('周', ' 周')
            draw.text((x + cw + dw2 + 24, ry + 6), date_s, fill=GRAY, font=fs)
    return y + math.ceil(len(cl) / 2) * (F_BODY + 8)

def draw_mlb(draw, d, y):
    """MLB · 道奇 / 教士：上一场比分 + 下一场时间（均为北京时间）"""
    y = draw_title(draw, y, tr('MLB · 道奇 / 教士'), d.get('mlb'))
    items = (d.get('mlb') or {}).get('items', [])
    ff = f(F_BODY)
    fs = f(F_SMALL)
    if not items:
        draw.text((PAD, y), tr('赛程暂不可用'), fill=GRAY, font=fs)
        return y + F_SMALL
    name_w = 88 if LANG == 'en' else 80
    col_a = PAD + name_w
    col_b = PAD + name_w + 410

    def mark_of(g):
        # "@勇士" 紧凑；"vs 海盗" 加空格更好读
        return 'vs ' if g.get('home') else '@'

    for i, it in enumerate(items[:2]):
        ry = y + i * (F_BODY + 8)
        draw.text((PAD, ry), it.get('cn', ''), fill=BLACK, font=f(F_BODY, bold=True))
        last = it.get('last') or {}
        nxt = it.get('next') or {}
        if last:
            s = '%s %s%s %s-%s' % (last.get('date', ''), mark_of(last), last.get('opp', ''),
                                   last.get('us', 0), last.get('them', 0))
            draw.text((col_a, ry), s, fill=GRAY, font=ff)
            res = tr('胜') if last.get('win') else tr('负')
            # 胜=黑，负=灰：e-ink 上靠明度区分，不用颜色
            draw.text((col_a + tw(draw, s, ff) + 12, ry), res,
                      fill=BLACK if last.get('win') else GRAY, font=f(F_BODY, bold=True))
        else:
            draw.text((col_a, ry), tr('无近期战报'), fill=GRAY, font=fs)
        if nxt:
            s2 = '→ %s %s %s%s' % (nxt.get('date', ''), nxt.get('time', ''),
                                   mark_of(nxt), nxt.get('opp', ''))
            draw.text((col_b, ry), clip(draw, s2, ff, SCREEN_W - PAD - col_b), fill=BLACK, font=ff)
    return y + min(len(items), 2) * (F_BODY + 8)

def draw_quote(draw, d, y, quotes):
    y = draw_title(draw, y, tr('今日一句'))
    if not quotes:
        draw.text((PAD, y), tr('（编辑 data/quotes.txt）'), fill=GRAY, font=f(F_SMALL))
        return y + F_SMALL
    ff = f(F_BODY)
    q = quotes[display_now().timetuple().tm_yday % len(quotes)]
    if ' —— ' in q:
        text, src = q.split(' —— ', 1)
    elif '—' in q:
        text, src = q.split('—', 1)
    else:
        text, src = q, ''
    line = clip(draw, text, ff, CONTENT_W - 80)
    if src:
        line = clip(draw, line + '  — ' + src, ff, CONTENT_W)
    draw.text((PAD, y), line, fill=BLACK, font=ff)
    return y + F_BODY + 6

MONTH_EN = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
WEEKDAY_EN = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']


def wrap_lines(draw, text, font, max_w):
    """按像素宽度折行：中文逐字，英文按单词。用于页 3 的大字句子。"""
    text = ' '.join((text or '').split())
    if not text:
        return []
    if tw(draw, text, font) <= max_w:
        return [text]
    units = text.split(' ') if LANG == 'en' else list(text)
    sep = ' ' if LANG == 'en' else ''
    lines, current = [], ''
    for unit in units:
        candidate = (current + sep + unit).lstrip() if current else unit
        if tw(draw, candidate, font) <= max_w or not current:
            current = candidate
        else:
            lines.append(current)
            current = unit
    if current:
        lines.append(current)
    return lines


def _slow_today():
    now = display_now()
    tz = (LAYOUT or {}).get('timezone') or 'Asia/Shanghai'
    return now, now.date(), tz


def draw_slow_calendar(draw, d, y):
    """页 2 · 日历：只陈述「今天在一年里的位置」，没有任何待办或提醒。"""
    y = draw_title(draw, y, tr('慢信息'))
    now, today, tz = _slow_today()
    current, upcoming = slowinfo.term_at(today, tz)
    (moon_zh, moon_en), age = slowinfo.moon_phase(today, tz)
    weekend = slowinfo.days_to_weekend(today)
    holiday = slowinfo.next_fixed_day(today)
    progress = slowinfo.year_progress(today)
    fbig, ff, fs = f(F_BIG, bold=True), f(F_BODY), f(F_SMALL)
    row = F_BODY + 44

    # 第一行：日期 + 年进度
    if LANG == 'en':
        date_s = '%s %d, %s' % (MONTH_EN[today.month - 1], today.day, WEEKDAY_EN[today.weekday()])
        sub = '%d%% of the year' % progress
    else:
        date_s = '%d月%d日 周%s' % (today.month, today.day, '一二三四五六日'[today.weekday()])
        sub = '今年已过 %d%%' % progress
    draw.text((PAD, y), date_s, fill=BLACK, font=fbig)
    draw.text((SCREEN_W - PAD - tw(draw, sub, fs), y + 22), sub, fill=GRAY, font=fs)
    y += row + 12

    # 第二行：当前节气 + 下一个节气
    if upcoming:
        if LANG == 'en':
            line = '%s · Next: %s in %dd' % (current[1] if current else '—', upcoming[1], upcoming[3])
        else:
            line = '%s · 下一个节气 %s（%d 天后）' % (current[0] if current else '—', upcoming[0], upcoming[3])
    else:
        # term_at 对任何年份都能算出下一个节气，此分支正常不可达；
        # 万一走到，也别把节气行写成「天气暂不可用」（早期版本复制错标签）。
        line = tr('节气信息暂不可用')
    draw.text((PAD, y), clip(draw, line, ff, CONTENT_W), fill=BLACK, font=ff)
    y += row

    # 第三行：月相 + 周末
    if LANG == 'en':
        weekend_s = 'It is the weekend' if weekend == 0 else 'Saturday in %dd' % weekend
        line = '%s · %.0f days old · %s' % (moon_en, age, weekend_s)
    else:
        weekend_s = '正在周末' if weekend == 0 else '距周六 %d 天' % weekend
        line = '%s · 月龄 %.0f 天 · %s' % (moon_zh, age, weekend_s)
    draw.text((PAD, y), clip(draw, line, ff, CONTENT_W), fill=GRAY, font=ff)
    y += row

    # 第四行：下一个公历固定日子
    if holiday:
        zh, en, _, days = holiday
        if LANG == 'en':
            line = '%s in %dd' % (en, days) if days else '%s is today' % en
        else:
            line = '距%s %d 天' % (zh, days) if days else '今天是%s' % zh
        draw.text((PAD, y), line, fill=GRAY, font=fs)
    return y + F_BODY + 6


def _daylight(sunrise, sunset):
    try:
        a = [int(x) for x in sunrise.split(':')]
        b = [int(x) for x in sunset.split(':')]
        minutes = (b[0] * 60 + b[1]) - (a[0] * 60 + a[1])
        if minutes <= 0 or minutes > 1440:
            return None
        return '%dh %02dm' % (minutes // 60, minutes % 60)
    except (AttributeError, ValueError, IndexError):
        return None


def draw_sun(draw, d, y):
    """页 2 · 日光：日出日落与昼长。"""
    y = draw_title(draw, y, tr('日光'))
    w = d.get('weather') or {}
    sunrise, sunset = w.get('sunrise'), w.get('sunset')
    if not (sunrise and sunset):
        draw.text((PAD, y), tr('日出日落暂不可用'), fill=GRAY, font=f(F_SMALL))
        return y + F_BODY + 12
    line = '%s → %s' % (sunrise, sunset)
    fbig = f(F_BIG, bold=True)
    draw.text((PAD, y), line, fill=BLACK, font=fbig)
    span = _daylight(sunrise, sunset)
    if span:
        if LANG == 'en':
            label = 'Daylight %s' % span
        else:
            hours, minutes = span.split(' ')
            label = '昼长 %s 小时 %s 分' % (hours.rstrip('h'), minutes.rstrip('m'))
        fs = f(F_SMALL)
        draw.text((SCREEN_W - PAD - tw(draw, label, fs), y + 18), label, fill=GRAY, font=fs)
    return y + F_BIG + 14


def draw_forecast(draw, d, y):
    """页 2 · 往后几天：三行天气，纯陈述。"""
    y = draw_title(draw, y, tr('往后几天'), d.get('weather'))
    days = ((d.get('weather') or {}).get('days') or [])[1:4]
    ff, fs = f(F_BODY), f(F_SMALL)
    if not days:
        draw.text((PAD, y), tr('未来天气暂不可用'), fill=GRAY, font=fs)
        return y + F_BODY + 12
    for i, day in enumerate(days):
        raw = str(day.get('date') or '')
        try:
            # provider 给 'MM-DD'，云端快照/历史样本可能是 'YYYY-MM-DD'：
            # 取最后两段两种格式都能读对，别把年份当成月份画成 "2026月11日"。
            parts = [int(x) for x in raw.split('-') if x.isdigit()]
            month, dom = parts[-2], parts[-1]
            weekday = WEEKDAY_EN[_date_weekday(today_year(), month, dom)] if LANG == 'en' else '一二三四五六日'[_date_weekday(today_year(), month, dom)]
        except (ValueError, IndexError):
            month, dom, weekday = 0, 0, ''
        if LANG == 'en':
            left = '%s %d %s' % (MONTH_EN[month - 1] if 1 <= month <= 12 else raw, dom, weekday)
        else:
            left = '%d月%d日 周%s' % (month, dom, weekday)
        text = day.get('text') or '—'
        temps = '%s° / %s°' % (fnum(day.get('high')), fnum(day.get('low')))
        ry = y + i * (F_BODY + 22)
        draw.text((PAD, ry), left, fill=BLACK, font=ff)
        draw.text((PAD + 340, ry), text, fill=GRAY, font=ff)
        draw.text((SCREEN_W - PAD - tw(draw, temps, ff), ry), temps, fill=BLACK, font=ff)
    return y + len(days) * (F_BODY + 22)


def _date_weekday(year, month, day):
    from datetime import date as _date
    try:
        return _date(year, month, day).weekday()
    except ValueError:
        return 0


def today_year():
    return display_now().year


def draw_reading(draw, d, y, quotes):
    """页 3 · 闲读：一句大字、大留白、看完就完。"""
    y = draw_title(draw, y, tr('闲读'))
    if not quotes:
        draw.text((PAD, y + 80), tr('（编辑句子库）'), fill=GRAY, font=f(F_SMALL))
        return y + 160
    # 与页 1「今日一句」错开索引，避免滑到第 3 页看到同一句。
    q = quotes[(display_now().timetuple().tm_yday * 7 + 3) % len(quotes)]
    if ' —— ' in q:
        text, source = q.split(' —— ', 1)
    elif LANG == 'en' and ' - ' in q:
        text, source = q.split(' - ', 1)
    else:
        text, source = q, ''
    font = f(F_BIG + 12)
    lines = wrap_lines(draw, text, font, CONTENT_W - 60)[:5]
    top = y + 220
    step = F_BIG + 60
    for i, line in enumerate(lines):
        draw.text((PAD + (CONTENT_W - tw(draw, line, font)) // 2, top + i * step),
                  line, fill=BLACK, font=font)
    bottom = top + len(lines) * step + 30
    if source:
        # 不用破折号：1-bit 抖动后单根 em dash 会变成一条波浪状噪声线。
        src = source.strip()
        fs = f(F_SMALL)
        draw.text((SCREEN_W - PAD - tw(draw, src, fs), bottom), src, fill=GRAY, font=fs)
        bottom += F_SMALL + 10
    # 页脚已带页码与换页提示，这里不再重复画一行提示 + 分隔线，
    # 否则两条横线把提示夹成三明治，反而是整页最吵的地方。
    return bottom + 40


def draw_footer(draw, d, y, offline=False, last_ok=None, page=1, pages=1):
    hline(draw, y, GRAY, 1)
    y += 12
    now = display_now().strftime('%H:%M')
    if pages > 1:
        tail = ('Page %d/%d · %s' % (page, pages, tr('左右滑换页'))) if LANG == 'en' \
            else ('第 %d/%d 页 · %s' % (page, pages, tr('左右滑换页')))
    else:
        tail = 'Swipe from top to exit' if LANG == 'en' else ('Смахните сверху для выхода' if LANG == 'ru' else '顶部下滑返回')
    if LANG == 'en':
        head = ('DayPane · Offline · Last %s' % (last_ok or '?')) if offline else ('DayPane · Updated %s' % now)
    elif LANG == 'ru':
        head = ('DayPane · офлайн · последнее обновление %s' % (last_ok or '?')) if offline else ('DayPane · обновлено %s' % now)
    else:
        head = ('DayPane · 离线 · 最后 %s' % (last_ok or '?')) if offline else ('DayPane · 更新 %s' % now)
    txt = head + ' · ' + tail
    fs = f(F_FOOT)
    draw.text((PAD, y), clip(draw, txt, fs, CONTENT_W), fill=GRAY, font=fs)
    return y + F_FOOT

# ---------- 主流程 ----------
def render(d, out_path=None, language="zh", page=1, pages=1):
    """page 从 1 起；pages>1 时页脚显示页码。

    默认 pages=1 是刻意的：云端 Pages 只有一张图（build_site.py 不带分页参数），
    显示「1/3 · 左右滑换页」却滑不动会误导人。只有本机 :8787 的多页模式才传 3。
    """
    global LANG
    LANG = language
    page = page if page in (1, 2, 3) else 1
    pages = max(1, min(3, int(pages or 1)))
    global LAYOUT, SCREEN_W, SCREEN_H, CONTENT_W
    LAYOUT = load_layout(os.environ.get('SHAWN_CONFIG', 'config.json'))
    # Compose at a readable portrait ratio, then scale to the selected screen.
    SCREEN_W = 1072
    SCREEN_H = round(1072 * LAYOUT['height'] / LAYOUT['width'])
    CONTENT_W = SCREEN_W - 2 * PAD
    for key, base in {'F_DATE':96,'F_MONTH':46,'F_TIME':72,'F_TITLE':40,'F_BIG':56,'F_BODY':34,'F_SMALL':27,'F_FOOT':24}.items():
        globals()[key] = round(base * LAYOUT['fontScale'])
    d = localized_data(d)
    if LAYOUT['temperatureUnit'] == 'F':
        for key in ('temp','high','low'):
            value = (d.get('weather') or {}).get(key)
            if isinstance(value, (int,float)): d['weather'][key] = value*9/5+32
    img = Image.new('L', (SCREEN_W, SCREEN_H), WHITE)
    draw = ImageDraw.Draw(img)
    _DRAWN.clear()
    _record_texts(draw)
    quotes = load_quotes()

    y = PAD
    y = draw_header(draw, d, y)
    y += 10
    thickline(draw, y, BLACK, 4)
    y += 16

    registry = {
        'news': lambda y: draw_news(draw, d, y),
        'ai': lambda y: draw_ai(draw, d, y),
        'weather': lambda y: draw_weather(draw, d, y),
        'market': lambda y: draw_market(draw, d, y),
        'clocks': lambda y: draw_clocks(draw, d, y),
        'fx': lambda y: draw_fx(draw, d, y),
        'calendar': lambda y: draw_month_calendar(draw, d, y),
        'mlb': lambda y: draw_mlb(draw, d, y),
        'quote': lambda y: draw_quote(draw, d, y, quotes),
        'slow_calendar': lambda y: draw_slow_calendar(draw, d, y),
        'sun': lambda y: draw_sun(draw, d, y),
        'forecast': lambda y: draw_forecast(draw, d, y),
    }
    if page == 2:
        y += 40   # 慢信息页先给一点呼吸空间，别把内容顶在日期横线下
    if page == 3:
        # 闲读页刻意留白：不画模块之间的分隔线。
        y = draw_reading(draw, d, y, quotes)
    else:
        mods = [registry['slow_calendar'], registry['sun'], registry['forecast']] if page == 2 \
            else [registry[name] for name in LAYOUT['modules']]
        # 页 2 只有三个模块，间距放宽一点才不像一张挤在顶部的清单。
        gap = 34 if page == 2 else 14
        for fn in mods:
            y = fn(y)
            hline(draw, y + 8, GRAY, 1)
            y += gap
    content_bottom = y
    # 页脚固定贴底：页 1 内容多时自然接在后面，页 2/3 内容少时也不会
    # 把 "DayPane · 更新 …" 挂在半屏中间、下面空掉一大截。
    y = draw_footer(draw, d, max(content_bottom, SCREEN_H - F_FOOT - 40),
                    page=page, pages=pages)

    print('[render] final_y=%d content_bottom=%d screen_h=%d' % (y, content_bottom, SCREEN_H), file=sys.stderr, flush=True)
    if content_bottom > SCREEN_H - F_FOOT - 50:
        raise ValueError('Layout exceeds screen height; reduce modules or font scale')
    # 英文版绝不能出现中文：在缩放 + Floyd-Steinberg 抖动（整屏最贵的一步）
    # 之前就拦住，漏翻译时立刻失败，不白跑一遍图像处理。
    if language == 'en':
        leaked = _cjk_leak()
        if leaked:
            raise ValueError('English render contains Chinese text: %r' % (leaked[:5],))
    img = img.resize((LAYOUT['width'], LAYOUT['height']), Image.Resampling.LANCZOS)
    out = img.convert('1', dither=Image.Dither.FLOYDSTEINBERG)
    if out_path:
        out.save(out_path)
        print('saved', out_path, file=sys.stderr, flush=True)
    else:
        out.save(sys.stdout.buffer, 'PNG')
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lang', choices=['en', 'zh', 'ru'], default='ru')
    ap.add_argument('--out')
    ap.add_argument('--data')
    ap.add_argument('--url', default='http://127.0.0.1:8787/api/dashboard')
    ap.add_argument('--page', type=int, default=1, help='page number: 1 dashboard, 2 slow info, 3 reading')
    ap.add_argument('--pages', type=int, default=1, help='total pages; >1 shows a page indicator')
    ap.add_argument('--check-fonts', action='store_true',
                    help='只校验字体能否渲染中文，失败则以非零码退出（CI 用）')
    a = ap.parse_args()
    # CI 上字体找错会渲染成方块，打出来便于排查
    print('[render] font_reg=%s%s' % (FONT_REG, '' if os.path.exists(FONT_REG) else '  <-- 缺失!'),
          file=sys.stderr, flush=True)
    print('[render] font_bold=%s%s' % (FONT_BOLD, '' if os.path.exists(FONT_BOLD) else '  <-- 缺失!'),
          file=sys.stderr, flush=True)

    if a.check_fonts:
        ok, info = check_fonts()
        for line in info:
            print('[font] ' + line, file=sys.stderr, flush=True)
        if not ok:
            print('[font] FAILED', file=sys.stderr, flush=True)
            sys.exit(2)
        print('[font] OK', file=sys.stderr, flush=True)
        return
    # 字体缺失时 f() 会退回 load_default：中文全变豆腐块，但退出码仍是 0，
    # 于是坏图会被当成好图推到 Pages 上。--check-fonts 只有 CI 会显式调用，
    # 本地/CI 正常出图这条路径也必须拦住。
    missing = [p for p in (FONT_REG, FONT_BOLD) if not os.path.exists(p)]
    if missing:
        print('[render] FAILED: font files missing: ' + ', '.join(missing), file=sys.stderr, flush=True)
        sys.exit(2)
    if a.data:
        with open(a.data, encoding='utf-8') as source:
            d = json.load(source)
    else:
        d = fetch_dashboard(a.url)
    render(d, a.out, a.lang, a.page, a.pages)

if __name__ == '__main__':
    main()
