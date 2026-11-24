# Digital Marketing Agent

Creates a **video or image post every day** for your company and publishes it to **Instagram, Facebook and LinkedIn** after you approve it.

- **Video days**: the agent reads your website, writes a short viral-style script, captures your website pages in high resolution (mobile view, smooth scroll, the feature highlighted), adds an AI voice-over and subtitles, plus a hook card and a call-to-action card. The output is a 9:16 MP4 ready for Reels.
- **Post days**: a branded 1080×1350 image plus a caption for each platform. The topic comes from **festivals** (Indian holidays and your special days), **your events**, **market trends** (Google Trends and industry news), or **website features**.
- **Approval**: tomorrow's content is generated every evening. You review, edit or approve it in the dashboard (and optionally get a Telegram alert). It is published at your posting time.

```
 schedule ─► planner (festival / event / trend / website) ─► generator ─► dashboard approval ─► publish
                         ▲                                     │ video: script → TTS → page capture → ffmpeg
          website crawl, Google Trends, holidays               │ post : copy → branded image
```

## 1. Setup (Windows / PyCharm)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```
Install **ffmpeg** and make sure it is on your PATH (`winget install Gyan.FFmpeg`, then reopen the terminal and run `ffmpeg -version`).

```bash
copy .env.example .env      # add ANTHROPIC_API_KEY (or GROQ_API_KEY + LLM_PROVIDER=groq)
```
Edit **`config/settings.yaml`**: company name, **website URL**, audience, brand colours, weekly schedule, and posting time.
Optional: put `assets/logo.png` there, add royalty-free `.mp3` tracks to `assets/music/`, and add your events to `config/events.yaml`.

## 2. Try it

```bash
python cli.py research                      # what the agent sees: site, trends, next 7 days
python cli.py generate --kind post          # make a post now
python cli.py generate --kind video         # make a video now (takes 1–3 min)
python cli.py serve                         # dashboard + scheduler → http://localhost:8000  (admin / change-me)
```
Platforms without credentials run in **dry-run** mode. Content is generated, but nothing is posted.

## 1a. Dashboard (React)

Open <http://localhost:8000> and log in with `DASHBOARD_USER` / `DASHBOARD_PASSWORD` from `.env`.

- **Content queue:** every post and video as a card, with a strip showing the week ahead.
  - Filter by Needs review, Generating, Approved, Published, or Rejected/failed; filter by type; search.
  - One-click Approve or Reject on a card, **Stop** on anything still generating, **Delete** on rejected/failed items (or **Delete all** in that tab).
  - **Generate now** always makes a new post or video. The automatic runs (18:00 and the start-up catch-up) make at most one item per day.
- **Review page:**
  - Post preview, or a video player with a 16:9 / 9:16 switch, plus downloads.
  - Video storyboard.
  - Platform toggles.
  - A caption editor per platform, with a character counter and a "preview with hashtags" view.
  - Hashtag chips (LinkedIn uses the first 5).
  - Approve, Reject, Regenerate, Publish now, Stop (while generating) and Delete (rejected/failed).
  - **AI quality check:** every new post/video is checked before it reaches you – size, blank frames, video length and sound, caption limits, plus the AI looking at the poster or video frames with the captions (score out of 10 and a list of problems). Use **Check again** any time.
  - While an item is generating, you see a live progress bar and the current step, e.g. "Rendering 9:16 video – 64%".
- **Edit without regenerating:**
  - **Posts – Edit text:** change any text on the poster; it re-renders in ~10 s with the same design (new file version, old one removed).
  - **Videos – Edit scenes:** change headlines and voice-over per scene, let the AI rewrite a scene, or pick another voice; the video is rebuilt (on your PC when `VIDEO_RENDERER=pc`). The previous version stays until the new one is ready.
