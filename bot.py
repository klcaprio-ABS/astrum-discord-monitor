    """
ASTRUM Discord Monitor — browser-based scraper
Logs in as the user, reads watched channels, sends daily summary + real-time alerts.
"""

import os, asyncio, smtplib, json, re, subprocess, sys

# Install Chromium browser at startup (Railway doesn't persist build artifacts)
print("Installing Chromium...")
subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
subprocess.run([sys.executable, "-m", "playwright", "install-deps", "chromium"], check=False)
print("Chromium ready.")
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from playwright.async_api import async_playwright

# ── Config ────────────────────────────────────────────────────────────────────
DISCORD_EMAIL    = os.environ["DISCORD_EMAIL"]
DISCORD_PASSWORD = os.environ["DISCORD_PASSWORD"]
EMAIL_ADDRESS    = os.environ["EMAIL_ADDRESS"]      # klcaprio@hotmail.com
EMAIL_PASSWORD   = os.environ["EMAIL_PASSWORD"]      # outlook app password
ALERT_EMAIL      = os.environ["ALERT_EMAIL"]         # klcaprio@hotmail.com

EASTERN = timezone(timedelta(hours=-4))  # ET (adjust to -5 in Nov for EST)
DAILY_SUMMARY_HOUR = 18  # 6 PM ET

MIN_PROFIT = 7
MIN_ROI    = 50
MAX_BSR    = 150_000

# ── Channels to monitor: {server_id: [channel_ids or names]} ─────────────────
# We identify channels by name since IDs can change
WATCHED = {
    "OA Challenge+": [
        "2026-q3-leads", "2026-q4-leads", "flip-alert-leads", "deals-feed",
        "ai-chat", "announcements", "amazon-ecommerce-news",
        "source-lens-support", "asin-so-support", "discontinued-bolos",
        "wins", "guides-and-sops",
    ],
    "The Amazon Launchpad": [
        "ungating", "auto-ungate-asins", "sourcing-questions",
        "keepa-analysis", "software-questions", "announcements",
        "success", "retailers-that-cancel", "lessons-learned",
    ],
}

SKIP_KEYWORDS = [
    "canada", "canadian", "uk ", "united kingdom", "british", "£",
    "introduce yourself", "intro post", "just joined", "new member",
]

ALERT_KEYWORDS = [
    "flip", "ungate", "ungated", "ungating", "lead", "deal", "roi",
    "profit", "bsr", "keepa", "ai tool", "sourcelen", "asin.so",
    "software update", "retailer", "bolos", "restricted", "approve",
]

