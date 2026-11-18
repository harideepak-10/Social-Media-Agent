"""Product promo video studio (style of the Krypsos sample videos).

1. Capture the product page's UI blocks (visuals.py).
2. The design model SEES the blocks and writes a storyboard: intro → feature scenes (eyebrow, headline
   with accent words, 3 icon bullets, floating stat badges taken from the UI) → 'everything in one place'
   grid → outro with CTA.
3. Every scene is an HTML/CSS page with timed animations; Chromium renders it frame-by-frame
   (deterministic, crisp), piped straight into ffmpeg. Landscape 16:9 and vertical 9:16 versions.
4. Voice-over (optional) + background music with ducking.
"""
from __future__ import annotations

import html as H
import json
import logging
import random
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from .. import llm, progress
from .. import storage
from ..config import ASSETS_DIR, company, settings
from ..generators import browser, ffmpeg, tts
from . import assets, icons, rotation, visuals
from .catalog import ICONS, VIDEO_THEMES

log = logging.getLogger(__name__)

SIZES = {"landscape": (1920, 1080), "vertical": (1080, 1920)}

SYSTEM = """You are a creative director making premium SaaS product videos (think Linear/Stripe launch videos).
Copy is short, confident and benefit-led. Headlines are 3-7 words, often split so the LAST part is the accent
(e.g. headline 'Your whole restaurant,' + accent 'in one glance.'). Bullets are max 8 words each.
You never invent features, numbers or claims: badge values must be copied exactly from what is visible in the
chosen UI block. Every video must feel fresh — never reuse headlines from the 'already used' list."""


# ── storyboard ────────────────────────────────────────────────────────────
def storyboard(plan: dict, product: dict | None, cap: dict, work: Path, voice: bool) -> dict:
    blocks = cap["blocks"][:12]
    sheet = visuals.contact_sheet(blocks, work / "sheet.jpg") if blocks else None
    c = company()
    block_lines = "\n".join(f"B{b['id']} ({b['w']}x{b['h']}): {b['text'][:300]}" for b in blocks)
    max_s = int((settings().get("video") or {}).get("max_seconds", 75))
    prompt = f"""BRAND: {c.get('name')} — {c.get('tagline')} | {c.get('website')}
PRODUCT: {(product or {}).get('name') or plan['topic']} — {(product or {}).get('description', '')}
AUDIENCE: {c.get('audience')}
VIDEO IDEA: {plan['topic']} — {plan['angle']} (hook idea: {plan['hook']}) {plan.get('context', '')}

PAGE TEXT (facts you may use):
{cap['text'][:3500]}

UI BLOCKS captured from the page (see the attached contact sheet, labelled B0, B1, …):
{block_lines or '(none)'}

ALREADY USED RECENTLY (do not repeat):
{rotation.recent_creative_memory()}

Write a storyboard for a {max_s}-second-max promo video.
- intro: eyebrow (3-6 words, e.g. 'THE ALL-IN-ONE RESTAURANT OS'), headline + accent (2 lines total),
  sub (max 16 words), chips (3-5 short feature names).
- scenes: 4-7 feature scenes, each uses ONE block id that clearly shows a product screen/feature
  (prefer app/dashboard-like blocks; skip contact forms, logos, plain text). Order them as a story.
  Each: block, eyebrow (2-3 words, e.g. 'THE DASHBOARD'), headline + accent, 3 bullets
  [{{"icon": one of {ICONS}, "text": "…"}}], badges: 0-2 [{{"value": "exact number/text visible in that block",
  "label": "2-3 words"}}].
- grid: eyebrow, headline + accent ('Everything X runs,' + 'in one place.'), 6 or 9 items
  [{{"icon", "title" (2-3 words), "desc" (max 7 words)}}].
- outro: headline + accent (short), cta (e.g. 'Book a free demo'), url (display form of the website).
{"- voice: every intro/scene/grid/outro has a 'voice' line — natural spoken English, 1-2 short sentences (max 24 words), adds to the on-screen text instead of reading it." if voice else "- no voice lines needed."}
Also captions for instagram/facebook/linkedin and 8-12 hashtags.

Return JSON: {{"title": "…", "intro": {{…}}, "scenes": [{{…}}], "grid": {{…}}, "outro": {{…}},
 "captions": {{"instagram": "…", "facebook": "…", "linkedin": "…"}}, "hashtags": ["#…"]}}"""
    data = llm.complete_json(prompt, SYSTEM, max_tokens=6000, design=True,
                             images=[sheet] if sheet and llm.vision_available() else None)
    valid = {f"B{b['id']}": b for b in blocks}
    scenes = []
    for sc in data.get("scenes") or []:
        b = valid.get(str(sc.get("block", "")).upper().strip())
        if not b:
            continue
        flat = re.sub(r"\s+", "", b["text"])
        sc["badges"] = [bd for bd in (sc.get("badges") or [])[:2]
                        if re.sub(r"\s+", "", str(bd.get("value", ""))) and re.sub(r"\s+", "", str(bd["value"])) in flat]
        sc["_block"] = b
        scenes.append(sc)
    if not scenes and blocks:  # fallback: show the first blocks with generic copy
        scenes = [{"_block": b, "eyebrow": "SEE IT IN ACTION", "headline": plan["topic"], "accent": "",
                   "bullets": [], "badges": [], "voice": ""} for b in blocks[:3]]
    data["scenes"] = scenes[:7]
    return data