- **How it will look:** previews of the post as an Instagram, LinkedIn and Facebook post, cut where each app shows "… more".
- **When it goes out:** move an item to another day or give it its own posting time (item page, or drag its thumbnail in the calendar). Approved items whose day passed are marked **missed** and wait for a new date instead of going out late.
- **Select & bulk actions:** select several cards to approve, reject, delete, restore or delete for good in one go.
- **Bin:** deleting moves items to the Bin for 7 days (Undo right away, or Restore later); then they and their files are removed for good.
- **Pause the agent:** sidebar switch (phone: top-bar button). Stops the evening preparation and automatic posting – until you resume or until a date. Generate now / Publish now keep working.
- **Results:** likes, comments, shares, reach, views and clicks fetched from each platform every 6 hours after posting; totals, best posts, and averages by format, product, weekday and source. Every Monday the AI writes "what worked best" and the planner leans towards it.
- **Setup wizard:** first-time setup (company → logo → products → schedule → connections). "Read my website" fills in the company details and suggests products. Opens by itself until finished; Settings → **Setup wizard** runs it again (e.g. for a new brand or client).
- **Install as an app (PWA):** on a phone, open the site and choose **Install** (Android/Chrome) or **Share → Add to Home Screen** (iPhone). It opens full-screen with its own icon; updates arrive with every deploy.
- **Create from URL:** paste any link, choose video or post, add an optional focus, and watch it being made.
- **Schedule & calendar:**
  - Weekly plan: Video, Post or Off for each day.
  - When content is prepared and when it's published.
  - The order of post topics (festivals, your events, trends, products).
  - Festival greetings on days off, and how early to post festival wishes.
  - A month calendar with planned types, festivals, your events and the content already made (click a thumbnail to open it).
  - Add, edit or delete your events. The agent announces them on the day or a few days before.
- **Settings:**
  - **Company & brand:** name, tagline, website, audience, tone, call to action, colours, and logo upload with a light/dark preview.
  - **Products:** add, edit, reorder or remove the products the agent rotates through.
  - **Content style:** video sizes, length, voice-over on/off, voice picker with "Listen", background music library (upload, play, delete), and video looks. For posts: AI review on/off, which formats and looks to rotate.
  - **Status & health:** the same health check as `check_agent.bat` (quick or full), publishing connections, AI engine and the next scheduler runs.

Changes made in the dashboard are written to `config/settings.yaml` and `config/events.yaml`, and your comments in those files are kept. A new preparation time takes effect immediately; you don't need to restart.

The old server-rendered dashboard is still at `/classic/` and works without Node.

**Frontend code** (`frontend/`, Vite + React + TypeScript + Tailwind):
```bash
cd frontend
npm install
npm run dev      # hot reload on http://localhost:5173 (agent must be running on :8000)
npm run build    # -> frontend/dist, served by the agent at http://localhost:8000 (restart the agent)
```
API used by the UI (`app/api.py`, Bearer token from `POST /api/login`, or HTTP Basic for scripts/n8n):
- `GET /api/meta`
- `GET /api/items?status=&kind=&q=`
- `GET|PATCH /api/items/{id}`
- `POST /api/items/{id}/approve|reject|regenerate|publish`
- `POST /api/from-url`
- `POST /api/generate`

## 1b. Premium creative engine (styled after the Krypsos sample posts & videos)

**Posts.** An AI art director (`ANTHROPIC_DESIGN_MODEL`) designs every post as an HTML/CSS poster (1080×1350). Chromium renders it, the agent checks for clipped or overflowing text and broken images, and the AI looks at the result and fixes any problems before it goes for approval.
- **13 formats**, including: problem headline + mock invoice + numbered steps (like *"No more manual invoice entry"*), real product screenshot with callouts, before/after, myth vs fact, checklist, chat demo, expectation vs reality humour, big statement, poll question, trend take, tip, festive art (like the Diwali mandala) and event announcement.
- **8 themes**, including: cream editorial, midnight violet, dark tech, amber noir, navy & gold, clean white, mint and sunset.
- **No repeats.** Format, theme and product rotate least-recently-used, so the same format never appears within 4 posts and the same theme never twice in a row. The AI also sees the last 15 headlines, hooks and jokes and must not reuse them. You can limit the formats and themes in `settings.yaml → post`.

