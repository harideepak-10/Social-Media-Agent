"""Design system distilled from the Krypsos sample posts/videos: themes, post formats, video looks.

Variety comes from rotating FORMAT x THEME x PRODUCT x TOPIC (see rotation.py), so the feed
never shows the same layout twice in a row.
"""
from __future__ import annotations

# ── Post themes ───────────────────────────────────────────────────────────
# fonts are Google Fonts (loaded at render time; system fallbacks if offline)
POST_THEMES: dict[str, dict] = {
    "cream_editorial": {
        "label": "Cream editorial (sample: 'No more manual invoice entry')",
        "bg": "#ECE4D8", "surface": "#FBF8F2", "ink": "#151413", "muted": "#5B5650",
        "accent": "#C8372D", "accent2": "#F7DC6F", "logo": "dark",
        "heading_font": "Manrope:800", "body_font": "Manrope:400,600",
        "mood": "paper-like warm cream, heavy black headline with a highlighter swipe behind one key word, "
                "white document/UI card with soft shadow, red numbered square badges, dashed connector lines",
    },
    "midnight_violet": {
        "label": "Midnight violet festive (sample: Diwali mandala)",
        "bg": "#14072B", "surface": "#24104A", "ink": "#F6F0FF", "muted": "#B9A8D9",
        "accent": "#F3C46B", "accent2": "#FF4FD8", "logo": "light",
        "heading_font": "Playfair Display:500,700", "body_font": "IBM Plex Mono:400",
        "mood": "deep purple night, glowing neon line-art (SVG) in pink/gold, bokeh dots, elegant serif headline, "
                "italic gold quote line, small monospace body text",
    },
    "dark_tech": {
        "label": "Dark tech / developer (sample: expectation vs reality)",
        "bg": "#0B111C", "surface": "#141C2B", "ink": "#EAF0F8", "muted": "#8D9AB0",
        "accent": "#7EF0A8", "accent2": "#FF5C7A", "logo": "light",
        "heading_font": "Inter:800", "body_font": "Inter:400,600",
        "mood": "dark navy panels, rounded label chips (mint / coral), terminal window with red error rows, "
                "handwritten-style accent line, bottom bar with 3 icon+label pillars",
    },
    "amber_noir": {
        "label": "Amber noir premium (sample: DineOS video)",
        "bg": "#0B0A09", "surface": "#16130F", "ink": "#F5F1EA", "muted": "#9C958A",
        "accent": "#F59E0B", "accent2": "#F97316", "logo": "light",
        "heading_font": "Manrope:700,800", "body_font": "Manrope:400,500",
        "mood": "near-black with a warm amber glow, product UI in a dark window frame, amber gradient accent text, "
                "small uppercase letter-spaced eyebrow with a dot",
    },
    "navy_gold": {
        "label": "Navy & gold luxury (sample: clinic video)",
        "bg": "#08111F", "surface": "#0F1B2E", "ink": "#EEF2F8", "muted": "#94A3B8",
        "accent": "#9CC3FF", "accent2": "#C9A86A", "logo": "light",
        "heading_font": "Playfair Display:500,600", "body_font": "Inter:400,500",
        "mood": "calm luxury, deep navy, serif headline with soft-blue accent words, thin gold details, lots of air",
    },
    "clean_white": {
        "label": "Clean white SaaS",
        "bg": "#F7F9FC", "surface": "#FFFFFF", "ink": "#0F172A", "muted": "#5B6474",
        "accent": "#2563EB", "accent2": "#22C55E", "logo": "dark",
        "heading_font": "Plus Jakarta Sans:800", "body_font": "Plus Jakarta Sans:400,600",
        "mood": "crisp white, soft blue glow, floating UI cards with layered shadows, pill tags",
    },
    "mint_fresh": {
        "label": "Mint fresh",
        "bg": "#E6F5EE", "surface": "#FFFFFF", "ink": "#0B3B2E", "muted": "#3F6B5E",
        "accent": "#0F9D6B", "accent2": "#FF7A59", "logo": "dark",
        "heading_font": "DM Sans:800", "body_font": "DM Sans:400,500",
        "mood": "fresh mint background, rounded shapes, friendly icons, coral highlights",
    },
    "sunset_bold": {
        "label": "Sunset bold",
        "bg": "#FF6B4A", "surface": "#FFF4E8", "ink": "#1A0E0A", "muted": "#4A2A1F",
        "accent": "#1A0E0A", "accent2": "#FFE27A", "logo": "dark",
        "heading_font": "Bricolage Grotesque:800", "body_font": "DM Sans:400,600",
        "mood": "loud coral-to-amber gradient, giant tight headline, sticker-like cards and arrows",
    },
    "receipt_red": {
        "label": "Tomato red + paper (sample: 'Your receipt is ready')",
        "bg": "#E04A30", "surface": "#FAF8F3", "ink": "#161412", "muted": "#5B5650",
        "accent": "#161412", "accent2": "#FFFFFF", "logo": "dark",
        "heading_font": "Fraunces:800,900", "body_font": "IBM Plex Mono:400,600,700",
        "mood": "flat tomato-red background, giant white heavy serif headline, off-white paper objects (receipts, "
                "tickets, cards) with monospace type, dotted leaders, a black inverted box, soft drop shadow",
    },
    "forest_mint": {
        "label": "Forest & mint infographic (sample: 'Why choose Krypsos?')",
        "bg": "#EEF6F1", "surface": "#FFFFFF", "ink": "#0F2E24", "muted": "#4B6358",
        "accent": "#0F5C45", "accent2": "#7BD389", "logo": "dark",
        "heading_font": "Plus Jakarta Sans:700,800", "body_font": "Plus Jakarta Sans:400,500,600",
        "mood": "airy mint-white, deep forest green headline and icon circles, rounded service cards, a dark green "
                "footer band with a mint pill button, handwritten green note with a hand-drawn underline",
    },
}

