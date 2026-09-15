import discord
import smtplib
import asyncio
import os
import json
from datetime import datetime, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

# ── Configuration ────────────────────────────────────────────────────────────
DISCORD_TOKEN   = os.environ["DISCORD_TOKEN"]
EMAIL_ADDRESS   = os.environ["EMAIL_ADDRESS"]    # klcaprio@hotmail.com
EMAIL_PASSWORD  = os.environ["EMAIL_PASSWORD"]   # app password
ALERT_EMAIL     = os.environ["ALERT_EMAIL"]      # klcaprio@hotmail.com

EASTERN = ZoneInfo("America/New_York")
DAILY_SUMMARY_HOUR = 18   # 6 PM EST

# ── Channels to monitor (exact Discord channel names) ────────────────────────
WATCHED_CHANNELS = {
    # OA Challenge+
    "2026-q3-leads", "2026-q4-leads",
    "flip-alert-leads", "deals-feed",
    "ai-chat", "announcements",
    "amazon-ecommerce-news", "source-lens-support",
    "asin-so-support", "discontinued-bolos",
    "wins", "guides-and-sops",
    # The Amazon Launchpad
    "ungating", "auto-ungate-asins",
    "sourcing-questions", "keepa-analysis",
    "software-questions",
    "success",
    "retailers-that-cancel", "lessons-learned",
}

# ── Alert keywords (triggers real-time email) ─────────────────────────────────
ALERT_KEYWORDS = [
    # Flips / leads
    "flip", "amazon to amazon", "a to a", "a2a", "flip alert",
    "bolo", "buy box", "arbitrage",
    # Ungating
    "ungat", "ungate", "approved", "invoice approved",
    "brand approved", "category approved", "gated", "get approved",
    # AI tools
    "chatgpt", "claude", "ai tool", "gpt", "copilot", "gemini",
    "ai sourcing", "ai leads", "automation", "ai finds",
    # Software
    "source lens", "sourcelens", "keepa", "asin.so", "scanpower",
    "seller amp", "selleramp", "tactical arbitrage", "oaxray",
    "storefront stalker", "flip alert", "update", "new feature",
    # OA retailers
    "walmart", "target", "home depot", "lowes", "costco", "staples",
    "office depot", "best buy", "kohls", "macys", "nordstrom",
    "dick's sporting", "academy", "crocs", "adidas", "new balance",
]

# ── Skip keywords (never alert on these) ─────────────────────────────────────
SKIP_KEYWORDS = [
    "canada", "canadian", "uk ", "united kingdom", "ebay uk",
    "amazon.ca", "amazon.co.uk", "introduce yourself", "hello everyone",
    "just joined", "new member", "hi i'm", "hi i am",
]

# ── ROI / profit filter ───────────────────────────────────────────────────────
MIN_PROFIT = 7.0
MIN_ROI    = 50.0
MAX_BSR    = 150_000

# ── Storage for daily summary ─────────────────────────────────────────────────
daily_log: list[dict] = []
last_summary_date: str = ""

# ─────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

client = discord.Client(intents=intents)