**Videos.** These are styled like the DineOS and clinic videos.
- **Source material.** The agent opens the product page (`products:` in settings) and captures each UI mock-up or dashboard as a crisp image. The AI looks at all of them and writes a storyboard.
- **Structure.**
  1. Intro title.
  2. 4–7 feature scenes: an eyebrow label, a headline with accent-coloured words and 3 icon bullets, with the real UI in a window frame and floating stat badges that count up. Badge numbers must exist in the UI.
  3. A grid of everything in one place.
  4. An outro with the logo, a CTA button and the URL.
- **Output.** Scenes are rendered frame by frame (30 fps) in two versions: **16:9 for LinkedIn** and **9:16 for Instagram/Facebook Reels**.
- **Audio.** There's an optional AI voice-over. Music from `assets/music/*.mp3` is ducked under the voice.
- **Looks.** The 5 looks (amber noir, navy & gold, emerald, violet, paper) rotate.
- **Render time.** About 3 seconds of rendering per second of video, per format, so a 60-second video takes roughly 5–6 minutes in the background.

**Products.** The agent features the least recently used product next: Restaurant POS, Clinic, Super Agent, AP/AR, Support Bot, Lead Qualifier and Workflows. Edit the list in `settings.yaml`.

**Logo.** The logo is captured automatically from krypsos.tech on the first run and saved to `assets/logo.png`. Replace it with your original transparent PNG for the best result; the agent makes the light and dark versions itself.

**Festival greetings.** Approved festivals get a dedicated greeting design (logo, quote with one highlighted word,
big gold script "Happy <Festival>", tagline) on either a photo background or a hand-drawn illustrated scene
(lanterns & diyas for Diwali, sun & kolam for Pongal, tree & snow for Christmas, crescent & lanterns for Eid,
tricolour for Independence/Republic Day, fireworks for New Year …). Videos made on a festival day open with a short
animated greeting. Typing e.g. "Diwali greeting" in Generate now makes one any day.

**Optional AI photos.** `IMAGE_PROVIDER=pollinations` + `POLLINATIONS_API_KEY` (free key from
enter.pollinations.ai), or `gemini` / `openai` with their keys, gives festival posts a photo background (checked by
the AI; it falls back to the illustrated scene if the photo has text or looks wrong) and allows photo-style memes.
Without it, festival posts use the illustrated scenes and other posts are drawn with CSS/SVG.

If the premium engine ever fails, a simpler version is made so the day isn't empty, and a warning appears on the item.

## 2a. Video or post for ANY website

Give the agent any link and it creates an explainer video (or a post) for that site:
```bash
python cli.py from-url https://anywebsite.com
python cli.py from-url https://anywebsite.com --kind post
python cli.py from-url https://anywebsite.com --notes "explain the booking feature for restaurant owners"
```
You can also use the **🎬 Create from any website** box in the dashboard, or call `POST /api/from-url` with `{"url": "...", "kind": "video", "notes": ""}`.

Video options on that page:
- **How long:** *Short* (45–60 s highlight), *Full walkthrough* (2–4 min: a scrolling tour of every main page, screen
  close-ups and an animated "how it works" scene), or *Series* (one short Reel per main page, dated one per day, up to 5).
- **Show me the outline first** (on by default): the agent stops after writing the scenes. On the item page you can
  reorder, remove and rename scenes, edit the voice-over and pick the voice, then press **Make video**.
- **Your screenshots** (optional, up to 8, drag & drop or Ctrl+V): screens the agent can't reach itself, such as inside
  your app after login. Each one becomes a scene with your caption; for a post, it is used as the screen in the design.

What the agent does with the link:
- **Explores the whole site** (not just the front page): sitemap, top menu, footer and links – up to 40 pages
  (25 for JavaScript apps). Login, legal, cart pages and single blog posts are skipped. The AI sorts every page
  (product, feature, how it works, pricing, case study …) and notes its features, workflow steps, benefits and real
  numbers. This is remembered for a week, so the next post/video about the same site starts straight away.
- **Wakes sleeping sites**: free hosts (Render, Railway …) show a "waking up" page first – the agent waits and
  retries for up to ~2.5 minutes, and tells you clearly if the site never answers.
