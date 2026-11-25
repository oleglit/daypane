#!/usr/bin/env python3
"""Build a Pages artifact; failed attempts preserve the last published good PNG."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def previous_site(base, output):
    previous = {}
    if not base:
        return previous
    try:
        with urllib.request.urlopen(base.rstrip('/') + '/status.json?t=' + str(time.time_ns()), timeout=20) as r:
            previous = json.load(r)
        with urllib.request.urlopen(base.rstrip('/') + '/screen.png?t=' + str(time.time_ns()), timeout=20) as r:
            png = r.read(4 * 1024 * 1024 + 1)
        if len(png) > 4 * 1024 * 1024 or hashlib.sha256(png).hexdigest() != previous.get('sha256'):
            raise ValueError('previous published image checksum mismatch')
        from PIL import Image
        import io
        with Image.open(io.BytesIO(png)) as im:
            if not all(100 <= n <= 4096 for n in im.size):
                raise ValueError('invalid previous image size')
            im.verify()
        (output / 'screen.png').write_bytes(png)
        return previous
    except Exception as e:
        print('Previous generation unavailable:', e, file=sys.stderr)
        return {}


def build(output, previous, generate, metadata):
    started = int(time.time() * 1000)
    try:
        png, sections = generate()
        (output / 'screen.png').write_bytes(png)
        state = {**metadata, 'state': 'ready', 'generatedAt': int(time.time() * 1000),
                 'sha256': hashlib.sha256(png).hexdigest(), 'sections': sections}
        success = True
    except Exception as e:
        print('Generation failed:', e, file=sys.stderr)
        if not previous or not (output / 'screen.png').exists():
            # No artifact is published; Pages keeps its existing deployment.
            raise
        state = {**previous, **metadata, 'state': 'failed', 'error': str(e)[:500]}
        success = False
    state.update(lastAttemptAt=started, completedAt=int(time.time() * 1000), staleAfterSeconds=2700)
    history = previous.get('history', [])[-255:]
    history.append({k: state.get(k) for k in ('runId', 'trigger', 'requestedAt', 'lastAttemptAt', 'completedAt', 'state', 'generatedAt')})
    state['history'] = history
    # Immutable image names prevent a manifest/image race across deployments.
    import io
    from PIL import Image
    png = (output / 'screen.png').read_bytes()
    with Image.open(io.BytesIO(png)) as image:
        width, height = image.size
    images = output / 'images'
    images.mkdir(exist_ok=True)
    name = state['sha256'] + '.png'
    (images / name).write_bytes(png)
    write_json(output / 'manifest.json', {
        'schemaVersion': 1, 'image_url': 'images/' + name, 'sha256': state['sha256'],
        'generatedAt': state['generatedAt'], 'state': state['state'], 'width': width, 'height': height,
        'refreshAfterSeconds': 1800, 'staleAfterSeconds': 2700, 'language': metadata.get('language', 'ru')})
    write_json(output / 'status.json', state)
    (output / '.nojekyll').write_text('')
    (output / 'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>DayPane</title><style>body{font-family:system-ui;max-width:720px;margin:24px auto;padding:16px}img{width:100%}</style><h1>DayPane</h1><p id="status">Проверка обновления…</p><img id="image" src="screen.png" alt="Панель Kindle"><script>
async function refresh(){try{const s=await(await fetch('status.json?t='+Date.now())).json();const image=document.getElementById('image');if(image.dataset.hash!==s.sha256){image.src='images/'+s.sha256+'.png';image.dataset.hash=s.sha256;}const age=Math.max(0,Math.floor((Date.now()-s.generatedAt)/60000));document.getElementById('status').textContent=(age>45?'Данные устарели · ':s.state==='failed'?'Ошибка генерации, сохранено старое изображение · ':'Всё в порядке · ')+'Изображение создано '+new Date(s.generatedAt).toLocaleString()+' ('+age+' мин. назад)';}catch(e){document.getElementById('status').textContent='Не удалось прочитать статус';}}refresh();setInterval(refresh,60000);
</script></html>''', encoding='utf-8')
    return success


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='_site')
    ap.add_argument('--previous-url')
    args = ap.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    previous = previous_site(args.previous_url, output)
    work = output.parent / 'render-work'
    work.mkdir(exist_ok=True)

    def generate(language="ru"):
        subprocess.run([sys.executable, 'tools/render_screen.py', '--check-fonts'], check=True, timeout=20)
        # Collect public data once, then render each language from the same snapshot.
        # The primary cloud dashboard is Russian; do not gate collection on Chinese output.
        if not (work / 'dashboard.json').exists():
            with (work / 'dashboard.json').open('wb') as f:
                subprocess.run(['node', 'tools/dump_dashboard.js'], stdout=f, check=True, timeout=120)
        data = json.loads((work / 'dashboard.json').read_text())
        sections = {k: {'ok': bool(data.get(k, {}).get('ok')), 'fetchedAt': data.get(k, {}).get('fetchedAt'),
                         'error': str(data.get(k, {}).get('error', ''))[:240] if not data.get(k, {}).get('ok') else ''}
                    for k in ('weather', 'stocks', 'fx', 'news', 'mlb')}
        for name, section in sections.items():
            if section['error']:
                print('[data] %s unavailable: %s' % (name, section['error']), file=sys.stderr, flush=True)
        if not data.get('ok') or not any(v['ok'] for v in sections.values()):
            raise ValueError('all public data sources unavailable')
        subprocess.run([sys.executable, 'tools/render_screen.py', '--data', str(work / 'dashboard.json'),
                        '--out', str(work / 'screen.png'), '--lang', language], check=True, timeout=60)
        from PIL import Image
        with Image.open(work / 'screen.png') as im:
            if not all(100 <= n <= 4096 for n in im.size):
                raise ValueError('unexpected image size')
            im.verify()
        return (work / 'screen.png').read_bytes(), sections

    run_id = os.environ.get('GITHUB_RUN_ID', '')
    ok = build(output, previous, generate, {'runId': run_id,
        'trigger': os.environ.get('GITHUB_EVENT_NAME', 'local'),
        'requestedAt': os.environ.get('DISPATCH_REQUESTED_AT', ''),
        'runUrl': 'https://github.com/' + os.environ.get('GITHUB_REPOSITORY', '') + '/actions/runs/' + run_id})
    # Publish an independent English variant, preserving each locale's last good image.
    # 英文版首发失败（没有上一版可保留）时 build() 会抛异常 —— 以前这会让整个
    # 脚本退出，连已经生成好的中文站点都不会被部署。主链路必须和英文变体解耦。
    english = output / 'en'
    english.mkdir(exist_ok=True)
    ok_en = False
    try:
        previous_en = previous_site(args.previous_url.rstrip('/') + '/en' if args.previous_url else None, english)
        ok_en = build(english, previous_en, lambda: generate('en'), {'runId': run_id,
            'trigger': os.environ.get('GITHUB_EVENT_NAME', 'local'), 'language': 'en'})
        page = (english / 'index.html').read_text()
        for zh, en in {'lang="ru"':'lang="en"', 'Проверка обновления…':'Checking freshness…',
                       'Панель Kindle':'Kindle dashboard', 'Данные устарели · ':'Stale · ',
                       'Ошибка генерации, сохранено старое изображение · ':'Generation failed; previous image retained · ',
                       'Всё в порядке · ':'Ready · ', 'Изображение создано ':'Image generated at ',
                       ' мин. назад)':' minutes ago)', 'Не удалось прочитать статус':'Unable to read status'}.items():
            page = page.replace(zh, en)
        (english / 'index.html').write_text(page, encoding='utf-8')
        (output / 'screen-en.png').write_bytes((english / 'screen.png').read_bytes())
    except Exception as e:
        print('English variant failed; publishing the primary image as fallback:', e, file=sys.stderr)
        # 删掉可能残留的清单，让 Kindle 走"直接取图"路径，而不是拿旧清单去校验新图。
        for name in ('manifest.json', 'status.json'):
            p = english / name
            if p.exists():
                p.unlink()
        (output / 'screen-en.png').write_bytes((output / 'screen.png').read_bytes())
        ok_en = False
    ok = ok and ok_en
    import shutil
    shutil.copytree('web/setup', output / 'setup', dirs_exist_ok=True)
    if os.environ.get('GITHUB_OUTPUT'):

        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('fresh=' + str(ok).lower() + '\n')


if __name__ == '__main__':
    main()