# ── HTML scenes ───────────────────────────────────────────────────────────
def _e(s) -> str:
    return H.escape(str(s or ""))


def _head(theme: dict, size: tuple[int, int]) -> str:
    w, h = size
    fams = {theme["heading"], theme["body"]}
    link = "https://fonts.googleapis.com/css2?" + "&".join(
        f"family={f.replace(' ', '+')}:wght@400;500;600;700;800" for f in fams) + "&display=swap"
    vert = h > w
    t = theme
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><link rel="stylesheet" href="{link}">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden;background:{t['bg']};color:{t['ink']};
 font-family:'{t['body']}',Inter,'Segoe UI',Arial,sans-serif;-webkit-font-smoothing:antialiased}}
.bg{{position:absolute;inset:0;background:
 radial-gradient(ellipse 60% 55% at 12% 8%, {t['bg2']} 0%, transparent 70%),
 radial-gradient(ellipse 50% 50% at 92% 95%, {t['accent']}22 0%, transparent 70%),
 radial-gradient(ellipse 35% 30% at 85% 10%, {t['accent2']}14 0%, transparent 70%), {t['bg']}}}
.grid{{position:absolute;inset:0;opacity:.5;background-image:linear-gradient({t['ink']}08 1px,transparent 1px),
 linear-gradient(90deg,{t['ink']}08 1px,transparent 1px);background-size:64px 64px;
 -webkit-mask-image:radial-gradient(ellipse at 50% 40%,#000 0%,transparent 75%)}}
.stage{{position:absolute;inset:0;animation:stageIn .55s ease-out both, stageOut .45s ease-in both;
 animation-delay:0s, calc(var(--dur) - .45s)}}
@keyframes stageIn{{from{{opacity:0}}to{{opacity:1}}}}
@keyframes stageOut{{from{{opacity:1}}to{{opacity:0}}}}
@keyframes up{{from{{opacity:0;transform:translateY(26px)}}to{{opacity:1;transform:none}}}}
@keyframes slideIn{{from{{opacity:0;transform:translateX(70px) scale(.97);filter:blur(6px)}}to{{opacity:1;transform:none;filter:none}}}}
@keyframes slideInL{{from{{opacity:0;transform:translateX(-70px) scale(.97);filter:blur(6px)}}to{{opacity:1;transform:none;filter:none}}}}
@keyframes rise{{from{{opacity:0;transform:translateY(60px) scale(.97)}}to{{opacity:1;transform:none}}}}
@keyframes pop{{0%{{opacity:0;transform:scale(.8) translateY(10px)}}70%{{opacity:1;transform:scale(1.04)}}100%{{opacity:1;transform:none}}}}
@keyframes drift{{from{{transform:scale(1)}}to{{transform:scale(1.035)}}}}
@keyframes pan{{from{{transform:translateY(0)}}to{{transform:translateY(var(--pan))}}}}
@keyframes glow{{from{{opacity:.35}}to{{opacity:.8}}}}
.a{{animation:up .8s cubic-bezier(.2,.8,.2,1) both}}
.brand{{position:absolute;left:{70 if vert else 110}px;top:{80 if vert else 64}px;height:{52 if vert else 46}px;
 display:flex;align-items:center;gap:14px;font-weight:700;font-size:{26 if vert else 24}px}}
.brand img{{height:100%;width:auto}}
.eyebrow{{display:flex;align-items:center;gap:14px;color:{t['accent']};font-weight:700;letter-spacing:.28em;
 text-transform:uppercase;font-size:{24 if vert else 21}px}}
.eyebrow:before{{content:"";width:10px;height:10px;border-radius:50%;background:{t['accent']};box-shadow:0 0 18px {t['accent']}}}
h1{{font-family:'{t['heading']}',{'Georgia,serif' if t['serif'] else "'Segoe UI',Inter,Arial,sans-serif"};font-weight:{t['head_weight']};letter-spacing:{'-0.01em' if t['serif'] else '-0.035em'};
 line-height:1.04;color:{t['ink']}}}
.acc{{background:linear-gradient(90deg,{t['accent']},{t['accent2']});-webkit-background-clip:text;background-clip:text;color:transparent;
 {'font-style:italic;' if t['serif'] else ''}}}
.muted{{color:{t['muted']}}}
.bul{{list-style:none;display:flex;flex-direction:column;gap:{22 if vert else 18}px}}
.bul li{{display:flex;align-items:center;gap:18px;font-size:{31 if vert else 26}px;color:{t['ink']}d9}}
.bul svg{{color:{t['accent']};flex:none}}
.win{{position:absolute;border-radius:18px;background:{t['panel']};border:1px solid {t['ink']}1a;overflow:hidden;
 box-shadow:0 50px 140px rgba(0,0,0,.55),0 0 0 1px rgba(0,0,0,.2)}}
.win .bar{{height:46px;display:flex;align-items:center;gap:9px;padding:0 20px;border-bottom:1px solid {t['ink']}12;
 font-size:16px;color:{t['muted']};letter-spacing:.02em}}
.win .bar i{{width:12px;height:12px;border-radius:50%;display:block}}
.win .bar span{{flex:1;text-align:center;margin-right:60px}}
.win .vp{{position:relative;overflow:hidden}}
.win .vp img{{display:block;width:100%;animation:drift var(--dur) linear both, pan var(--dur) ease-in-out both}}
.badge{{position:absolute;padding:16px 26px;border-radius:16px;background:{t['panel']}e6;border:1px solid {t['accent']}55;
 box-shadow:0 20px 60px rgba(0,0,0,.45),0 0 40px {t['accent']}22;backdrop-filter:blur(8px);animation:pop .7s cubic-bezier(.2,.8,.2,1) both}}
.badge b{{display:block;font-size:{46 if vert else 42}px;font-weight:800;color:{t['accent']};letter-spacing:-.02em;font-family:'{t['body']}',sans-serif}}
.badge small{{display:block;font-size:15px;letter-spacing:.18em;text-transform:uppercase;color:{t['muted']};margin-top:2px}}
.chip{{display:inline-flex;align-items:center;gap:10px;padding:12px 22px;border-radius:99px;border:1px solid {t['ink']}22;
 background:{t['ink']}0a;font-size:{24 if vert else 20}px;color:{t['ink']}cc}}
.card{{background:{t['panel']};border:1px solid {t['ink']}14;border-radius:18px;padding:26px;display:flex;flex-direction:column;gap:10px}}
.card .ic{{width:52px;height:52px;border-radius:14px;display:grid;place-items:center;background:{t['accent']}1f;color:{t['accent']}}}
.card b{{font-size:{26 if vert else 23}px}}
.card p{{font-size:{20 if vert else 17}px;color:{t['muted']};line-height:1.35}}
.btn{{display:inline-block;padding:20px 40px;border-radius:99px;background:linear-gradient(90deg,{t['accent']},{t['accent2']});
 color:{'#111' if t['logo'] == 'light' else '#fff'};font-weight:800;font-size:{30 if vert else 26}px;box-shadow:0 20px 60px {t['accent']}55}}
</style></head>"""


_COUNTER_JS = """<script>
const fmt=(n,dec,indian)=>{let s=n.toFixed(dec);let [i,d]=s.split('.');
 if(indian){let l=i.slice(-3),r=i.slice(0,-3);if(r)l=r.replace(/\\B(?=(\\d{2})+(?!\\d))/g,',')+','+l;i=l}
 else i=i.replace(/\\B(?=(\\d{3})+(?!\\d))/g,',');return d?i+'.'+d:i};
const C=[...document.querySelectorAll('[data-count]')].map(e=>{const m=e.textContent.match(/^(\\D*?)([\\d,]+(?:\\.\\d+)?)(.*)$/);
 if(!m)return null;const raw=m[2];return{e,pre:m[1],post:m[3],v:parseFloat(raw.replace(/,/g,'')),dec:(raw.split('.')[1]||'').length,
 indian:/\\d,\\d\\d,\\d{3}/.test(raw),comma:raw.includes(','),start:parseFloat(e.dataset.start||'1')}}).filter(Boolean);
window.__render=t=>{for(const c of C){const p=Math.min(1,Math.max(0,(t-c.start)/1.3));const k=1-Math.pow(1-p,3);
 const n=c.v*k;c.e.textContent=c.pre+(c.comma?fmt(n,c.dec,c.indian):n.toFixed(c.dec))+c.post}};window.__render(0);
</script>"""


def _brand_html(logo_file: str | None) -> str:
    c = company()
    if logo_file:
        return f'<div class="brand a" style="animation-delay:.1s"><img src="{logo_file}"></div>'
    return f'<div class="brand a" style="animation-delay:.1s">{_e(c.get("name"))}</div>'


def _doc(theme, size, dur, body, logo_file, brand=True) -> str:
    return (_head(theme, size) + f'<body style="--dur:{dur:.2f}s"><div class="bg"></div><div class="grid"></div>'
            f'<div class="stage">{_brand_html(logo_file) if brand else ""}{body}</div>{_COUNTER_JS}</body></html>')


def _headline(d: dict) -> str:
    acc = d.get("accent", "")
    return f'{_e(d.get("headline", ""))}{"<br>" if acc else ""}<span class="acc">{_e(acc)}</span>'


def scene_intro(d, theme, size, dur, logo, product_name):
    w, h = size
    vert = h > w
    chips = "".join(f'<span class="chip a" style="animation-delay:{1.1 + i * .12:.2f}s">{_e(c)}</span>'
                    for i, c in enumerate((d.get("chips") or [])[:5]))
    fs = 104 if vert else 92
    body = f"""<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
 text-align:center;padding:0 {90 if vert else 260}px;gap:{38 if vert else 30}px">
 <div class="eyebrow a" style="animation-delay:.25s">{_e(d.get('eyebrow'))}</div>
 <h1 class="a" style="font-size:{fs}px;animation-delay:.45s">{_headline(d)}</h1>
 <p class="a muted" style="font-size:{34 if vert else 29}px;max-width:1100px;line-height:1.4;animation-delay:.75s">{_e(d.get('sub'))}</p>
 <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:14px;margin-top:10px">{chips}</div>
 <div class="a muted" style="font-size:{22 if vert else 18}px;letter-spacing:.2em;text-transform:uppercase;animation-delay:1.6s">{_e(product_name)}</div>
</div>"""
    return _doc(theme, size, dur, body, logo)


def scene_feature(d, theme, size, dur, logo, idx, title):
    w, h = size
    vert = h > w
    b = d["_block"]
    flip = (idx % 2 == 1) and not vert
    bullets = "".join(f'<li class="a" style="animation-delay:{.95 + i * .16:.2f}s">{icons.svg(x.get("icon", "check"), 30 if vert else 26)}'
                      f'<span>{_e(x.get("text"))}</span></li>' for i, x in enumerate((d.get("bullets") or [])[:3]))
    if vert:
        win_w, win_x, win_y = w - 100, 50, 800
        max_vp = h - win_y - 230
        text_css = f"position:absolute;left:70px;right:70px;top:230px;display:flex;flex-direction:column;gap:30px"
        hfs = 76
    else:
        win_w, win_y = 1040, 160
        win_x = 110 if flip else w - win_w - 90
        max_vp = h - win_y - 120 - 46
        text_css = (f"position:absolute;{'right:110px' if flip else 'left:110px'};top:0;bottom:0;width:640px;"
                    "display:flex;flex-direction:column;justify-content:center;gap:28px")
        hfs = 70 if not theme["serif"] else 66
    img_h = round(win_w * b["h"] / max(1, b["w"]))
    vp_h = min(img_h, max_vp)
    pan = -(img_h - vp_h) if img_h > vp_h else 0
    if not vert:  # vertically centre the window
        win_y = max(120, (h - vp_h - 46) // 2 + 10)
    badges = ""
    spots = ([("right:-26px", "top:-34px"), ("left:-40px", "bottom:-30px")] if not vert
             else [("right:-14px", "top:-60px"), ("left:-14px", "bottom:-44px")])
    for i, bd in enumerate((d.get("badges") or [])[:2]):
        x, y = spots[i]
        start = 1.5 + i * .35
        badges += (f'<div class="badge" style="{x};{y};animation-delay:{start:.2f}s"><b data-count data-start="{start:.2f}">'
                   f'{_e(bd.get("value"))}</b><small>{_e(bd.get("label"))}</small></div>')
    anim = "slideInL" if flip else ("rise" if vert else "slideIn")
    body = f"""<div style="{text_css}">
 <div class="eyebrow a" style="animation-delay:.3s">{_e(d.get('eyebrow'))}</div>
 <h1 class="a" style="font-size:{hfs}px;animation-delay:.5s">{_headline(d)}</h1>
 <ul class="bul" style="margin-top:6px">{bullets}</ul>
</div>
<div style="position:absolute;left:{win_x}px;top:{win_y}px;width:{win_w}px;animation:{anim} 1s cubic-bezier(.2,.8,.2,1) .35s both">
 <div style="position:absolute;inset:-60px;background:radial-gradient(closest-side,{theme['accent']}26,transparent);filter:blur(20px);animation:glow 3s ease-in-out infinite alternate"></div>
 <div class="win" style="position:relative;left:0;top:0;width:{win_w}px">
  <div class="bar"><i style="background:#FF5F57"></i><i style="background:#FEBC2E"></i><i style="background:#28C840"></i><span>{_e(title)}</span></div>
  <div class="vp" style="height:{vp_h}px;--pan:{pan}px"><img src="{Path(b['path']).name}"></div>
 </div>
 {badges}
</div>"""
    return _doc(theme, size, dur, body, logo)


def scene_grid(d, theme, size, dur, logo):
    w, h = size
    vert = h > w
    items = (d.get("items") or [])[:9]
    cols = 2 if vert else 3
    if vert and len(items) % 2:
        items = items[:-1] or items
    cards = "".join(f'<div class="card a" style="animation-delay:{.7 + i * .09:.2f}s"><div class="ic">{icons.svg(it.get("icon", "check"), 28)}</div>'
                    f'<b>{_e(it.get("title"))}</b><p>{_e(it.get("desc"))}</p></div>' for i, it in enumerate(items))
    body = f"""<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
 gap:{48 if vert else 44}px;padding:{'0 60px' if vert else '0 200px'}">
 <div style="text-align:center;display:flex;flex-direction:column;align-items:center;gap:22px">
  <div class="eyebrow a" style="animation-delay:.2s">{_e(d.get('eyebrow'))}</div>
  <h1 class="a" style="font-size:{70 if vert else 60}px;animation-delay:.4s">{_e(d.get('headline'))} <span class="acc">{_e(d.get('accent'))}</span></h1>
 </div>
 <div style="display:grid;grid-template-columns:repeat({cols},1fr);gap:{22 if vert else 20}px;width:100%">{cards}</div>
</div>"""
    return _doc(theme, size, dur, body, logo)


def scene_outro(d, theme, size, dur, logo):
    w, h = size
    vert = h > w
    logo_html = (f'<img src="{logo}" style="height:{110 if vert else 96}px" class="a">' if logo
                 else f'<div class="a" style="font-size:64px;font-weight:800">{_e(company().get("name"))}</div>')
    body = f"""<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:40px;text-align:center;padding:0 80px">
 <div style="position:absolute;width:900px;height:900px;border-radius:50%;background:radial-gradient(closest-side,{theme['accent']}30,transparent);animation:glow 2.5s ease-in-out infinite alternate"></div>
 <div style="animation-delay:.2s;position:relative" class="a">{logo_html}</div>
 <h1 class="a" style="position:relative;font-size:{60 if vert else 52}px;animation-delay:.5s">{_e(d.get('headline'))} <span class="acc">{_e(d.get('accent'))}</span></h1>
 <div class="a" style="position:relative;display:flex;flex-direction:{'column' if vert else 'row'};align-items:center;gap:26px;animation-delay:.85s">
  <span class="btn">{_e(d.get('cta') or 'Book a free demo')}</span>
  <span class="muted" style="font-size:{30 if vert else 26}px">{_e(d.get('url'))}</span>
 </div>
</div>"""
    return _doc(theme, size, dur, body, logo, brand=False)


# ── rendering ─────────────────────────────────────────────────────────────
def _render_frames(scenes: list[tuple[Path, float]], size: tuple[int, int], out: Path, fps: int,
                   on_progress=None) -> Path:
    """Render each HTML scene frame-by-frame (animations seeked precisely) and pipe JPEGs into ffmpeg.

    LOW_MEMORY=1 (small servers like Render free, 512 MB / 0.1 CPU): frames are drawn at half resolution and
    15 fps, then scaled back to full HD / 30 fps by ffmpeg – about 1/8 of the pixels to draw and far less memory."""
    w, h = size
    low = ffmpeg.low_memory()
    scale = 0.5 if low else 1
    rfps = min(fps, 15) if low else fps
    vf = [f"scale={w}:{h}:flags=lanczos", "unsharp=5:5:0.6"] if low else []
    x264 = (["-preset", "ultrafast", "-threads", "1", "-x264-params", "rc-lookahead=0:ref=1:bframes=0"]
            if low else list(ffmpeg.X264))
    cmd = [ffmpeg.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(rfps),
           "-c:v", "mjpeg", "-i", "-", *(["-vf", ",".join(vf)] if vf else []),
           "-c:v", "libx264", *x264, "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps), str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    total_frames = sum(int(round(d * rfps)) for _, d in scenes) or 1
    done = 0
    try:
        extra_args = ["--single-process", "--in-process-gpu"] if low else []  # one Chromium process instead of four
        with browser.browser_context(viewport={"width": w, "height": h}, device_scale_factor=scale,
                                     extra_args=extra_args) as ctx:
            page = ctx.new_page()
            for html_path, dur in scenes:
                page.goto(html_path.resolve().as_uri(), wait_until="load", timeout=60000)
                try:
                    page.evaluate("document.fonts.ready.then(() => true)")
                except Exception:
                    pass
                page.wait_for_timeout(300)
                page.evaluate("document.getAnimations().forEach(a => a.pause())")
                # when every animation has finished the picture no longer changes: reuse the last frame
                settle = page.evaluate("""() => window.__render ? 1e9 : Math.max(0, ...document.getAnimations().map(a => {
                    const e = a.effect && a.effect.getComputedTiming().endTime;
                    return (e === Infinity || e == null) ? 1e9 : e; })) / 1000""")
                last = None
                for i in range(int(round(dur * rfps))):
                    t = i / rfps
                    if last is None or t <= settle + 1 / rfps:
                        page.evaluate("t => { document.getAnimations().forEach(a => { try { a.currentTime = t * 1000 } catch (e) {} });"
                                      " window.__render && window.__render(t); }", t)
                        last = page.screenshot(type="jpeg", quality=88)
                    proc.stdin.write(last)
                    done += 1
                    if on_progress and done % rfps == 0:
                        on_progress(done / total_frames)
        proc.stdin.close()
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        raise ffmpeg.FFmpegError(proc.stderr.read().decode()[-1500:] if proc.stderr else "frame render failed")
    return out


def _audio_track(segments: list[tuple[Path | None, float, float]], total: float, work: Path) -> Path | None:
    """segments: (voice file, start second, scene duration). Voice placed at scene start + 0.45s,
    music (assets/music/*.mp3) underneath with ducking. Returns an m4a or None if no audio at all."""
    music_files = sorted((ASSETS_DIR / "music").glob("*.mp3"))
    use_music = (settings().get("video") or {}).get("background_music", True) and music_files
    voices = [(p, s) for p, s, _ in segments if p]
    if not voices and not use_music:
        return None
    inputs, filters, labels = [], [], []
    for i, (p, start) in enumerate(voices):
        inputs += ["-i", str(p)]
        ms = int((start + 0.45) * 1000)
        filters.append(f"[{i}:a]adelay={ms}|{ms},aformat=channel_layouts=stereo[v{i}]")
        labels.append(f"[v{i}]")
    out = work / "audio.m4a"
    if voices:
        filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,apad,atrim=0:{total:.2f}[vo]")
    if use_music:
        mi = len(voices)
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(music_files))]
        filters.append(f"[{mi}:a]atrim=0:{total:.2f},volume=0.55,afade=t=in:d=1.2,afade=t=out:st={max(0, total - 2):.2f}:d=2,"
                       f"aformat=channel_layouts=stereo[m]")
        if voices:
            filters.append("[vo]asplit=2[vo1][sc]")
            filters.append("[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[md]")
            filters.append("[vo1][md]amix=inputs=2:normalize=0[out]")
        else:
            filters.append("[m]anull[out]")
    else:
        filters.append("[vo]anull[out]")
    ffmpeg.run([*inputs, "-filter_complex", ";".join(filters), "-map", "[out]", "-t", f"{total:.2f}",
                "-c:a", "aac", "-b:a", "192k", str(out)])
    return out


def build(board: dict, theme_name: str, work: Path, targets: dict[str, Path], product_name: str,
          orientations: list[str], voice: bool) -> dict[str, Path]:
    theme = VIDEO_THEMES[theme_name]
    vcfg = settings().get("video") or {}
    fps = int(vcfg.get("fps", 30))
    logo = assets.brand_logo(company())
    logo_file = None
    if logo:
        shutil.copy(logo[theme["logo"]], work / "logo.png")
        logo_file = "logo.png"
    for sc in board["scenes"]:
        shutil.copy(sc["_block"]["path"], work / Path(sc["_block"]["path"]).name)

    # 1) voice-over and timing
    progress.report("Recording the voice-over" if voice else "Timing the scenes", 35)
    parts = [("intro", board.get("intro") or {})] + [("scene", s) for s in board["scenes"]] + \
            [("grid", board.get("grid") or {}), ("outro", board.get("outro") or {})]
    if not (board.get("grid") or {}).get("items"):
        parts = [p for p in parts if p[0] != "grid"]
    base = {"intro": 4.6, "scene": 6.4, "grid": 6.0, "outro": 5.0}
    timeline, t0 = [], 0.0
    for i, (kind, d) in enumerate(parts):
        vpath, vsec = None, 0.0
        if voice and d.get("voice"):
            vpath, vsec = tts.speak(d["voice"], work / f"vo_{i}")
        dur = max(base[kind], vsec + 1.2) if vpath else base[kind]
        dur = min(dur, 12.0)
        timeline.append((kind, d, vpath, t0, dur))
        t0 += dur
    total = t0

    outputs = {}
    title = f"{product_name} · " if product_name else ""
    for orient in orientations:
        size = SIZES[orient]
        scenes, si = [], 0
        for i, (kind, d, _, _, dur) in enumerate(timeline):
            if kind == "intro":
                doc = scene_intro(d, theme, size, dur, logo_file, product_name)
            elif kind == "scene":
                doc = scene_feature(d, theme, size, dur, logo_file, si,
                                    title + (d.get("eyebrow", "").title() or "Overview"))
                si += 1
            elif kind == "grid":
                doc = scene_grid(d, theme, size, dur, logo_file)
            else:
                doc = scene_outro(d, theme, size, dur, logo_file)
            p = work / f"{orient}_{i:02d}_{kind}.html"
            p.write_text(doc, encoding="utf-8")
            scenes.append((p, dur))
        silent = work / f"{orient}_video.mp4"
        oi = orientations.index(orient)
        span = 55 / len(orientations)
        label = "16:9" if orient == "landscape" else "9:16"
        lo = 40 + oi * span
        _render_frames(scenes, size, silent, fps,
                       on_progress=lambda f, lo=lo, label=label: progress.report(
                           f"Rendering {label} video – {int(f * 100)}%", lo + f * span, throttle=2))
        outputs[orient] = silent

    progress.report("Mixing music and voice", 96)
    audio = _audio_track([(v, s, d) for _, _, v, s, d in timeline], total, work)
    final = {}
    for orient, silent in outputs.items():
        out = targets[orient]
        if audio:
            ffmpeg.run(["-i", str(silent), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out)])
        else:
            ffmpeg.run(["-i", str(silent), "-c:v", "copy", "-movflags", "+faststart", str(out)])
        final[orient] = out
    return final


def generate(plan: dict, day: date, item_id: int, theme_name: str, product: dict | None) -> dict:
    vcfg = settings().get("video") or {}
    work = storage.work_dir("video", item_id)
    voice = bool(vcfg.get("voiceover", True))
    orientations = vcfg.get("formats") or ["landscape", "vertical"]

    url = (product or {}).get("url") or (plan.get("page_urls") or [company().get("website")])[0]
    progress.report("Capturing the product screens", 12)
    cap = visuals.capture(url, work / "cap")
    # add blocks from a second page if the first one is thin
    for extra in (plan.get("page_urls") or [])[1:3]:
        if len(cap["blocks"]) >= 6 or extra == url:
            break
        more = visuals.capture(extra, work / f"cap_{len(cap['blocks'])}")
        offset = len(cap["blocks"]) + 100
        for b in more["blocks"]:
            b["id"] += offset
        cap["blocks"] += more["blocks"]
        cap["text"] += " " + more["text"][:2000]

    progress.report(f"AI is writing the storyboard from {len(cap['blocks'])} screens", 25)
    board = storyboard(plan, product, cap, work, voice)
    product_name = (product or {}).get("name", "")
    files = build(board, theme_name, work, storage.video_paths(day, item_id, plan, "promo"),
                  product_name, orientations, voice)
    main = files[orientations[0]]
    alt = files.get("vertical") if orientations[0] != "vertical" else None
    thumb = ffmpeg.thumbnail(main, storage.thumb_path(main), at=1.6)
    shutil.rmtree(work, ignore_errors=True)

    tags = [t if t.startswith("#") else f"#{t}" for t in board.get("hashtags", [])]
    clean = {k: v for k, v in board.items() if k not in ("captions", "hashtags")}
    for sc in clean.get("scenes", []):
        sc.pop("_block", None)
    clean.update({"headline": (board.get("intro") or {}).get("headline", ""), "theme": theme_name,
                  "product": product_name})
    return {"copy": board, "media": main, "alt": alt, "thumb": thumb, "hashtags": " ".join(tags),
            "script_json": json.dumps(clean, ensure_ascii=False, indent=2)}