- **Local addresses** (`localhost:3000`, `192.168.x.x`, `*.local`): only your PC can open them, so these jobs –
  posts too – go to your PC (`run_video_worker.bat` must be running and the site started).
- **Reads the site.** It handles plain websites and JavaScript apps (React, Vue, Angular), finds the main pages and skips login, privacy and cart pages.
- **Detects the brand.** It works out the name, tagline, audience and tone, and takes the brand colours from the site's header and buttons. The cards and captions use that brand, not yours.
- **Builds the content.** It picks the 2–4 pages that best show the product, then writes, captures, voices and subtitles the video.

The result goes into the same approval queue. **Regenerate** rebuilds it from the same link.

If a site needs a login, run `python cli.py login --url https://app.thatsite.com` once. Sessions for multiple sites are kept side by side.

## 2b. Go live on your PC (5 steps)

1. **Install Python 3.11+** from python.org. During install, tick **"Add python.exe to PATH"**.
2. **Double-click `setup_windows.bat`.** It creates `.venv`, installs the packages, the Chromium browser and ffmpeg, and creates `.env`. This takes about 5 minutes.
3. **Open `.env` in Notepad** and fill in:
   - `ANTHROPIC_API_KEY=sk-ant-...`
   - `DASHBOARD_PASSWORD=` (any password you like)

   Leave the Meta/LinkedIn keys empty for now, so publishing stays in dry-run.
4. **Optional but recommended:**
   - Put your transparent logo at `assets/logo.png`.
   - Add 3–5 royalty-free `.mp3` tracks to `assets/music/` (for example from the YouTube Audio Library).
5. **Double-click `check_agent.bat`.** Every line should be ✅. ⚠️ lines are optional. If ffmpeg shows ❌ right after setup, close the window and run the check again.

**First real run:** open a terminal in this folder and run:
```bat
.venv\Scripts\activate
python cli.py generate --kind post
python cli.py generate --kind video
```

**Go live:**
- Double-click **`run_agent.bat`** and open <http://localhost:8000> (user `admin` and your password).
- Double-click **`install_autostart.bat`** once, so the agent starts whenever you log in to Windows.

What happens each day:
- At **18:00** the agent creates tomorrow's video or post. It shows up in the dashboard as *pending approval*.
- Click **Approve**. At **10:00** on that day it is "published" in dry-run mode: the status becomes `dry_run` and nothing is posted.
- If the PC was off at 18:00, the agent makes any missing content for today and tomorrow when it next starts.
- The PC must be on (not asleep) for the agent to run. In Windows power settings, set sleep to "Never" while plugged in, or leave the PC on in the evening.

**When you're ready to really post:** add the Meta/LinkedIn keys (section 4) and set `PUBLIC_BASE_URL` to a public address. Instagram fetches media from a URL, so you'll need either a tunnel (cloudflared/ngrok) or a hosted server.

## 2c. Festivals & special days need your OK
**Schedule → Festivals & special days** lists the next 90 days. Nothing festive is posted unless it says **Will post**.
- **Festivals** come from the Indian holidays calendar.
  - Diwali, Pongal, Christmas, Independence Day, Republic Day, New Year and Gandhi Jayanti start as *always post*.
  - Everything else waits for you: ✅ Post or ❌ Skip.
