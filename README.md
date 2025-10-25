# PrepEng LinkHub PRO (FastAPI)

Link hub + tracking + webhooks (Messenger & LINE) + server-side conversions (stubs) for running TikTok ads that branch users to LINE / Facebook Messenger / Shopee while keeping attribution intact.

## Features
- `/choose` landing (chooser page) collecting `ttclid` + UTM
- `/track` logs destination selection and emits unique `ref`
- `/go/messenger|line|shopee` redirects with `ref` for later matching
- `/webhook/facebook` verifies + receives Messenger events (captures `ref`)
- `/webhook/line` receives LINE events (validates signature) and captures userId (post-add friend or message)
- Minimal admin JSON endpoints for stats (clicks/leads)
- Stubs for Facebook CAPI / TikTok Events API (fill tokens to activate)

## Quick Start (Local)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open: `http://localhost:8000/choose?src=tiktok&utm_campaign=Test&ttclid=TEST123`

## Deploy on Render (Free)
- Push this folder to GitHub
- Create a **Web Service**
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Add environment variables (see `.env.example`)

## TikTok Ad URL
```
https://YOUR_DOMAIN/choose?src=tiktok&utm_source=tiktok&utm_campaign={{CampaignName}}&utm_adset={{AdGroupName}}&utm_ad={{AdName}}&ttclid={ttclid}
```

## Messenger Button redirect
The app sends users to:
```
https://m.me/<FB_PAGE_ID>?ref=<ref_token>
```

## LINE Button redirect
We first log the click at `/go/line?ref=...` then redirect to the official add-friend link:
```
https://line.me/R/ti/p/@YOUR_LINE_ID
```
For deeper tracking, consider LIFF login to capture LINE userId proactively.

## Minimal DB schema
Tables:
- `clicks` (one per landing)
- `choices` (one per button click)
- `leads` (created when we receive a Messenger or LINE webhook referencing a `ref`)

## Security
- Validate LINE signatures
- Restrict admin endpoints; by default they are open for demo

## Disclaimer
Replace all placeholder IDs/tokens before production. Test in a sandbox page before going live.
