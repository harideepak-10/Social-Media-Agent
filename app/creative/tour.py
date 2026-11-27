""""Product tour" video style – like a polished SaaS launch demo:
full-screen app screens, a cursor that moves and clicks through the pages, and one section at a time lifted out of a
blurred screen with a numbered label ("1  Your tools, connected"). Screen recordings play full screen with the
spotlight on the area where the action happens.

Works with video_studio: capture() collects the material, storyboard() asks the AI for the tour, scene_*() build the
HTML that video_studio's frame-by-frame renderer draws (window.__render(t) = everything that moves)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from PIL import Image, ImageDraw

from .. import llm, progress
from ..config import company
from ..research import explorer
from . import brandfix, recording, rotation, screenrec, visuals

log = logging.getLogger(__name__)

LENGTHS = {"short": {"scenes": "4-7", "label": "short tour (about 45-75 s)"},
           "full": {"scenes": "9-18", "label": "full product tour (2-4 minutes)"}}
SYSTEM = """You are the creative director of product-launch demo videos for SaaS and web apps (think Linear, Notion,
Stripe launch videos). You write tight, confident tours: the real product on screen, one idea per moment, labels a
customer understands in two seconds. Never invent features, numbers or claims that are not in the material."""


# ── material ────────────────────────────────────────────────────────────────
def capture(plan: dict, work: Path, uploads: list[dict] | None, max_pages: int = 6) -> dict:
    """Every chosen page as full 1920x1080 screens with the sections to spotlight, plus the user's recordings (clips
    with their action area) and screenshots. Returns {screens: [...], media: [...]}."""
    out = {"screens": [], "media": []}
    urls = list(dict.fromkeys(plan.get("page_urls") or []))[:max_pages]
    names = {p.get("url"): p.get("name") for p in plan.get("pages_meta") or []}
    for i, u in enumerate(urls):
        progress.report(f"Opening page {i + 1} of {len(urls)}: {u.split('//')[-1][:60]}", 12 + int(10 * i / max(1, len(urls))))
        progress.check()
        try:
            cap = visuals.tour_capture(u, work / f"tour{i}", max_screens=2 if len(urls) > 3 else 3)
        except Exception as e:
            log.warning("tour capture of %s failed: %s", u, e)
            continue
        for s in cap["screens"]:
            with Image.open(s["path"]) as im:
                if recording.is_blank(im):  # an empty screen (still loading, blank page) is never shown
                    continue
            out["screens"].append({"id": f"P{i}S{s['id']}", "path": s["path"], "w": s["w"], "h": s["h"], "url": u,
                                   "page": names.get(u) or cap["title"].split("|")[0].strip() or u,
                                   "spots": s["spots"], "links": cap["links"][:80], "text": cap["text"][:1200]})
    imgs = [u for u in uploads or [] if not (u.get("video") or recording.is_video(u["path"]))]
    recs = [u for u in uploads or [] if u not in imgs]
    for j, up in enumerate(recs):
        # a screen recording = the person clicking through their app: find its pages (in order), the panels on
        # each page to spotlight, where they clicked, and moments where something happens in place
        progress.report(f"Watching your screen recording {j + 1}: finding its pages", 18)
        progress.check()
        try:
            got = screenrec.analyze(Path(up["path"]), up.get("caption", ""), j, work / f"rec{j}",
                                    max_pages={1: 20, 2: 12}.get(len(recs), 8))
            out["screens"] += got["screens"]
            out["media"] += got["media"]
        except Exception as e:
            log.warning("screen recording %s skipped: %s", up["path"], e)
    for j, up in enumerate(imgs):
        p = Path(up["path"])
        try:
            with Image.open(p) as im:
                w, h = im.size
        except Exception:
            continue
        out["media"].append({"id": f"U{j}", "path": p, "w": w, "h": h, "user": True,
                             "text": up.get("caption", "") or "(screenshot from the user)"})
    return out


def _sheets(cap: dict, work: Path) -> list[Path]:
    """Contact sheets for the AI: every screen with its numbered spotlight boxes (6 per sheet, big enough to read),
    then the user's clips/screenshots."""
    tiles = []
    for s in cap["screens"]:
        im = Image.open(s["path"]).convert("RGB")
        d = ImageDraw.Draw(im)
        for k, sp in enumerate(s["spots"]):
            box = [sp["x"] * im.width, sp["y"] * im.height, (sp["x"] + sp["w"]) * im.width, (sp["y"] + sp["h"]) * im.height]
            d.rectangle(box, outline=(239, 68, 68), width=8)
            d.rectangle([box[0], box[1], box[0] + 70, box[1] + 60], fill=(239, 68, 68))
            d.text((box[0] + 18, box[1] + 4), str(k + 1), fill="white", font=_font(48))
        p = work / f"sheet_{s['id']}.jpg"
        im.thumbnail((960, 540))
        im.save(p, quality=80)
        tiles.append({"id": s["id"], "path": p})
    for m in cap["media"]:
        tiles.append({"id": m["id"], "path": m["path"]})
    out = []
    for n in range(0, min(len(tiles), 36), 6):
        out.append(visuals.contact_sheet(tiles[n:n + 6], work / f"tour_sheet{n // 6}.jpg", thumb_w=620))
    return out