- **Special days** (Engineers' Day, Science Day…) work the same way. Days you add yourself are approved automatically and repeat every year.
- **AI suggestions:** "Suggest days for my products" proposes fitting days, e.g. World Health Day for Clinic. They're only posted if you accept them.
- **Your events** are approved by default. Pause one to stop it being announced.
- **Options per day (⌄):**
  - Remember every year: Always / Never / Ask me.
  - When: on the day, 1 or 2 days early.
  - A note for the AI, e.g. "mention our Pongal offer".
- **Reminders:** undecided days in the next week show as a banner on the Content queue, plus a Telegram reminder if it's set up.

Undecided or skipped days get the normal product/trend post. The calendar shows ✅ will post, ⏳ waiting, ✕ skipped.

## 3. Weekly schedule

Set this in the dashboard (**Weekly schedule**) or in `settings.yaml`:
```yaml
schedule: { monday: video, tuesday: post, wednesday: post, thursday: video, friday: post, saturday: post, sunday: none }
generate_time: "18:00"   # prepare tomorrow's content and send it for approval
publish_time:  "10:00"   # post approved content
```
With `always_post_on_festivals: true`, a festival on a `none` day still gets a greeting post.

## 4. Connect the social accounts

**Easiest: in the dashboard, go to Settings → Connections.** For each platform:
1. **Set up your app (one time).** Paste the Meta App ID/secret or the LinkedIn Client ID/secret. The dialog shows the exact steps and the **redirect URL** to copy into the app.
2. **Connect with Facebook / LinkedIn.** Log in, pick your company Page, done.
   - Instagram is connected automatically when the Facebook Page has an Instagram Business account linked.
   - LinkedIn access renews itself when LinkedIn provides a refresh token. Otherwise the page warns you 10 days before it expires.
3. **Test connection** checks that everything is ready to post.

Tokens are stored encrypted in the database. "Enter tokens manually" is there if you already have tokens. The `.env` values below also still work as a fallback.
`PUBLIC_BASE_URL` must be your public address (e.g. the Render URL) for the login redirect and for Instagram.

The manual way (tokens in `.env`) and what each app needs:

### Instagram only (no Facebook Page needed)
New Meta apps (since late Oct 2026) use **API setup with Unified login**: no Facebook Page, but a (free) business
portfolio, and a system-user token that never expires.
1. developers.facebook.com → **Create app** → use case **Manage messaging & content on Instagram**.
2. **Use cases → Instagram → Customize → API setup with Unified login** → connect a business portfolio.
3. **1. Configure your app → Create new configuration**: System-user access token, expiry Never, asset = your
   Instagram account, permissions `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`.
4. **2. Generate access tokens** → copy the token → dashboard **Settings → Connections → Instagram → Paste token**.
   (Or enter App ID + secret + Configuration ID under "Set up" and use **Connect with Instagram**; then add
   `https://<your-app>/api/connections/instagram/callback` under Facebook Login for Business → Valid OAuth Redirect URIs.)
Older apps with "API setup with Instagram login" still work: Instagram App ID/secret, no Configuration ID.
If an Instagram account is connected here, Instagram posts go through it.

### Facebook + Instagram (one Meta app covers both)
1. Convert Instagram to a **Business/Creator account** and link it to your **Facebook Page** (Instagram → Settings → Account type / Linked Page).
2. At <https://developers.facebook.com>, create an app (type **Business**) and add the **Facebook Login for Business** and **Instagram Graph API** products.
3. In the **Graph API Explorer**, generate a *User* token with these permissions: `pages_show_list, pages_read_engagement, pages_manage_posts, instagram_basic, instagram_content_publish, business_management`.
4. Exchange it for a long-lived token, then call `GET /me/accounts`. That returns your **Page id** and a **Page access token** that doesn't expire.
5. Call `GET /{page-id}?fields=instagram_business_account` to get **META_IG_USER_ID**.
6. Fill in `META_PAGE_ID`, `META_PAGE_ACCESS_TOKEN` and `META_IG_USER_ID` in `.env`.
7. To post for real outside development mode, the app needs **App Review** for the permissions above (or use it as an app admin while it's in development).

> Instagram downloads media from a **public URL**. Set `PUBLIC_BASE_URL` to your deployed address (for example `https://dma.onrender.com`). For local testing you can use an ngrok/cloudflared tunnel.

### LinkedIn Company Page
1. At <https://www.linkedin.com/developers>, create an app and link it to your **Company Page** (a page admin must verify it).
2. Request the **Community Management API** product. You need the `w_organization_social` scope.
3. Generate an access token with the OAuth tool (as a page admin) → `LINKEDIN_ACCESS_TOKEN`. Tokens last 60 days, so set a reminder to renew.
4. `LINKEDIN_ORG_ID` is the number in your page's admin URL (`linkedin.com/company/12345678/admin`).

### Telegram alerts (optional)
Create a bot with @BotFather, then fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. You'll get the image or thumbnail and a dashboard link for each new item.

## 5. Deploy on Render (one service: dashboard + API)

```
Browser ──► Render (Docker: React dashboard + FastAPI + scheduler + Chromium + ffmpeg) ──► Supabase (database + files)
```
The dashboard is built into the same service, so there's no CORS setup and no API URL to configure.

1. Push the repo to GitHub.
2. On render.com, choose **New → Blueprint** and pick the repo. Render reads `render.yaml`.
3. Under **Environment**, fill in (your `.env` file is **not** used on Render):
   - `ANTHROPIC_API_KEY`
   - `DASHBOARD_USER`, `DASHBOARD_PASSWORD`
   - `PUBLIC_BASE_URL` (your Render URL, e.g. `https://social-media-agent-y7yv.onrender.com`, no trailing `/`)
   - `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (see Supabase below)
4. Deploy. The first build takes about 10 minutes because it includes Chromium. Then open `https://<your-app>.onrender.com/health`; it should return `{"ok": true}`.
5. Log in and open **Settings → Status → Full check**. Every line should be green.

### Dashboard on a free Static Site (no Render "waking up" page)
The free agent sleeps after 15 minutes. Open the dashboard through the **Static Site** instead of the agent's link:
it never sleeps, opens instantly and shows a Krypsos loading screen until the agent is awake (about a minute).
1. Render → **New → Static Site** → this repo. Root directory `frontend`, build `npm ci && npm run build`,
   publish directory `dist` (or use the Blueprint – `render.yaml` already describes it).
2. **Redirects/Rewrites** (Static Site → Settings), in this order – all type *Rewrite*:
   `/api/*` → `https://<agent>.onrender.com/api/*`, the same for `/media/*`, `/brand/*`, `/classic/*`,
   and last `/*` → `/index.html`.
3. On the **agent** service set `FRONTEND_URL=https://<static-site>.onrender.com` (logins to Instagram/LinkedIn
   return there). Keep `PUBLIC_BASE_URL` = the agent's own address.
4. Use only the Static Site link from now on (also for "Install app" on your phone). The agent's link still works.
Tip: a free cron-job.org job opening `https://<agent>.onrender.com/health` every 10 minutes keeps the agent awake
for the 18:00 preparation and posting times.

### Supabase: free database + file storage (so nothing is lost on Render)
Render's free plan wipes the server's disk on every restart. With Supabase connected:
- the queue and history are kept in **Postgres**;
- posters, videos and thumbnails are kept in **Storage**;
- settings and events you edit in the dashboard are copied into the database and restored on start-up;
- your uploaded logo and music are kept in Storage and downloaded again on start-up.

Steps:
1. On supabase.com, create a **new project**. Pick region **South Asia (Mumbai)** and save the database password.
2. Click **Connect → Session pooler** and copy the URI. Replace `[YOUR-PASSWORD]` with your database password and use the result as `DATABASE_URL`. Use the pooler URI: the direct connection needs IPv6, which Render doesn't have.
3. Go to **Project Settings → API keys**. Use the **Project URL** as `SUPABASE_URL` and the **secret** (`sb_secret_…`) or legacy **service_role** key as `SUPABASE_SERVICE_KEY`; the publishable / anon key does not work. Keep that key secret; it goes only in Render's environment.
4. Add these three values in Render (Environment). A public `media` bucket is created automatically on the first upload.
5. Open **Settings → Status & health** in the dashboard. *Database* should show "cloud Postgres" and *File storage* should show "Supabase bucket".

Free tier limits:
- 500 MB database (plenty).
- **1 GB storage**: about 40–60 promo videos with both versions, or thousands of posters.
- Max 50 MB per file.
- A project pauses after 7 days with no activity; with the cron-job.org ping, the daily agent keeps it active.

On your PC, leave all three empty: the agent keeps using `agent.db` and the `media/` folder.

### Videos on the free plan: made by your PC
Render's free server (512 MB) runs out of memory making videos, so `render.yaml` sets `VIDEO_RENDERER=pc`:
the website makes posts itself, but **queues videos** ("Waiting for your PC"). Your PC makes them and they
appear on the website, with live progress, Stop and the quality check.

One-time setup on your PC:
1. In the project's `.env` on your PC, set the **same** `DATABASE_URL`, `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` as on Render (plus `ANTHROPIC_API_KEY`).
2. Double-click **`run_video_worker.bat`** and keep the window open. It checks for queued videos every 20 seconds.

The sidebar shows **Video PC: online / making a video / offline**. If the PC is off, videos simply wait. If it's switched
off in the middle of a video, that video is marked failed after 5 minutes so you can click Regenerate.
While the PC uses Supabase, `run_agent.bat` on the PC also shows the live data – use the website instead, so the
daily schedule only runs in one place.

### Render free plan: limits and workarounds
| Limit | What it means | Workaround |
|---|---|---|
| Sleeps after 15 min with no visits | The 18:00 preparation and 10:00 publishing don't run while it sleeps. The first visit takes about a minute (the dashboard shows "Waking up the server…"). | Create a free job on cron-job.org that opens `https://<your-app>.onrender.com/health` every 10 minutes. 750 free hours a month covers one service 24/7. |
| Files reset on every deploy or restart | Without Supabase, the queue, media, logo/music and dashboard setting changes are lost. | **Connect Supabase** (above) and everything is kept. Or, on a paid plan, add the disk in `render.yaml`. With Supabase on, the dashboard is the source of truth for settings: edits pushed to `config/settings.yaml` are overridden by the saved copy, so make changes in the dashboard. |
| 512 MB RAM | Posts work. Videos can run out of memory (`LOW_MEMORY=1` is already on). | Use the agent on your PC for videos, or move to a 2 GB plan. |

When you upgrade, set the plan in `render.yaml` to `standard` and uncomment the `disk:` block. You don't need to change any code.

## 6. Tuning for reach
- Keep videos at 30–45 s (`video.max_seconds`). The first 2 seconds (hook card) decide retention.
- Add 2–4 `showcase_pages` in settings so videos always show your best pages.
- Voice: change `video.voice` (`en-IN-NeerjaNeural`, `en-US-AriaNeural`, … run `edge-tts --list-voices`).
- Use **Regenerate** freely. Edits to captions are saved before publishing.
- No tool can guarantee a viral post. The agent follows proven patterns (hook, trend tie-in, captions, hashtags) and you approve what fits your brand.

## Where your posters and videos are saved
```
media/
  posters/      2026-11-18_restaurant-pos_before-after_12.jpg      ← ready-to-post images (1080×1350)
    source/     2026-11-18_restaurant-pos_before-after_12.html     ← the design each poster was made from
  videos/       2026-11-20_clinic_promo_14_16x9.mp4                 ← LinkedIn / YouTube
                2026-11-20_clinic_promo_14_9x16.mp4                 ← Instagram / Facebook Reels
  thumbnails/   video cover images for the dashboard
  .work/        temporary render files (cleaned automatically)
```
File names are *date_product_format_id*, so they sort by date. The review page shows each item's file path.
Files made by an older version (in `media/<date>/`) can be moved into these folders with `python cli.py organize-media`.
`media/` stays out of Git. The agent serves it to the dashboard and, later, to Instagram, which needs a public link to each file.

## Project layout
```
app/research/   website.py (crawler) · trends.py (Google Trends + news) · calendar.py (festivals/events)
app/generators/ planner.py · post.py · video.py · browser.py (Playwright) · tts.py · ffmpeg.py · graphics.py
app/publishers/ meta.py (Facebook + Instagram) · linkedin.py
app/            pipeline.py · scheduler.py · main.py (dashboard + API) · db.py · llm.py · notify.py
config/         settings.yaml · events.yaml
```
API for Super Agent Platform / n8n: `GET /api/items?status=pending_approval`, `POST /api/items/{id}/approve` (basic auth).
