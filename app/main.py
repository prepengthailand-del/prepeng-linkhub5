import os, hmac, hashlib, json, urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, Response, Depends, Header
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship

import httpx

load_dotenv()

ENV = os.getenv("ENV","development")
BASE_URL = os.getenv("BASE_URL","http://localhost:8000")
PORT = int(os.getenv("PORT","8000"))

DB_URL = os.getenv("DATABASE_URL","sqlite:///./data.db")
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# --- Models ---
class Click(Base):
    __tablename__ = "clicks"
    id = Column(Integer, primary_key=True)
    ref_token = Column(String(32), unique=True, index=True)
    src = Column(String(32))
    ttclid = Column(String(128), nullable=True)
    utm_source = Column(String(128), nullable=True)
    utm_campaign = Column(String(256), nullable=True)
    utm_adset = Column(String(256), nullable=True)
    utm_ad = Column(String(256), nullable=True)
    user_agent = Column(Text, nullable=True)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    choices = relationship("Choice", back_populates="click", cascade="all, delete-orphan")
    lead = relationship("Lead", back_populates="click", uselist=False)

class Choice(Base):
    __tablename__ = "choices"
    id = Column(Integer, primary_key=True)
    click_id = Column(Integer, ForeignKey("clicks.id"))
    dest = Column(String(32))  # line / messenger / shopee
    created_at = Column(DateTime, default=datetime.utcnow)
    click = relationship("Click", back_populates="choices")

class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    click_id = Column(Integer, ForeignKey("clicks.id"), unique=True)
    ref_token = Column(String(32), unique=True, index=True)
    channel = Column(String(32))  # messenger or line
    external_user_id = Column(String(128))  # PSID or LINE userId
    first_event_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(32), default="new")
    raw = Column(Text, nullable=True)
    click = relationship("Click", back_populates="lead")

def init_db():
    Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- App ---
app = FastAPI(title="PrepEng LinkHub PRO")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- Utils ---
def new_ref() -> str:
    seed = f"{datetime.now(timezone.utc).timestamp()}-{os.urandom(8).hex()}"
    return hashlib.sha1(seed.encode()).hexdigest()[:16]

def capi_send_facebook(event_name: str, click: Click, lead: Optional[Lead]=None):
    pixel_id = os.getenv("FB_CAPI_PIXEL_ID")
    access_token = os.getenv("FB_CAPI_ACCESS_TOKEN")
    if not pixel_id or not access_token:
        return {"skipped":"missing fb capi config"}
    url = f"https://graph.facebook.com/v18.0/{pixel_id}/events"
    # Minimal payload (improve hashing in production)
    data = {
        "data":[{
            "event_name": event_name,
            "event_time": int(datetime.now(timezone.utc).timestamp()),
            "action_source": "website",
            "event_source_url": f"{BASE_URL}/choose",
            "user_data": {
                # You can add more hashed fields later
                "client_ip_address": click.ip or "",
                "client_user_agent": click.user_agent or ""
            },
            "custom_data": {
                "ref": click.ref_token,
                "src": click.src,
                "utm_campaign": click.utm_campaign
            }
        }]
    }
    try:
        r = httpx.post(url, params={"access_token": access_token}, json=data, timeout=10.0)
        return {"status": r.status_code, "resp": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}

def tiktok_events_api(event_name: str, click: Click):
    # Placeholder: fill in with Business Events API when ready
    return {"skipped":"tiktok events api not configured"}

# --- Schemas ---
class TrackPayload(BaseModel):
    dest: str
    query: Dict[str, Any] = {}
    user_agent: Optional[str] = None

# --- Routes ---
@app.get("/choose", response_class=HTMLResponse)
def choose_page(request: Request):
    return templates.TemplateResponse("choose.html", {"request": request})

@app.post("/track")
def track_choice(payload: TrackPayload, request: Request, db: Session = Depends(get_db)):
    # 1) store or create click
    q = payload.query or {}
    ref = new_ref()
    click = Click(
        ref_token=ref,
        src=q.get("src") or "tiktok",
        ttclid=q.get("ttclid"),
        utm_source=q.get("utm_source"),
        utm_campaign=q.get("utm_campaign"),
        utm_adset=q.get("utm_adset"),
        utm_ad=q.get("utm_ad"),
        user_agent=payload.user_agent or request.headers.get("user-agent",""),
        ip=request.client.host if request.client else None
    )
    db.add(click)
    db.flush()  # get click.id

    ch = Choice(click_id=click.id, dest=payload.dest)
    db.add(ch)
    db.commit()

    # Optional: fire CAPI/tiktok event for click
    capi_send_facebook("LeadClick", click)
    tiktok_events_api("Click", click)

    # 2) redirect target
    if payload.dest == "messenger":
        page_id = os.getenv("FB_PAGE_ID","")
        if not page_id:
            return JSONResponse({"ok": False, "error":"FB_PAGE_ID missing"}, status_code=500)
        url = f"https://m.me/{page_id}?ref={urllib.parse.quote(ref)}"
        return {"ok": True, "redirect_to": f"/go/messenger?ref={ref}"}
    elif payload.dest == "line":
        return {"ok": True, "redirect_to": f"/go/line?ref={ref}"}
    elif payload.dest == "shopee":
        return {"ok": True, "redirect_to": f"/go/shopee?ref={ref}"}
    else:
        return JSONResponse({"ok": False, "error":"unknown dest"}, status_code=400)