def _font(size: int):
    from ..generators import graphics
    return graphics.font(size, True)


# ── storyboard ──────────────────────────────────────────────────────────────
def storyboard(plan: dict, product: dict | None, cap: dict, work: Path, voice: bool, length: str = "short") -> dict:
    L = LENGTHS.get(length, LENGTHS["short"])
    c = company()
    sheets = _sheets(cap, work)
    screen_lines = "\n".join(
        (f"{s['id']} – page \"{s['page']}\" ({s['url']}):\n" if s.get("url") else
         f"{s['id']} – a page from the user's screen recording ({s['page']}){' – reached by clicking the sidebar' if s.get('nav_in') else ''}; "
         f"{len(s['spots'])} boxed sections (read them on the contact sheet)\n") +
        "\n".join(f"   spot {k + 1}: {sp['text'][:160]}" for k, sp in enumerate(s["spots"]) if sp.get("text"))
        for s in cap["screens"])
    from_rec = any(not s.get("url") for s in cap["screens"])
    media_lines = "\n".join(f"{m['id']} ({'moving clip from the user’s screen recording' if m.get('clip_path') else 'user screenshot'}): "
                            f"{m['text'][:200]}" for m in cap["media"])
    story = "\n".join(f"- {s}" for s in plan.get("story") or [])
    prompt = f"""BRAND: {c.get('name')} — {c.get('tagline')} | {c.get('website')}
AUDIENCE: {c.get('audience')}
VIDEO: {plan['topic']} — {plan['angle']} (hook: {plan['hook']}) {plan.get('context', '')}
LENGTH: {L['label']}
PLANNED STORY:
{story or '- (choose)'}

FACTS ABOUT THE PRODUCT (use only these; never invent features or numbers):
{plan.get('site_summary', '')[:6000]}

SCREENS (full-screen captures{', in the order the user clicked through them in the recording' if from_rec else ''}; red numbered boxes
on the contact sheets = sections you can spotlight; read each screen on the sheets to know what it shows):
{screen_lines or '(none)'}

THE USER'S OWN MATERIAL (R…A… = moving clips from their screen recording – the real product in use, the best proof;
U… = their screenshots):
{media_lines or '(none)'}

ALREADY USED RECENTLY (do not repeat): {rotation.recent_creative_memory()}

Write a PRODUCT TOUR with {L['scenes']} scenes in customer-journey order (sign in / first look -> core features ->
how work gets done -> control & trust -> result).{' Keep the order of the recording (that is how the product is really used); skip screens that are empty, loading, duplicated or not interesting.' if from_rec else ''}
Scene types:
- "spot": one screen; 1-3 of its spots light up one after another, each with a short label.
  {{"type":"spot","screen":"P0S0","steps":[{{"spot":1,"label":"Your tools, connected"}}]}}
- "clip": one of the user's moving clips plays full screen. {{"type":"clip","block":"R0A1","label":"Ask in plain English"}}
- "shot": one of the user's screenshots. {{"type":"shot","block":"U0","label":"…"}}
Labels: 2-5 words, benefit-first, like "Live business KPIs", "Decisions waiting for you", "Set once, runs forever".
{'Use most of the R… clips, in their order, between the screens they belong to.' if any(m.get('clip_path') for m in cap['media']) else ''}
{'Every scene gets a "voice" line: natural spoken English, 1-2 short sentences (max 26 words) that add to the labels.' if voice else ''}
Also: intro {{"eyebrow" (2-3 words), "headline" (3-5 words), "accent" (2-4 words, the coloured 2nd line), "sub" (max 12 words){', "voice"' if voice else ''}}}
and outro {{"headline", "accent", "sub" (max 8 words), "cta" (2-4 words), "url"{', "voice"' if voice else ''}}},
captions for instagram/facebook/linkedin and 8-12 hashtags.

Return JSON: {{"title": "…", "intro": {{…}}, "scenes": [{{…}}], "outro": {{…}},
 "captions": {{"instagram": "…", "facebook": "…", "linkedin": "…"}}, "hashtags": ["#…"]}}"""
    data = llm.complete_json(prompt, SYSTEM, max_tokens=9000 if length == "full" else 5000, design=True,
                             images=sheets or None if llm.vision_available() else None)
    data = brandfix.fix_obj(data)
    screens = {s["id"].upper(): s for s in cap["screens"]}
    media = {m["id"].upper(): m for m in cap["media"]}
    scenes = []
    for sc in data.get("scenes") or []:
        t = sc.get("type")
        if t == "spot":
            s = screens.get(str(sc.get("screen", "")).upper().strip())
            if not s:
                continue
            steps = []
            for st in sc.get("steps") or []:
                try:
                    sp = s["spots"][int(st.get("spot")) - 1]
                except (TypeError, ValueError, IndexError):
                    continue
                steps.append({"title": str(st.get("label") or "")[:60], "rect": [sp["x"], sp["y"], sp["w"], sp["h"]]})
            sc["steps"] = steps[:3]
            sc["_block"] = _screen_block(s)
            sc["page_name"] = s["page"]
        elif t in ("clip", "shot"):
            m = media.get(str(sc.get("block", "")).upper().strip())
            if not m:
                continue
            t = "clip" if m.get("clip_path") else "shot"
            sc["_block"] = {k: v for k, v in m.items() if k not in ("user",)}
            sc["steps"] = [{"title": str(sc.get("label") or "")[:60], "rect": m.get("focus")}]
            sc["page_name"] = "Your recording" if t == "clip" else "Your screenshot"
        else:
            continue
        sc["type"] = t
        sc.setdefault("headline", (sc["steps"][0]["title"] if sc.get("steps") else sc.get("page_name", "")))
        scenes.append(sc)
    if not scenes:  # the AI gave nothing usable: every screen with its first spots, then the clips
        for s in cap["screens"]:
            scenes.append({"type": "spot", "page_name": s["page"], "headline": s["page"], "voice": "",
                           "steps": [{"title": _short(sp["text"]), "rect": [sp["x"], sp["y"], sp["w"], sp["h"]]}
                                     for sp in s["spots"][:2]], "_block": _screen_block(s)})
        for m in cap["media"]:
            t = "clip" if m.get("clip_path") else "shot"
            scenes.append({"type": t, "page_name": "Your recording", "headline": _short(m["text"]), "voice": "",
                           "steps": [{"title": _short(m["text"]), "rect": m.get("focus")}],
                           "_block": {k: v for k, v in m.items() if k != "user"}})
    data["scenes"] = scenes[:20]
    data["_style"] = "tour"
    data["_length"] = length
    return data


