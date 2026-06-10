
India Non-Fossil Power Alert — Real-Time
-----------------------------------------
Data: npp.gov.in/dashBoard/demandmet2chartdata (live, ~4-min updates)
Alerts: Email via Gmail SMTP
Run: every 30 min via GitHub Actions
"""

import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

GENERATION_URL = "https://npp.gov.in/dashBoard/demandmet2chartdata"
STATE_FILE     = Path("last_alert.json")

EMAIL_FROM     = os.environ["EMAIL_FROM"]
EMAIL_TO       = os.environ["EMAIL_TO"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

SMTP_SERVER    = "smtp.gmail.com"
SMTP_PORT      = 587

ALERT_COOLDOWN_HOURS = 0
AVERAGE_DAYS         = 30

NON_FOSSIL = ["HYDRO", "NUCLEAR", "SOLAR", "WIND", "RENEWABLE", "RES",
              "SMALL HYDRO", "BIOMASS", "BAGASSE"]

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://npp.gov.in"}

# ── Fetch generation for a given date ────────────────────────────────────────

def fetch_generation(target_date: str) -> dict | None:
    try:
        resp = requests.get(GENERATION_URL, params={"date": target_date},
                            headers=HEADERS, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None

        latest = {}
        for row in rows:
            src = row["name_of_data"].replace(" GENERATION", "").strip().upper()
            ts  = row["updated_on"]
            if src not in latest or ts > latest[src]["ts"]:
                latest[src] = {"mw": float(row["value_of_data"]), "ts": ts}

        sources       = {k: v["mw"] for k, v in latest.items()}
        last_ts_ms    = max(v["ts"] for v in latest.values())
        timestamp     = datetime.fromtimestamp(last_ts_ms / 1000, tz=IST).strftime("%Y-%m-%d %H:%M IST")

        non_fossil_mw = sum(mw for src, mw in sources.items()
                            if any(nf in src for nf in NON_FOSSIL))
        fossil_mw     = sum(mw for src, mw in sources.items()
                            if not any(nf in src for nf in NON_FOSSIL))
        total_mw      = sum(sources.values())
        non_fossil_pct = (non_fossil_mw / total_mw * 100) if total_mw else 0

        return {
            "sources":        sources,
            "non_fossil_mw":  round(non_fossil_mw, 1),
            "fossil_mw":      round(fossil_mw, 1),
            "total_mw":       round(total_mw, 1),
            "non_fossil_pct": round(non_fossil_pct, 1),
            "timestamp":      timestamp,
        }
    except Exception as e:
        print(f"  Error fetching {target_date}: {e}")
        return None

# ── Historical average (last N days, same endpoint) ───────────────────────────

def fetch_average_mw(days: int = AVERAGE_DAYS) -> dict:
    print(f"Computing {days}-day historical average...")
    readings_mw  = []
    readings_pct = []

    for i in range(1, days + 1):
        d    = (datetime.now(IST) - timedelta(days=i)).strftime("%Y-%m-%d")
        data = fetch_generation(d)
        if data and data["non_fossil_mw"] > 0:
            readings_mw.append(data["non_fossil_mw"])
            readings_pct.append(data["non_fossil_pct"])

    if not readings_mw:
        return {"avg_mw": 0.0, "avg_pct": 0.0, "n_days": 0}

    avg_mw  = round(sum(readings_mw)  / len(readings_mw), 1)
    avg_pct = round(sum(readings_pct) / len(readings_pct), 1)
    print(f"Average from {len(readings_mw)} days: {avg_mw:,.0f} MW / {avg_pct:.1f}% non-fossil")
    return {"avg_mw": avg_mw, "avg_pct": avg_pct, "n_days": len(readings_mw)}

# ── State & cooldown ──────────────────────────────────────────────────────────

def load_state() -> dict:
    try:    return json.loads(STATE_FILE.read_text())
    except: return {"last_alert_time": None}

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state))

def in_cooldown(state: dict) -> bool:
    if not state.get("last_alert_time"):
        return False
    last    = datetime.fromisoformat(state["last_alert_time"])
    elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
    return elapsed < ALERT_COOLDOWN_HOURS

# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(data: dict, avg: dict, pct_vs_avg: float):
    sign = "+" if pct_vs_avg > 0 else ""
    rows = "\n".join(
        f"  {'[non-fossil]' if any(nf in src for nf in NON_FOSSIL) else '[fossil]   '} "
        f"{src.title()}: {mw:,.0f} MW"
        for src, mw in sorted(data["sources"].items(), key=lambda x: -x[1])
    )
    body = f"""India Non-Fossil Power Alert
{'='*45}
Time:                  {data['timestamp']}

Non-fossil generation: {data['non_fossil_mw']:,.0f} MW  ({data['non_fossil_pct']:.1f}% of total)
Fossil generation:     {data['fossil_mw']:,.0f} MW  ({100 - data['non_fossil_pct']:.1f}% of total)
Total generation:      {data['total_mw']:,.0f} MW

vs {AVERAGE_DAYS}-day average:
  Non-fossil MW:       {sign}{pct_vs_avg:.1f}% above average ({avg['avg_mw']:,.0f} MW avg)
  Non-fossil share:    {data['non_fossil_pct']:.1f}% today vs {avg['avg_pct']:.1f}% avg

Breakdown:
{rows}

Source: MERIT India / National Power Portal
"""
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = (f"India Power Alert: Non-fossil at {data['non_fossil_pct']:.1f}% "
                      f"of grid ({sign}{pct_vs_avg:.1f}% above avg)")
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

    print(f"✓ Email sent to {EMAIL_TO}")

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    state = load_state()
    if in_cooldown(state):
        print(f"In cooldown (last alert: {state['last_alert_time']}) — skipping.")
        return

    today = datetime.now(IST).strftime("%Y-%m-%d")
    print(f"Fetching live data for {today}...")
    data = fetch_generation(today)
    if not data:
        print("Failed to fetch live data.")
        return

    avg = fetch_average_mw()
    if avg["avg_mw"] == 0:
        print("Could not compute average — skipping.")
        return

    pct_vs_avg = ((data["non_fossil_mw"] - avg["avg_mw"]) / avg["avg_mw"]) * 100

    print(f"\n{'='*50}")
    print(f"Timestamp      : {data['timestamp']}")
    print(f"Non-fossil     : {data['non_fossil_mw']:,} MW  ({data['non_fossil_pct']:.1f}% of grid)")
    print(f"Fossil         : {data['fossil_mw']:,} MW  ({100 - data['non_fossil_pct']:.1f}% of grid)")
    print(f"Total          : {data['total_mw']:,} MW")
    print(f"30-day avg     : {avg['avg_mw']:,} MW  ({avg['avg_pct']:.1f}%)")
    print(f"vs average     : {pct_vs_avg:+.1f}%")
    print(f"{'='*50}\n")

    if data["non_fossil_mw"] > avg["avg_mw"]:
        print("Above average — sending email alert")
        try:
            send_email(data, avg, pct_vs_avg)
            state["last_alert_time"] = datetime.now(timezone.utc).isoformat()
            save_state(state)
        except Exception as e:
            print(f"Email error: {e}")
            raise
    else:
        print("Below average — no alert.")

if __name__ == "__main__":
    run()
