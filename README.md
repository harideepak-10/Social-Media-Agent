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

**Optional AI photos.** Set `IMAGE_PROVIDER=openai` or `gemini` with a key to allow photo-style memes (like the cat post). Without it, the AI draws with CSS/SVG instead.

If the premium engine ever fails, a simpler version is made so the day isn't empty, and a warning appears on the item.

## 2a. Video or post for ANY website

Give the agent any link and it creates an explainer video (or a post) for that site:
```bash
python cli.py from-url https://anywebsite.com
python cli.py from-url https://anywebsite.com --kind post
python cli.py from-url https://anywebsite.com --notes "explain the booking feature for restaurant owners"
```
You can also use the **🎬 Create from any website** box in the dashboard, or call `POST /api/from-url` with `{"url": "...", "kind": "video", "notes": ""}`.

What the agent does with the link:
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

## 3. Weekly schedule

Set this in the dashboard (**Weekly schedule**) or in `settings.yaml`:
```yaml
schedule: { monday: video, tuesday: post, wednesday: post, thursday: video, friday: post, saturday: post, sunday: none }
generate_time: "18:00"   # prepare tomorrow's content and send it for approval
publish_time:  "10:00"   # post approved content
```
With `always_post_on_festivals: true`, a festival on a `none` day still gets a greeting post.

## 4. Connect the social accounts

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

## 5. Deploy (needs to run 24/7 for the schedule)
- **Docker**: `docker build -t dma . && docker run -p 8000:8000 --env-file .env -v ./media:/app/media dma`
- **Render**: create a *Web Service → Docker*. Note: the **free plan sleeps** after 15 minutes idle, so scheduled jobs won't fire. Use a paid instance, or ping `/health` every 10 minutes (cron-job.org). The app also catches up on missing content at start-up. Render's free disk is wiped on deploy, so use a persistent disk for `media/` and `agent.db`.
- Or run it on any always-on PC or VPS with `python cli.py serve`.

## 6. Tuning for reach
- Keep videos at 30–45 s (`video.max_seconds`). The first 2 seconds (hook card) decide retention.
- Add 2–4 `showcase_pages` in settings so videos always show your best pages.
- Voice: change `video.voice` (`en-IN-NeerjaNeural`, `en-US-AriaNeural`, … run `edge-tts --list-voices`).
- Use **Regenerate** freely. Edits to captions are saved before publishing.
- No tool can guarantee a viral post. The agent follows proven patterns (hook, trend tie-in, captions, hashtags) and you approve what fits your brand.

## Project layout
```
app/research/   website.py (crawler) · trends.py (Google Trends + news) · calendar.py (festivals/events)
app/generators/ planner.py · post.py · video.py · browser.py (Playwright) · tts.py · ffmpeg.py · graphics.py
app/publishers/ meta.py (Facebook + Instagram) · linkedin.py
app/            pipeline.py · scheduler.py · main.py (dashboard + API) · db.py · llm.py · notify.py
config/         settings.yaml · events.yaml
```
API for Super Agent Platform / n8n: `GET /api/items?status=pending_approval`, `POST /api/items/{id}/approve` (basic auth).