def _short(text: str) -> str:
    words = re.sub(r"\s+", " ", text or "").strip().split(" ")
    return " ".join(words[:4])


def _screen_block(s: dict) -> dict:
    return {"id": s["id"], "path": s["path"], "w": s["w"], "h": s["h"], "url": s["url"],
            "nav_in": s.get("nav_in"), "rec": s.get("rec"), "t": s.get("t"),
            "links": [{"href": ln["href"], "r": [round(ln["x"], 4), round(ln["y"], 4), round(ln["w"], 4), round(ln["h"], 4)]}
                      for ln in s.get("links") or []][:80]}


def nav_rect(scene: dict, next_scene: dict | None) -> list | None:
    """Where the cursor clicks to go to the next page (a link on this screen that points there)."""
    b, nb = scene.get("_block") or {}, (next_scene or {}).get("_block") or {}
    if nb.get("nav_in") and nb.get("rec") is not None and nb.get("rec") == b.get("rec"):
        return nb["nav_in"]  # recording: the sidebar item the person clicked to get to the next page
    if not nb.get("url") or nb.get("url") == b.get("url"):
        return None
    target = explorer._norm(nb["url"])
    for ln in b.get("links") or []:
        if explorer._norm(ln["href"]) == target:
            return ln["r"]
    return None