# ── Email helper ──────────────────────────────────────────────────────────────
def send_email(subject: str, body_html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = ALERT_EMAIL
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP("smtp-mail.outlook.com", 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, ALERT_EMAIL, msg.as_string())


# ── Message scoring / filtering ───────────────────────────────────────────────
def should_skip(text: str) -> bool:
    tl = text.lower()
    return any(kw in tl for kw in SKIP_KEYWORDS)


def get_alert_reason(text: str) -> str | None:
    tl = text.lower()
    for kw in ALERT_KEYWORDS:
        if kw in tl:
            return kw
    return None


def extract_numbers(text: str) -> dict:
    """Best-effort extraction of profit / ROI / BSR from message text."""
    import re
    numbers = {}

    profit_match = re.search(r"\$\s*([\d,]+\.?\d*)\s*profit", text, re.I)
    if profit_match:
        numbers["profit"] = float(profit_match.group(1).replace(",", ""))

    roi_match = re.search(r"([\d,]+\.?\d*)\s*%\s*roi", text, re.I)
    if roi_match:
        numbers["roi"] = float(roi_match.group(1).replace(",", ""))

    bsr_match = re.search(r"bsr[:\s#]*([0-9,]+)", text, re.I)
    if bsr_match:
        numbers["bsr"] = int(bsr_match.group(1).replace(",", ""))

    return numbers


def passes_profit_filter(text: str) -> tuple[bool, dict]:
    """Returns (passes, numbers_found). If no numbers found, passes by default."""
    nums = extract_numbers(text)
    if not nums:
        return True, nums   # no numbers → don't filter out

    profit_ok = nums.get("profit", MIN_PROFIT) >= MIN_PROFIT
    roi_ok    = nums.get("roi",    MIN_ROI)    >= MIN_ROI
    bsr_ok    = nums.get("bsr",    1)          <= MAX_BSR

    return profit_ok and roi_ok and bsr_ok, nums


# ── Alert email HTML ──────────────────────────────────────────────────────────
def build_alert_html(msg: discord.Message, reason: str, nums: dict) -> str:
    now    = datetime.now(EASTERN).strftime("%b %d %Y %I:%M %p ET")
    server = msg.guild.name if msg.guild else "Unknown Server"
    chan   = f"#{msg.channel.name}" if hasattr(msg.channel, "name") else ""
    author = str(msg.author.display_name)
    url    = msg.jump_url

    numbers_html = ""
    if nums:
        rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#888'>{k.upper()}</td>"
            f"<td style='padding:4px 0;font-weight:bold'>{v}</td></tr>"
            for k, v in nums.items()
        )
        numbers_html = f"<table style='margin:8px 0'>{rows}</table>"

    content = msg.content.replace("<", "&lt;").replace(">", "&gt;")
    # Highlight the triggering keyword
    import re
    content = re.sub(
        f"({re.escape(reason)})",
        r"<mark style='background:#fff3cd'>\1</mark>",
        content, flags=re.I
    )

    return f"""
<html><body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:20px">
<div style="background:#1a1a2e;color:white;padding:16px 20px;border-radius:8px 8px 0 0">
  <h2 style="margin:0;font-size:18px">🚨 ASTRUM Discord Alert</h2>
  <p style="margin:4px 0 0;opacity:.7;font-size:13px">{now}</p>
</div>
<div style="background:#f8f9fa;padding:16px 20px;border-left:4px solid #e63946">
  <p style="margin:0"><strong>Server:</strong> {server} &nbsp;|&nbsp; <strong>Channel:</strong> {chan}</p>
  <p style="margin:4px 0 0"><strong>Posted by:</strong> {author}</p>
  <p style="margin:4px 0 0"><strong>Triggered by:</strong> <code style="background:#e9ecef;padding:2px 6px;border-radius:4px">{reason}</code></p>
  {numbers_html}
</div>
<div style="background:white;padding:20px;border:1px solid #dee2e6;border-top:none;white-space:pre-wrap;font-size:14px;line-height:1.6">
{content}
</div>
<div style="padding:12px 20px;background:#f1f3f5;border-radius:0 0 8px 8px;font-size:13px">
  <a href="{url}" style="color:#1971c2;text-decoration:none">→ Jump to message in Discord</a>
</div>
</body></html>
"""


