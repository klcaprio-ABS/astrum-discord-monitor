# ASTRUM Discord Monitor

Monitors OA Challenge+ and The Amazon Launchpad Discord servers.
Sends real-time email alerts and a daily 6pm ET summary to klcaprio@hotmail.com.

## Environment Variables Required in Railway

| Variable | Value |
|---|---|
| DISCORD_TOKEN | Your bot token |
| EMAIL_ADDRESS | klcaprio@hotmail.com |
| EMAIL_PASSWORD | Your Outlook app password |
| ALERT_EMAIL | klcaprio@hotmail.com |

## Alert Criteria
- Profit ≥ $7
- ROI ≥ 50%
- BSR ≤ 150,000
- US content only