# ── timing ──────────────────────────────────────────────────────────────────
LEAD, STEP, TAIL, CLIP_LEAD = 0.9, 2.8, 1.3, 0.4


def base_seconds(sc: dict) -> float:
    t = sc.get("type")
    if t == "spot":
        return LEAD + STEP * max(1, len(sc.get("steps") or [])) + TAIL
    if t == "clip":
        return CLIP_LEAD + float((sc.get("_clip") or {}).get("n", 0)) / recording.FPS + 0.5 \
            if sc.get("_clip") else CLIP_LEAD + float((sc.get("_block") or {}).get("clip_s") or 6.5) + 0.5
    return 4.6


# ── scenes ──────────────────────────────────────────────────────────────────
def _e(s) -> str:
    import html
    return html.escape(str(s or ""))


_CURSOR = ("<svg viewBox='0 0 24 24' width='34' height='34'><path d='M4 2l16 9.5-7 1.6L9.6 20z' fill='#111' "
           "stroke='#fff' stroke-width='1.6' stroke-linejoin='round'/></svg>")


def _base_css(theme: dict, size: tuple[int, int]) -> str:
    w, h = size
    acc = theme["accent"]
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@500;600;700;800&display=swap">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden;background:#0b1020;font-family:Inter,'Segoe UI',Arial,sans-serif;
 -webkit-font-smoothing:antialiased}}
#bgfill{{position:absolute;inset:-60px;background-size:cover;background-position:center;filter:blur(40px) brightness(.55)}}
#cam{{position:absolute;left:0;top:0;transform-origin:0 0;will-change:transform,filter}}
#cam img{{position:absolute;left:0;top:0;width:100%;height:100%;display:block}}
#blur{{filter:blur(9px) brightness(.78) saturate(.9);opacity:0}}
#sharp{{position:absolute;inset:0;clip-path:inset(0 0 0 0);opacity:0}}
#glow{{position:absolute;border-radius:12px;border:2.5px solid {acc};opacity:0;
 box-shadow:0 0 0 6px {acc}26,0 18px 50px rgba(0,0,0,.35),0 0 60px {acc}66}}
#pill{{position:absolute;display:flex;align-items:center;gap:10px;white-space:nowrap;padding:8px 18px 8px 8px;border-radius:99px;
 background:linear-gradient(90deg,{acc},{theme['accent2']});color:{theme.get('btn_text') or '#fff'};font-weight:700;font-size:{30 if size[1] > size[0] else 24}px;opacity:0;
 box-shadow:0 10px 30px {acc}66;transform-origin:center bottom}}