FESTIVE_THEMES = ["midnight_violet", "navy_gold", "amber_noir", "sunset_bold"]

# ── Post formats ──────────────────────────────────────────────────────────
# needs: "product" (a product/service to explain), "shot" (captured UI image), "festival", "trend", "photo" (AI image)
POST_FORMATS: dict[str, dict] = {
    "explainer_steps": {
        "label": "Problem headline + document/UI mock + numbered steps",
        "brief": "Big problem-killing headline ('No more manual X.') with a highlighter on one word, one-line "
                 "subhead, a realistic mock card (invoice / booking / order / chat) on the left with highlighted "
                 "fields, and 3-4 numbered steps on the right connected with dashed lines; footer: logo + "
                 "'benefit · benefit · website'.",
        "needs": {"product"}, "sources": {"website", "trend", "url"},
    },
    "ui_showcase": {
        "label": "Real product screenshot with callouts",
        "brief": "Headline on top; the provided product screenshot (shot1.png) large in a window frame with "
                 "2-3 floating callout chips pointing at real features/numbers visible in it.",
        "needs": {"product", "shot"}, "sources": {"website", "url"},
    },
    "before_after": {
        "label": "Before vs after split",
        "brief": "Two halves: 'Before' (manual chaos: sticky notes, spreadsheets, missed calls) vs 'After' "
                 "(the product: calm, automated). Strong contrast between halves, short lines only.",
        "needs": {"product"}, "sources": {"website", "trend", "url"},
    },
    "myth_fact": {
        "label": "Myth vs fact",
        "brief": "A common myth about automation/AI for small businesses crossed out, followed by the fact, "
                 "with one supporting point tied to the product.",
        "needs": set(), "sources": {"website", "trend", "url"},
    },
    "checklist": {
        "label": "'N signs you need…' checklist",
        "brief": "Title like '5 signs your restaurant has outgrown its billing software', 4-6 check rows with icons, "
                 "last line a soft CTA.",
        "needs": {"product"}, "sources": {"website", "url"},
    },
    "chat_demo": {
        "label": "Chat conversation mock",
        "brief": "A phone/chat window showing a short realistic conversation where the bot/agent solves a task "
                 "(WhatsApp-style bubbles, approval button), headline beside or above it.",
        "needs": {"product"}, "sources": {"website", "url"},
    },
    "relatable_meme": {
        "label": "Relatable humour (expectation vs reality)",
        "brief": "Light, relatable humour for business owners or developers: Expectation vs Reality, "
                 "'Monday vs Friday', 'Me before / after automation', 'The client said: small change'. Two stacked "
                 "panels with label chips, or a classic two-row meme layout. Illustrate with a simple SVG cartoon "
                 "character (round face, expressive eyes) or big emoji reactions, UI mocks, a terminal window of "
                 "errors or sticky notes. If photo images are available you may use them (ai1.png, ai2.png).",
        "needs": set(), "sources": {"website", "trend", "url"},
    },
    "big_statement": {
        "label": "One big statement / insight",
        "brief": "Single bold typographic statement filling the canvas (max 9 words), one supporting line, "
                 "subtle background shapes. No numbers unless they are on the website.",
        "needs": set(), "sources": {"website", "trend", "url"},
    },
    "question_engage": {
        "label": "Engagement question / poll",
        "brief": "Ask the audience a question ('Which task would you automate first?') with 3-4 option cards "
                 "(A/B/C/D) and 'Tell us in the comments'.",
        "needs": set(), "sources": {"website", "trend", "url"},
    },
    "trend_take": {
        "label": "Trend / news reaction",
        "brief": "A news-style card quoting the trend topic (paraphrased, no fake quotes), then 'What it means for "
                 "your business' with 2-3 takeaways and how the product helps.",
        "needs": {"trend"}, "sources": {"trend"},
    },
    "tip_card": {
        "label": "Practical tip",
        "brief": "'Tip #N' badge, a practical, specific productivity/automation tip in 2-3 short steps, small "
                 "illustration made with CSS/SVG.",
        "needs": set(), "sources": {"website", "trend", "url"},
    },
    "object_metaphor": {
        "label": "Everyday-object metaphor (receipt, ticket, menu …)",
        "brief": "Explain the value through a familiar object rebuilt in HTML/CSS, like the 'Your receipt is ready.' "
                 "sample: a receipt, boarding pass, restaurant menu, prescription, report card, movie ticket, recipe "
                 "card or parking ticket. Giant headline above; the object slightly rotated with realistic details "
                 "(zigzag edges, monospace type, dotted leaders, barcode/QR, a stamp); its lines list real services "
                 "or benefits from the website; a punchy result line ('TOTAL: YOUR TIME BACK'). Witty but clear.",
        "needs": set(), "sources": {"website", "trend", "url"},
    },
    "services_overview": {
        "label": "'Why choose us' brand infographic",
        "brief": "Like the 'Why Choose Krypsos?' sample: huge question headline + one-line answer, a laptop or "
                 "phone mock showing the website UI (built in CSS, or shot1.png if provided), 3 short value rows "
                 "with icons, an 'Our Services' grid of 6 icon cards (real services from the website), and a "
                 "footer band with a pill CTA. Only use numbers that appear on the website.",
        "needs": set(), "sources": {"website", "url"},
    },
    "festive_greeting": {
        "label": "Festival greeting art",
        "brief": "Elegant festival greeting: generative SVG line art inspired by the festival's symbols (e.g. "
                 "diyas & rangoli for Diwali, stars for Christmas, kolam for Pongal) blended with tech motifs "
                 "(circuit lines, binary rings). Two-line serif headline, one italic quote line, short body, "
                 "'Happy <festival> from Team <brand>'. Warm, respectful, no selling.",
        "needs": {"festival"}, "sources": {"festival"},
    },
    "event_announcement": {
        "label": "Event / launch announcement",
        "brief": "Bold announcement card: event title, date/time chips, 2-3 'what you'll get' lines, CTA.",
        "needs": {"event"}, "sources": {"event"},
    },
}