# ── Email helpers ─────────────────────────────────────────────────────────────
def send_email(subject: str, html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = ALERT_EMAIL
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP("smtp-mail.outlook.com", 587) as s:
        s.starttls()
        s.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        s.sendmail(EMAIL_ADDRESS, ALERT_EMAIL, msg.as_string())

def build_alert_html(server, channel, author, content, reason):
    return f"""
<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
<div style="background:#5865F2;padding:16px;border-radius:8px 8px 0 0">
  <h2 style="color:white;margin:0">🚨 ASTRUM Discord Alert</h2>
  <p style="color:#ddd;margin:4px 0 0">{reason}</p>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:16px;border-radius:0 0 8px 8px">
  <p><strong>Server:</strong> {server}<br>
     <strong>Channel:</strong> #{channel}<br>
     <strong>Posted by:</strong> {author}<br>
     <strong>Time:</strong> {datetime.now(EASTERN).strftime('%I:%M %p ET')}</p>
  <div style="background:#f5f5f5;padding:12px;border-left:4px solid #5865F2;border-radius:4px">
    {content}
  </div>
</div>
</body></html>"""

def build_summary_html(daily_log):
    if not daily_log:
        body = "<p>No qualifying posts captured today.</p>"
    else:
        rows = ""
        for item in daily_log:
            rows += f"""
            <tr>
              <td style="padding:8px;border-bottom:1px solid #eee">{item['time']}</td>
              <td style="padding:8px;border-bottom:1px solid #eee">{item['server']}</td>
              <td style="padding:8px;border-bottom:1px solid #eee">#{item['channel']}</td>
              <td style="padding:8px;border-bottom:1px solid #eee">{item['author']}</td>
              <td style="padding:8px;border-bottom:1px solid #eee">{item['reason']}</td>
              <td style="padding:8px;border-bottom:1px solid #eee;max-width:300px">{item['content'][:200]}{'...' if len(item['content'])>200 else ''}</td>
            </tr>"""
        body = f"""
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="background:#5865F2;color:white">
              <th style="padding:8px;text-align:left">Time</th>
              <th style="padding:8px;text-align:left">Server</th>
              <th style="padding:8px;text-align:left">Channel</th>
              <th style="padding:8px;text-align:left">Author</th>
              <th style="padding:8px;text-align:left">Category</th>
              <th style="padding:8px;text-align:left">Post</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""

    date_str = datetime.now(EASTERN).strftime("%B %d, %Y")
    return f"""
<html><body style="font-family:Arial,sans-serif;max-width:900px;margin:auto">
<div style="background:#5865F2;padding:16px;border-radius:8px 8px 0 0">
  <h2 style="color:white;margin:0">📋 ASTRUM Daily Discord Summary</h2>
  <p style="color:#ddd;margin:4px 0 0">{date_str} · {len(daily_log)} items captured</p>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:16px;border-radius:0 0 8px 8px">
  {body}
  <p style="color:#999;font-size:11px;margin-top:16px">
    Monitoring: OA Challenge+ &amp; The Amazon Launchpad ·
    Filters: profit ≥$7 · ROI ≥50% · BSR ≤150,000 · US only
  </p>
</div>
</body></html>"""

# ── Filtering ─────────────────────────────────────────────────────────────────
def should_skip(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in SKIP_KEYWORDS)

def get_alert_reason(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["flip", "amazon to amazon", "a2a"]):
        return "Amazon Flip"
    if any(k in t for k in ["ungate", "ungated", "ungating", "restricted", "approve"]):
        return "Ungating"
    if any(k in t for k in ["lead", "deal", "bolo", "profit", "roi", "bsr"]):
        return "OA Lead"
    if any(k in t for k in ["ai tool", "sourcelen", "asin.so", "software", "keepa"]):
        return "Tool/AI Update"
    if any(k in t for k in ["retailer", "source", "cancel"]):
        return "Retailer Intel"
    return ""

def passes_profit_filter(text: str) -> bool:
    """Return True if post passes profit/ROI/BSR filters OR has no numbers (cast wide net)."""
    t = text.lower()
    profits = [float(x) for x in re.findall(r'\$(\d+(?:\.\d+)?)', t)]
    rois    = [float(x) for x in re.findall(r'(\d+(?:\.\d+)?)\s*%', t)]
    bsrs    = [float(x.replace(',','')) for x in re.findall(r'bsr[:\s#]*([0-9,]+)', t)]

    if profits and max(profits) < MIN_PROFIT:
        return False
    if rois and max(rois) < MIN_ROI:
        return False
    if bsrs and min(bsrs) > MAX_BSR:
        return False
    return True

# ── Main scraper loop ─────────────────────────────────────────────────────────
async def run():
    daily_log       = []
    last_summary_date = ""
    seen_messages   = set()  # track message IDs to avoid duplicates

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        # ── Log in ────────────────────────────────────────────────────────────
        page = await context.new_page()
        print("🔐 Logging into Discord...")
        await page.goto("https://discord.com/login", wait_until="networkidle")
        await page.fill('input[name="email"]', DISCORD_EMAIL)
        await page.fill('input[name="password"]', DISCORD_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(5000)

        # Handle any 2FA / captcha by waiting up to 30s for the app to load
        try:
            await page.wait_for_selector('[class*="guilds"]', timeout=30000)
            print("✅ Logged in successfully")
        except:
            print("⚠️  Login may need manual action — check for captcha")

        # Save session cookies so we can restore if needed
        cookies = await context.cookies()
        with open("/tmp/discord_cookies.json", "w") as f:
            json.dump(cookies, f)

        # ── Build channel URL map ─────────────────────────────────────────────
        # Navigate to each server and collect channel URLs
        print("🗺️  Building channel map...")
        channel_urls = {}  # channel_name -> full discord URL

        for guild_name, channels in WATCHED.items():
            # Find the guild in the sidebar
            guild_el = await page.query_selector(f'[aria-label="{guild_name}"]')
            if not guild_el:
                # Try partial match
                all_guilds = await page.query_selector_all('[class*="listItem"] [class*="wrapper"]')
                for g in all_guilds:
                    label = await g.get_attribute("aria-label") or ""
                    if guild_name.lower() in label.lower():
                        guild_el = g
                        break

            if guild_el:
                await guild_el.click()
                await page.wait_for_timeout(2000)

                for ch_name in channels:
                    # Find channel link
                    ch_links = await page.query_selector_all('[class*="channel"] a[href*="/channels/"]')
                    for link in ch_links:
                        text = (await link.inner_text()).strip().lower()
                        if ch_name.lower().replace("-", " ") in text or ch_name.lower() in text:
                            href = await link.get_attribute("href")
                            if href:
                                channel_urls[f"{guild_name}::{ch_name}"] = f"https://discord.com{href}"
                                print(f"  ✅ Mapped {guild_name} :: #{ch_name}")
                            break
            else:
                print(f"  ⚠️  Could not find server: {guild_name}")

        print(f"📡 Monitoring {len(channel_urls)} channels")

        # ── Poll loop ─────────────────────────────────────────────────────────
        while True:
            now = datetime.now(EASTERN)

            # Check each channel
            for key, url in channel_urls.items():
                guild_name, ch_name = key.split("::")
                try:
                    await page.goto(url, wait_until="networkidle", timeout=15000)
                    await page.wait_for_timeout(2000)

                    # Get recent messages
                    messages = await page.query_selector_all('[class*="messageListItem"]')

                    for msg in messages[-20:]:  # last 20 messages
                        try:
                            msg_id = await msg.get_attribute("id") or ""
                            if msg_id in seen_messages:
                                continue
                            seen_messages.add(msg_id)

                            content_el = await msg.query_selector('[class*="messageContent"]')
                            author_el  = await msg.query_selector('[class*="username"]')

                            if not content_el:
                                continue

                            content = (await content_el.inner_text()).strip()
                            author  = (await author_el.inner_text()).strip() if author_el else "Unknown"

                            if not content or should_skip(content):
                                continue

                            reason = get_alert_reason(content)
                            if not reason:
                                continue

                            if not passes_profit_filter(content):
                                continue

                            # New qualifying message!
                            item = {
                                "time":    now.strftime("%I:%M %p"),
                                "server":  guild_name,
                                "channel": ch_name,
                                "author":  author,
                                "content": content,
                                "reason":  reason,
                            }
                            daily_log.append(item)
                            print(f"📌 [{reason}] {guild_name} #{ch_name}: {content[:60]}")

                            # Real-time alert
                            try:
                                subject = f"🚨 Discord Alert: {reason} in #{ch_name}"
                                html    = build_alert_html(guild_name, ch_name, author, content, reason)
                                send_email(subject, html)
                                print(f"📧 Alert sent")
                            except Exception as e:
                                print(f"❌ Alert email error: {e}")

                        except Exception as e:
                            print(f"  ⚠️  Message parse error: {e}")

                except Exception as e:
                    print(f"⚠️  Error reading {guild_name} #{ch_name}: {e}")

            # Keep seen_messages from growing forever
            if len(seen_messages) > 10000:
                seen_messages = set(list(seen_messages)[-5000:])

            # Daily summary at 6 PM ET
            today = now.strftime("%Y-%m-%d")
            if now.hour == DAILY_SUMMARY_HOUR and now.minute < 5 and today != last_summary_date:
                last_summary_date = today
                try:
                    subject = f"📋 ASTRUM Daily Discord Summary — {now.strftime('%B %d, %Y')}"
                    html    = build_summary_html(daily_log)
                    send_email(subject, html)
                    print(f"📧 Daily summary sent: {len(daily_log)} items")
                    daily_log = []
                except Exception as e:
                    print(f"❌ Summary email error: {e}")

            # Poll every 5 minutes
            print(f"💤 Sleeping 5 min... ({now.strftime('%I:%M %p ET')})")
            await asyncio.sleep(300)

asyncio.run(run())

    