#pill i{{font-style:normal;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:#fff;color:{acc};font-size:17px}}
#cur{{position:absolute;left:0;top:0;width:34px;height:34px;filter:drop-shadow(0 3px 6px rgba(0,0,0,.35));opacity:0}}
#ring{{position:absolute;width:56px;height:56px;margin:-28px 0 0 -28px;border-radius:50%;border:3px solid {acc};opacity:0}}
.logo{{position:absolute;right:26px;top:22px;height:34px;opacity:.9}}
</style></head>"""


def _timeline_js(spec: dict) -> str:
    """window.__render(t): camera, blur, spotlight cut-out, label, cursor – all computed from t (frame-exact)."""
    return """<script>(()=>{
const S=%s;
const $=id=>document.getElementById(id);const cam=$('cam'),blur=$('blur'),sharp=$('sharp'),glow=$('glow'),pill=$('pill'),
 num=$('num'),lab=$('lab'),cur=$('cur'),ring=$('ring');
const ease=p=>p<0?0:p>1?1:(p<.5?4*p*p*p:1-Math.pow(-2*p+2,3)/2);
const lerp=(a,b,k)=>a+(b-a)*k;const mix=(A,B,k)=>A.map((v,i)=>lerp(v,B[i],k));
const W=S.W,H=S.H,SW=S.SW,SH=S.SH;
function camFor(r){ // scale + offset that frames rect r (fractions of the screen)
  const s0=S.fit;if(!r)return[s0,(W-SW*s0)/2,(H-SH*s0)/2];
  let s=S.vert?Math.min(S.zmax,Math.max(W/SW,(W*0.96)/(r[2]*SW))):s0*S.zl;   // vertical: the whole box fits the width
  const cx=(r[0]+r[2]/2)*SW,cy=(r[1]+r[3]/2)*SH;let ox=W/2-cx*s,oy=H/2-cy*s;
  if(!S.vert){ox=lerp((W-SW*s)/2,ox,0.45);oy=lerp((H-SH*s)/2,oy,0.45);}
  ox=Math.min(0,Math.max(W-SW*s,ox));
  if(SH*s>=H)oy=Math.min(0,Math.max(H-SH*s,oy));else oy=(H-SH*s)/2;
  if(SW*s<W)ox=(W-SW*s)/2;
  return[s,ox,oy];}
const steps=S.steps;
function stateAt(t){
  let i=-1;for(let k=0;k<steps.length;k++)if(t>=steps[k].t0)i=k;
  const fin=t>=S.dur-S.tail;
  if(i<0||fin||!steps[i].r){ // no spotlight: whole screen
    const prev=i>=0&&steps[i].r?steps[i].r:null;
    const k=fin&&prev?ease((t-(S.dur-S.tail))/.5):1;
    return{r:prev,on:prev?1-k:0,cam:prev?mix(camFor(prev),camFor(null),k):camFor(null),i:fin?-1:i,lk:0};}
  const st=steps[i],k=ease((t-st.t0)/.6),pr=i>0&&steps[i-1].r?steps[i-1].r:null;
  const r=pr?mix(pr,st.r,k):st.r;
  const on=pr?1:k;
  return{r,on,cam:mix(pr?camFor(pr):camFor(null),camFor(st.r),k),i,lk:ease((t-st.t0-.45)/.35)};}
const pad=[0.006,0.009];
window.__render=t=>{
  const st=stateAt(t);const [s,ox,oy]=st.cam;
  const gb=Math.max(0,1-t/.45)*12+Math.max(0,(t-(S.dur-.3))/.3)*10;
  cam.style.transform=`translate(${ox}px,${oy}px) scale(${s})`;cam.style.filter=gb>0.05?`blur(${gb}px)`:'none';
  blur.style.opacity=st.on;sharp.style.opacity=st.on>0?1:0;
  if(st.r){const r=[st.r[0]-pad[0],st.r[1]-pad[1],st.r[2]+2*pad[0],st.r[3]+2*pad[1]];
    sharp.style.clipPath=`inset(${r[1]*100}%% ${(1-r[0]-r[2])*100}%% ${(1-r[1]-r[3])*100}%% ${r[0]*100}%% round 12px)`;
    const lift=1+0.018*st.on;sharp.style.transformOrigin=`${(r[0]+r[2]/2)*100}%% ${(r[1]+r[3]/2)*100}%%`;sharp.style.transform=`scale(${lift})`;
    const gx=(r[0]+r[2]/2)*SW,gy=(r[1]+r[3]/2)*SH,gw=r[2]*SW*lift,gh=r[3]*SH*lift;
    glow.style.left=(gx-gw/2)+'px';glow.style.top=(gy-gh/2)+'px';glow.style.width=gw+'px';glow.style.height=gh+'px';glow.style.opacity=st.on;
    // label above the box (screen px of the final video, so it stays the same size whatever the zoom)
    const pw=pill.offsetWidth||200,ph=pill.offsetHeight||46;
    const px=Math.min(W-pw/2-16,Math.max(pw/2+16,ox+gx*s));let py=oy+(gy-gh/2)*s-16,below=false;
    if(py-ph<12){py=Math.min(H-ph-12,oy+(gy+gh/2)*s+16);below=true;}   // no room above the box: put the label under it
    if(below&&py+ph>H-12){py=Math.max(12+ph,oy+(gy-gh/2)*s+ph+16);below=false;}  // nor under it: inside, at its top
    pill.style.left=px+'px';pill.style.top=py+'px';
    pill.style.transform=`translate(-50%%,${below?'0':'-100%%'}) scale(${0.85+0.15*st.lk})`;pill.style.opacity=st.i>=0&&steps[st.i].label?st.lk*st.on:0;
    if(st.i>=0){num.textContent=String(st.i+1);lab.textContent=steps[st.i].label;}
  }else{glow.style.opacity=0;pill.style.opacity=0;}
  // cursor: glides between points (screen fractions), clicks at the end when it goes to the next page
  const P=S.cursor;let cx=P[0].p[0],cy=P[0].p[1];
  for(let k=1;k<P.length;k++){if(t>=P[k-1].t){const q=ease((t-P[k-1].t)/Math.max(.01,P[k].t-P[k-1].t));
    cx=lerp(P[k-1].p[0],P[k].p[0],q);cy=lerp(P[k-1].p[1],P[k].p[1],q);}}
  const X=ox+cx*SW*s,Y=oy+cy*SH*s;cur.style.transform=`translate(${X}px,${Y}px)`;
  cur.style.opacity=S.showCursor?Math.min(1,t/.5)*(S.click?1:Math.max(0,Math.min(1,(S.dur-t-.2)/.4))):0;
  if(S.click){const ck=(t-S.click)/.45;ring.style.left=X+'px';ring.style.top=Y+'px';
    ring.style.opacity=ck>0&&ck<1?1-ck:0;ring.style.transform=`scale(${0.4+ck*1.3})`;}
  };
window.__render(0);})();</script>""" % json.dumps(spec)


def _layout(size: tuple[int, int], sw: int, sh: int) -> dict:
    w, h = size
    vert = h > w
    fit = min(w / sw, h / sh) if not vert else w / sw * 1.3   # vertical: a little cropped at the sides, bigger
    return {"W": w, "H": h, "SW": sw, "SH": sh, "vert": vert, "fit": fit, "zl": 1.07, "zmax": fit * 2.4}


def _steps_timing(n: int, dur: float, lead: float, tail: float) -> list[float]:
    span = max(0.1, dur - lead - tail)
    return [lead + span * k / max(1, n) for k in range(n)]


def _cursor_path(steps: list[dict], dur: float, nav: list | None, start: tuple[float, float] = (0.86, 0.9)) -> tuple[list, float | None]:
    pts = [{"t": 0, "p": list(start)}]
    for st in steps:
        r = st.get("r")
        if not r:
            continue
        pts.append({"t": st["t0"] + 0.15, "p": [r[0] + r[2] * 0.62, r[1] + r[3] * 0.58]})
        pts.append({"t": st["t0"] + 1.6, "p": [r[0] + r[2] * 0.7, r[1] + r[3] * 0.48]})
    click = None
    if nav:
        at = dur - TAIL + 0.35
        pts.append({"t": at, "p": [nav[0] + nav[2] * 0.5, nav[1] + nav[3] * 0.55]})
        click = at + 0.5
        pts.append({"t": dur, "p": [nav[0] + nav[2] * 0.5, nav[1] + nav[3] * 0.55]})
    pts.sort(key=lambda p: p["t"])
    return pts, click


def scene_spot(d: dict, theme: dict, size: tuple[int, int], dur: float, logo: str | None, nav: list | None) -> str:
    b = d["_block"]
    img = Path(b["path"]).name
    lay = _layout(size, b["w"], b["h"])
    raw = [s for s in d.get("steps") or [] if s.get("rect")]
    t0s = _steps_timing(len(raw), dur, LEAD, TAIL)
    steps = [{"r": s["rect"], "label": s.get("title", ""), "t0": t0s[k]} for k, s in enumerate(raw)]
    cursor, click = _cursor_path(steps, dur, nav)
    spec = {**lay, "dur": dur, "tail": TAIL, "steps": steps, "cursor": cursor, "click": click, "showCursor": True}
    return _page(theme, size, img, lay, spec, logo)


def scene_media(d: dict, theme: dict, size: tuple[int, int], dur: float, logo: str | None) -> str:
    """A user's clip (frames swapped by __clipT) or screenshot, full screen, spotlight on its action area."""
    b = d["_block"]
    clip = d.get("_clip")
    lay = _layout(size, b["w"], b["h"])
    st = (d.get("steps") or [{}])[0]
    rect = st.get("rect")
    steps = [{"r": rect, "label": st.get("title", ""), "t0": 1.0 if rect else CLIP_LEAD}]
    if not rect:  # no action area: just the label over the full screen
        steps = []
    spec = {**lay, "dur": dur, "tail": 0.8, "steps": steps, "cursor": [{"t": 0, "p": [2, 2]}], "click": None,
            "showCursor": False}
    first = f"{clip['dir']}/f0001.jpg" if clip else Path(b["path"]).name
    doc = _page(theme, size, first, lay, spec, logo, label=None if rect else st.get("title", ""))
    if clip:
        js = f"""<script>(()=>{{const ims=[...document.querySelectorAll('#cam img')];let cur=1;
window.__clip=t=>{{const i=Math.min({clip['n']},Math.max(1,1+Math.floor((t-{CLIP_LEAD})*{clip['fps']})));
if(i===cur)return null;cur=i;const src='{clip['dir']}/f'+String(i).padStart(4,'0')+'.jpg';
return Promise.all(ims.map(m=>{{m.src=src;return m.decode().catch(()=>null)}}));}};}})()</script>"""
        doc = doc.replace("</body>", js + "</body>")
    return doc