# ── Video looks ───────────────────────────────────────────────────────────
VIDEO_THEMES: dict[str, dict] = {
    "amber_noir": {"bg": "#0A0908", "bg2": "#1A1209", "panel": "#15120F", "ink": "#F5F1EA", "muted": "#A39B8F",
                   "accent": "#F59E0B", "accent2": "#F97316", "heading": "Manrope", "head_weight": 700,
                   "body": "Manrope", "serif": False, "logo": "light"},
    "navy_gold": {"bg": "#060D19", "bg2": "#0E1E38", "panel": "#0D1829", "ink": "#EEF2F8", "muted": "#93A3BA",
                  "accent": "#9CC3FF", "accent2": "#C9A86A", "heading": "Playfair Display", "head_weight": 600,
                  "body": "Inter", "serif": True, "logo": "light"},
    "emerald_night": {"bg": "#04110D", "bg2": "#0A2A20", "panel": "#0B1C17", "ink": "#ECF7F2", "muted": "#8FB1A5",
                      "accent": "#34D399", "accent2": "#A7F3D0", "heading": "Plus Jakarta Sans", "head_weight": 800,
                      "body": "Plus Jakarta Sans", "serif": False, "logo": "light"},
    "violet_glow": {"bg": "#0D0718", "bg2": "#24104A", "panel": "#160D29", "ink": "#F4EEFF", "muted": "#A89BC4",
                    "accent": "#C084FC", "accent2": "#F472B6", "heading": "Manrope", "head_weight": 800,
                    "body": "Manrope", "serif": False, "logo": "light"},
    "paper_light": {"bg": "#F1EBE1", "bg2": "#E6DCCD", "panel": "#FFFFFF", "ink": "#161412", "muted": "#615A52",
                    "accent": "#C8372D", "accent2": "#E9A23B", "heading": "Manrope", "head_weight": 800,
                    "body": "Manrope", "serif": False, "logo": "dark"},
}

ICONS = ["spark", "chart", "clock", "shield", "users", "chat", "bolt", "check", "calendar", "receipt",
         "layers", "bell", "box", "qr", "wallet", "mail", "file", "bot", "star", "settings", "link", "search",
         "heart", "camera", "phone", "table", "chef", "stock", "lock", "globe"]