# ── Daily summary HTML ────────────────────────────────────────────────────────
def build_summary_html(entries: list[dict]) -> str:
    now = datetime.now(EASTERN).strftime("%B %d, %Y")

    if not entries:
        return f"""
<html><body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:20px">
<h2>📋 ASTRUM Daily Discord Summary — {now}</h2>
<p>No flagged activity today across monitored channels.</p>
</body></html>
"""

    # Group by category
    cats = {
        "🔄 Flips & Leads":       [],
        "🔓 Ungating":            [],
        "🤖 AI Tools":            [],
        "🛍️ OA Retailers":        [],
        "💻 Software Updates":    [],
        "🏆 Wins & Tips":         [],
        "📣 Other":               [],
    }

    def categorize(reason: str, text: str) -> str:
        r = reason.lower()
        t = text.lower()
        if any(k in r for k in ["flip","bolo","arbitrage","a2a","a to a","buy box","lead"]):
            return "🔄 Flips & Leads"
        if any(k in r for k in ["ungat","approved","gated","invoice"]):
            return "🔓 Ungating"
        if any(k in r for k in ["chatgpt","claude","gpt","gemini","copilot","ai tool","ai sourcing","ai leads","automation","ai finds"]):
            return "🤖 AI Tools"
        if any(k in r for k in ["walmart","target","home depot","lowes","costco","staples",
                                  "office depot","best buy","kohls","macys","nordstrom",
                                  "dick","academy","crocs","adidas","new balance"]):
            return "🛍️ OA Retailers"
        if any(k in r for k in ["source lens","sourcelens","keepa","asin.so","scanpower",
                                  "selleramp","tactical","oaxray","storefront","update","feature"]):
            return "💻 Software Updates"
        if any(k in t for k in ["win","success","approved","profit"]):
            return "🏆 Wins & Tips"
        return "📣 Other"

    for e in entries:
        cat = categorize(e["reason"], e["content"])
        cats[cat].append(e)

    sections = ""
    for cat, items in cats.items():
        if not items:
            continue
        rows = ""
        for e in items:
            snippet = e["content"][:200].replace("<","&lt;").replace(">","&gt;")
            if len(e["content"]) > 200:
                snippet += "…"
            rows += f"""
<tr>
  <td style="padding:10px;border-bottom:1px solid #f1f3f5;vertical-align:top;width:130px;color:#555;font-size:12px">
    {e['time']}<br><strong>{e['channel']}</strong><br><em>{e['author']}</em>
  </td>
  <td style="padding:10px;border-bottom:1px solid #f1f3f5;font-size:14px;line-height:1.5">
    {snippet}<br>
    <a href="{e['url']}" style="font-size:12px;color:#1971c2">→ View in Discord</a>
  </td>
</tr>"""

        sections += f"""
<h3 style="margin:24px 0 8px;color:#1a1a2e">{cat} <span style="font-weight:normal;font-size:14px;color:#888">({len(items)} item{'s' if len(items)!=1 else ''})</span></h3>
<table style="width:100%;border-collapse:collapse;background:white;border:1px solid #dee2e6;border-radius:8px">
{rows}
</table>"""

    return f"""
<html><body style="font-family:Arial,sans-serif;max-width:720px;margin:0 auto;padding:20px;color:#212529">
<div style="background:#1a1a2e;color:white;padding:20px;border-radius:8px 8px 0 0">
  <h1 style="margin:0;font-size:22px">📋 ASTRUM Daily Discord Summary</h1>
  <p style="margin:6px 0 0;opacity:.7">{now} &nbsp;·&nbsp; {len(entries)} flagged items across monitored channels</p>
</div>
<div style="padding:20px 0">
{sections}
</div>
<div style="background:#f8f9fa;padding:16px;border-radius:8px;font-size:13px;color:#666;margin-top:16px">
  Monitoring: OA Challenge+ &amp; The Amazon Launchpad &nbsp;·&nbsp;
  Filters: profit ≥$7 · ROI ≥50% · BSR ≤150,000 · US only
</div>
</body></html>
"""


# ── Discord events ────────────────────────────────────────────────────────────
@client.event
async def on_ready():
    print(f"✅ ASTRUM Monitor online as {client.user}")
    client.loop.create_task(daily_summary_scheduler())


@client.event
async def on_message(message: discord.Message):
    # Ignore bot's own messages
    if message.author.bot:
        return

    # Only watch specific channels
    channel_name = getattr(message.channel, "name", "")
    if channel_name not in WATCHED_CHANNELS:
        return

    text = message.content
    if not text.strip():
        return

    # Skip filtered content
    if should_skip(text):
        return

    # Check for alert keywords
    reason = get_alert_reason(text)
    if not reason:
        return

    # Check profit filter
    passes, nums = passes_profit_filter(text)
    if not passes:
        return

    now_et = datetime.now(EASTERN)

    # Log for daily summary
    daily_log.append({
        "time":    now_et.strftime("%I:%M %p"),
        "channel": f"#{channel_name}",
        "server":  message.guild.name if message.guild else "",
        "author":  message.author.display_name,
        "content": text,
        "reason":  reason,
        "url":     message.jump_url,
        "nums":    nums,
    })

    # Send real-time alert email
    try:
        subject = f"🚨 Discord Alert: {reason.title()} in #{channel_name}"
        html    = build_alert_html(message, reason, nums)
        send_email(subject, html)
        print(f"📧 Alert sent: {reason} in #{channel_name}")
    except Exception as e:
        print(f"❌ Email error: {e}")


# ── Daily summary scheduler ───────────────────────────────────────────────────
async def daily_summary_scheduler():
    global daily_log, last_summary_date

    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(EASTERN)
        today = now.strftime("%Y-%m-%d")

        if now.hour == DAILY_SUMMARY_HOUR and now.minute == 0 and today != last_summary_date:
            last_summary_date = today
            try:
                subject = f"📋 ASTRUM Daily Discord Summary — {now.strftime('%B %d, %Y')}"
                html    = build_summary_html(daily_log)
                send_email(subject, html)
                print(f"📧 Daily summary sent: {len(daily_log)} items")
                daily_log = []   # reset for next day
            except Exception as e:
                print(f"❌ Summary email error: {e}")

        await asyncio.sleep(60)   # check every minute


# ── Run ───────────────────────────────────────────────────────────────────────
client.run(DISCORD_TOKEN)