def _page(theme, size, img, lay, spec, logo, label: str | None = None) -> str:
    w, h = size
    top = ""
    if label:  # a full-screen label (no spotlight area)
        top = (f'<div style="position:absolute;left:50%;top:{int(h * (0.08 if h > w else 0.06))}px;transform:translateX(-50%);'
               f'display:flex;align-items:center;gap:10px;padding:10px 22px;border-radius:99px;'
               f'background:linear-gradient(90deg,{theme["accent"]},{theme["accent2"]});color:#fff;font-weight:700;font-size:24px;'
               f'box-shadow:0 10px 30px {theme["accent"]}66;animation:none">{_e(label)}</div>')
    return (_base_css(theme, size) +
            f"""<body><div id="bgfill" style="background-image:url('{img}')"></div>
<div id="cam" style="width:{lay['SW']}px;height:{lay['SH']}px">
 <img src="{img}"><img id="blur" src="{img}"><div id="sharp"><img src="{img}"></div><div id="glow"></div>
</div>
<div id="pill"><i id="num">1</i><span id="lab"></span></div>
<div id="ring"></div><div id="cur">{_CURSOR}</div>{top}
{f'<img class="logo" src="{logo}">' if logo else ''}
{_timeline_js(spec)}</body></html>""")


def _rgb(hx: str) -> tuple[int, int, int]:
    hx = str(hx).lstrip("#")[:6]
    try:
        return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (37, 99, 235)