@app.get("/go/messenger")
def go_messenger(ref: str):
    page_id = os.getenv("FB_PAGE_ID","")
    url = f"https://m.me/{page_id}?ref={urllib.parse.quote(ref)}"
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie("pe_ref", ref, max_age=30*24*3600, httponly=True)
    return resp

@app.get("/go/line")
def go_line(ref: str):
    # Log-only endpoint (click already stored); here you might create a 'prelead'
    # Then forward to LINE add-friend link
    line_link = os.getenv("LINE_ADD_FRIEND_LINK","https://line.me/R/ti/p/@YOUR_LINE_ID")
    resp = RedirectResponse(url=line_link, status_code=302)
    resp.set_cookie("pe_ref", ref, max_age=30*24*3600, httponly=True)
    return resp

@app.get("/go/shopee")
def go_shopee(ref: str, request: Request, db: Session = Depends(get_db)):
    # For Shopee, we can only attribute outbound clicks; purchases attribution lives in Shopee affiliate
    shopee = os.getenv("SHOPEE_FALLBACK_URL","https://shopee.co.th")
    resp = RedirectResponse(url=shopee, status_code=302)
    resp.set_cookie("pe_ref", ref, max_age=7*24*3600, httponly=True)
    return resp

# --- Facebook Webhook ---
@app.get("/webhook/facebook")
def fb_verify(mode: str = "", challenge: str = "", verify_token: str = ""):
    if verify_token == os.getenv("FB_VERIFY_TOKEN",""):
        return PlainTextResponse(challenge)
    return Response(status_code=403)

@app.post("/webhook/facebook")
async def fb_webhook(payload: Dict[str, Any], db: Session = Depends(get_db)):
    # Parse basic structure
    entry_list = payload.get("entry", [])
    for entry in entry_list:
        for msg in entry.get("messaging", []):
            sender_id = msg.get("sender",{}).get("id")
            ref = None
            if "referral" in msg:
                ref = msg["referral"].get("ref")
            elif "postback" in msg and "referral" in msg["postback"]:
                ref = msg["postback"]["referral"].get("ref")
            if ref:
                # find click and upsert lead
                click = db.query(Click).filter(Click.ref_token==ref).one_or_none()
                if click:
                    lead = db.query(Lead).filter(Lead.ref_token==ref).one_or_none()
                    if not lead:
                        lead = Lead(click_id=click.id, ref_token=ref, channel="messenger",
                                    external_user_id=sender_id, raw=json.dumps(msg))
                        db.add(lead); db.commit()
                        capi_send_facebook("Lead", click, lead)
    return {"ok": True}

# --- LINE Webhook ---
def verify_line_signature(body: bytes, signature: str) -> bool:
    secret = os.getenv("LINE_CHANNEL_SECRET","")
    if not secret or not signature:
        return False
    mac = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).digest()
    import base64
    return base64.b64encode(mac).decode('utf-8') == signature

@app.post("/webhook/line")
async def line_webhook(request: Request, db: Session = Depends(get_db), x_line_signature: str = Header(None)):
    raw = await request.body()
    if not verify_line_signature(raw, x_line_signature):
        return Response(status_code=403)
    payload = json.loads(raw.decode('utf-8'))
    events = payload.get("events",[])
    for ev in events:
        ev_type = ev.get("type")
        user_id = ev.get("source",{}).get("userId")
        # When user adds friend, type can be "follow"; when message, type is "message"
        # We cannot receive ref directly; recommend asking user to tap a postback with ref or use LIFF
        # As a pragmatic approach, if the user enters via /go/line we already set cookie 'pe_ref'
        # For server-side, consider mapping recent 'line choices' ip/ua to this event if needed.
        # Here we only log the first contact to create a lead without ref.
        if ev_type in ("follow","message") and user_id:
            # Create a generic lead without ref (or try to match heuristically)
            lead = Lead(click_id=None, ref_token=f"line-{user_id[:10]}", channel="line",
                        external_user_id=user_id, raw=json.dumps(ev))
            db.add(lead); db.commit()
    return {"ok": True}

# --- Minimal admin (demo) ---
@app.get("/admin/stats")
def admin_stats(db: Session = Depends(get_db)):
    clicks = db.query(Click).count()
    leads = db.query(Lead).count()
    by_campaign = {}
    for c in db.query(Click).all():
        key = c.utm_campaign or "NA"
        by_campaign[key] = by_campaign.get(key,0)+1
    return {"clicks": clicks, "leads": leads, "clicks_by_campaign": by_campaign}

@app.on_event("startup")
def on_startup():
    init_db()