def _dark_bg(theme: dict) -> str:
    """The title cards are dark: the brand's own dark background, else its accent colour taken almost to black."""
    r, g, b = _rgb(theme.get("bg", "#ffffff"))
    if 0.2126 * r + 0.7152 * g + 0.0722 * b < 60:
        return theme["bg"]
    ar, ag, ab = _rgb(theme["accent"])
    k = 0.1
    return "#%02x%02x%02x" % (int(ar * k + 3), int(ag * k + 5), int(ab * k + 14))


def scene_title(d: dict, theme: dict, size: tuple[int, int], dur: float, logo: str | None, outro: bool = False) -> str:
    """Intro / outro card: dark, centred, glowing in the brand colour – like the opening of a launch video."""
    w, h = size
    vert = h > w
    acc, acc2 = theme["accent"], theme["accent2"]
    btn_text = theme.get("btn_text") or "#fff"
    c = company()
    brand = (f'<img src="{logo}" style="height:{56 if vert else 48}px">' if logo else
             f'<b style="font-size:{30 if vert else 26}px;letter-spacing:.04em">{_e(c.get("name", ""))}</b>')
    hs = 92 if vert else 76
    cta = (f'<div class="t" style="animation-delay:1.1s;margin-top:{30 if vert else 22}px;display:inline-flex;align-items:center;gap:12px;'
           f'padding:{20 if vert else 16}px {44 if vert else 36}px;border-radius:99px;background:linear-gradient(90deg,{acc},{acc2});'
           f'color:{btn_text};font-weight:700;font-size:{30 if vert else 26}px;box-shadow:0 16px 50px {acc}66">{_e(d.get("cta"))} →</div>'
           if outro and d.get("cta") else "")
    eyebrow = (f'<div class="t" style="animation-delay:.15s;letter-spacing:.3em;font-size:{20 if vert else 16}px;'
               f'font-weight:700;color:#ffffffaa;text-transform:uppercase">{_e(d.get("eyebrow"))}</div>' if d.get("eyebrow") else "")
    brand_row = f'<div class="t" style="animation-delay:{.9 if not outro else .1}s;margin-top:{40 if vert else 30}px">{brand}</div>'
    head_block = f"""{brand_row if outro else ''}{eyebrow}
 <h1 class="t" style="animation-delay:.3s;font-size:{hs}px;line-height:1.05;font-weight:800;letter-spacing:-.03em;margin-top:16px">{_e(d.get('headline'))}<br>
 <span style="background:linear-gradient(90deg,{acc},{acc2});-webkit-background-clip:text;background-clip:text;color:transparent">{_e(d.get('accent'))}</span></h1>
 <div class="t" style="animation-delay:.55s;width:{90 if vert else 70}px;height:3px;border-radius:3px;background:{acc};margin:{30 if vert else 24}px auto 0"></div>
 <p class="t" style="animation-delay:.7s;margin-top:{26 if vert else 20}px;font-size:{32 if vert else 26}px;color:#ffffffcc">{_e(d.get('sub'))}</p>
 {cta}{'' if outro else brand_row}"""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@500;600;700;800&display=swap">
<style>*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{w}px;height:{h}px;overflow:hidden;font-family:Inter,'Segoe UI',Arial,sans-serif;color:#fff;
 background:radial-gradient(ellipse 70% 60% at 50% 18%,{acc}88 0%,transparent 70%),
 radial-gradient(ellipse 50% 40% at 85% 95%,{acc2}55 0%,transparent 70%),{_dark_bg(theme)}}}
@keyframes up{{from{{opacity:0;transform:translateY(22px);filter:blur(6px)}}to{{opacity:1;transform:none;filter:none}}}}
@keyframes out{{to{{opacity:0;filter:blur(8px)}}}}
.t{{animation:up .9s cubic-bezier(.2,.8,.2,1) both}}
.wrap{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;
 padding:0 {70 if vert else 160}px;animation:out .4s ease-in both;animation-delay:{max(0.1, dur - .4):.2f}s}}
</style></head><body><div class="wrap">{head_block}</div></body></html>"""


def estimate(sc: dict) -> float:
    return base_seconds(sc)


__all__ = ["capture", "storyboard", "scene_spot", "scene_media", "scene_title", "nav_rect", "base_seconds"]
