import yfinance as yf
import datetime
import json
import os
import urllib.request
import urllib.parse

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

# Load FMP key from environment variable (set as a GitHub Actions secret)
# In your repo: Settings → Secrets → Actions → New repository secret
# Name: FMP_API_KEY   Value: your key
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")

# Sanity-check bounds for commodity prices (to catch stale/bad yfinance data)
SANITY_BOUNDS = {
    "GC=F":   (1000, 5000),   # Gold futures $/oz
    "CL=F":   (20,   200),    # Crude Oil $/bbl
    "BTC-USD":(1000, 500000),
    "ETH-USD":(50,   50000),
    "SOL-USD":(1,    10000),
    "XRP-USD":(0.01, 100),
    "^GSPC":  (1000, 20000),
    "^IXIC":  (1000, 50000),
    "^DJI":   (5000, 200000),
    "^RUT":   (500,  10000),
    "^VIX":   (5,    150),
    "^TNX":   (0.1,  20),
    "^IRX":   (0.0,  20),
    "DX-Y.NYB":(50, 200),
}

# ETF fallbacks for problematic continuous futures
FALLBACKS = {
    "GC=F": "GLD",
    "CL=F": "USO",
}


# ─────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────

def is_sane(ticker_symbol, value):
    """Returns True if value is within expected bounds for a ticker."""
    if ticker_symbol not in SANITY_BOUNDS:
        return True
    lo, hi = SANITY_BOUNDS[ticker_symbol]
    return lo <= value <= hi


def fetch_weekly_data(ticker_symbol):
    """
    Fetches 6 days of data to get the previous Friday close, then returns
    the 5-day chart and WTD math. Falls back to ETF proxy if primary fails
    sanity check. Returns a dict with keys: dates, closes, end_price,
    pct_change, abs_change, ticker_used, error.
    """
    tickers_to_try = [ticker_symbol]
    if ticker_symbol in FALLBACKS:
        tickers_to_try.append(FALLBACKS[ticker_symbol])

    for tk in tickers_to_try:
        try:
            ticker = yf.Ticker(tk)
            hist = ticker.history(period="6d")

            if len(hist) < 2:
                continue

            prev_close = hist['Close'].iloc[0]
            chart_hist = hist.iloc[-5:]
            dates = [d.strftime('%a %m/%d') for d in chart_hist.index]
            closes = [round(float(val), 2) for val in chart_hist['Close'].tolist()]
            end_price = closes[-1]

            # Sanity check end price
            if not is_sane(tk, end_price):
                print(f"  ⚠ Sanity check FAILED for {tk}: end_price={end_price} — trying fallback")
                continue

            pct_change = ((end_price - prev_close) / prev_close) * 100 if prev_close != 0 else 0.0
            abs_change = end_price - prev_close

            return {
                "dates": dates,
                "closes": closes,
                "end_price": end_price,
                "pct_change": round(pct_change, 2),
                "abs_change": round(abs_change, 2),
                "ticker_used": tk,
                "error": None,
            }

        except Exception as e:
            print(f"  ⚠ Exception fetching {tk}: {e}")
            continue

    # All attempts failed — return zeroed-out sentinel
    print(f"  ✗ All fetch attempts failed for {ticker_symbol}. Using zeroed data.")
    return {
        "dates": [],
        "closes": [],
        "end_price": 0.0,
        "pct_change": 0.0,
        "abs_change": 0.0,
        "ticker_used": ticker_symbol,
        "error": f"Data unavailable for {ticker_symbol}",
    }


def d(result, key="end_price"):
    return result[key]


# ─────────────────────────────────────────────
# FMP ECONOMIC CALENDAR — SECTION 08 GENERATOR
# Fetches real scheduled events for next week,
# categorises them, and builds 4 HTML-ready cells.
# Falls back to rule-based copy if API call fails.
# ─────────────────────────────────────────────

# Keywords used to route each event into a cell
_FED_KEYWORDS = [
    "fed", "fomc", "federal reserve", "powell", "waller", "williams",
    "jefferson", "cook", "kashkari", "bostic", "daly", "barkin",
    "kugler", "musalem", "collins", "goolsbee", "balance sheet",
    "interest rate decision", "monetary policy",
]
_EARNINGS_KEYWORDS = [
    "earnings", "eps", "revenue", "guidance", "results", "quarterly",
]
_RISK_KEYWORDS = [
    "geopolit", "opec", "tariff", "trade", "debt ceiling", "auction",
    "treasury auction", "bond auction", "default", "sanction",
    "election", "referendum", "central bank", "ecb", "boj", "boe",
    "pboc", "imf", "world bank",
]
# Everything else (CPI, PPI, NFP, GDP, retail sales, etc.) → macro cell

# Impact labels FMP returns: "High", "Medium", "Low"
_MIN_IMPACT = {"High", "Medium"}


def _fetch_fmp_calendar(from_date: str, to_date: str) -> list:
    """
    Calls FMP /economic_calendar endpoint and returns a list of event dicts.
    Each dict has keys: date, event, country, impact, actual, estimate, previous.
    Returns [] on any failure.
    """
    if not FMP_API_KEY:
        print("  ⚠ FMP_API_KEY not set — skipping calendar fetch.")
        return []

    params = urllib.parse.urlencode({
        "from": from_date,
        "to": to_date,
        "apikey": FMP_API_KEY,
    })
    url = f"https://financialmodelingprep.com/api/v3/economic_calendar?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "market-summary-bot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list):
            # Keep only US events at Medium/High impact
            filtered = [
                e for e in data
                if e.get("country", "").upper() in ("US", "USD", "")
                and e.get("impact", "Low") in _MIN_IMPACT
            ]
            print(f"  ✓ FMP returned {len(data)} events, {len(filtered)} US medium/high impact.")
            return filtered
        print(f"  ⚠ Unexpected FMP response type: {type(data)}")
        return []
    except Exception as e:
        print(f"  ⚠ FMP calendar fetch failed: {e}")
        return []


def _categorise_events(events: list) -> dict[str, list]:
    """
    Routes each event into one of four buckets based on keyword matching.
    Returns {"macro": [...], "fed": [...], "earnings": [...], "risk": [...]}.
    """
    buckets = {"macro": [], "fed": [], "earnings": [], "risk": []}
    for e in events:
        name_lower = e.get("event", "").lower()
        if any(k in name_lower for k in _FED_KEYWORDS):
            buckets["fed"].append(e)
        elif any(k in name_lower for k in _EARNINGS_KEYWORDS):
            buckets["earnings"].append(e)
        elif any(k in name_lower for k in _RISK_KEYWORDS):
            buckets["risk"].append(e)
        else:
            buckets["macro"].append(e)
    return buckets


def _fmt_event_list(events: list, max_items: int = 5) -> str:
    """Formats a list of events into a compact readable string for the cell."""
    lines = []
    seen = set()
    for e in events[:max_items * 2]:  # over-fetch then dedupe
        name = e.get("event", "").strip()
        date_str = e.get("date", "")[:10]  # "YYYY-MM-DD"
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            label = dt.strftime("%a %b ") + str(dt.day)
        except ValueError:
            label = date_str
        impact = e.get("impact", "")
        impact_tag = " ★" if impact == "High" else ""
        lines.append(f"{label}: {name}{impact_tag}")
        if len(lines) >= max_items:
            break
    return " · ".join(lines) if lines else ""


def _fallback_cell(cell: str, market_context: dict) -> str:
    """Returns a generic fallback string for a given cell if FMP has no data."""
    tnx = market_context["tnx_close"]
    vix = market_context["vix_close"]
    bot1 = market_context["bottom_sectors"].split(", ")[0]
    top1 = market_context["top_sectors"].split(", ")[0]
    fallbacks = {
        "macro": (
            f"Investors will monitor upcoming inflation and labor market prints for "
            f"direction on the consumer backdrop. Given the 10-year at {tnx:.2f}%, "
            f"any upside surprise in price data could reignite rate pressure on "
            f"rate-sensitive names like those in {bot1}."
        ),
        "fed": (
            f"The Fed remains data-dependent with yields at {tnx:.2f}%. Scheduled "
            f"FOMC member speeches will be parsed for consensus on the rate path — "
            f"any hawkish lean could trigger another leg of pressure on growth equities."
        ),
        "earnings": (
            f"Earnings season continues with sector rotation firmly in focus. "
            f"Reports from {top1} constituents will be watched for guidance "
            f"confirmation, while results from lagging sectors will be scrutinised "
            f"for signs of stabilisation."
        ),
        "risk": (
            f"With the VIX at {vix:.2f}, the market is {'pricing elevated tail risk' if vix >= 20 else 'relatively complacent'}. "
            f"Geopolitical developments, surprise macro data, and any Fed communication "
            f"shift remain the primary exogenous risk factors heading into the new week."
        ),
    }
    return fallbacks.get(cell, "")


def generate_lookahead_fmp(market_context: dict) -> dict:
    """
    Fetches next week's FMP economic calendar and builds four Section 08 cells.
    Falls back to rule-based text per-cell if a bucket has no events.
    """
    # Calculate next Mon–Fri date range
    today = datetime.date.today()
    days_until_monday = (7 - today.weekday()) % 7 or 7
    next_monday = today + datetime.timedelta(days=days_until_monday)
    next_friday = next_monday + datetime.timedelta(days=4)
    from_str = next_monday.strftime("%Y-%m-%d")
    to_str   = next_friday.strftime("%Y-%m-%d")
    print(f"  Fetching FMP calendar: {from_str} → {to_str}")

    events   = _fetch_fmp_calendar(from_str, to_str)
    buckets  = _categorise_events(events)

    tnx      = market_context["tnx_close"]
    tnx_pct  = market_context["tnx_pct"]
    vix      = market_context["vix_close"]
    top1     = market_context["top_sectors"].split(", ")[0]
    bot1     = market_context["bottom_sectors"].split(", ")[0]
    sp_pct   = market_context["sp_pct"]

    # ── MACRO CELL ───────────────────────────────
    macro_events = _fmt_event_list(buckets["macro"])
    if macro_events:
        yield_context = (
            f"rising yield environment ({tnx:.2f}%, +{abs(tnx_pct):.0f}bps WTD)" if tnx_pct > 0.03
            else f"easing yield backdrop ({tnx:.2f}%, {tnx_pct:.0f}bps WTD)" if tnx_pct < -0.03
            else f"stable rate backdrop ({tnx:.2f}%)"
        )
        macro = (
            f"Key data on the calendar: {macro_events}. "
            f"These releases land in a {yield_context}, meaning any upside surprise "
            f"on inflation or labour data carries outsized repricing risk for rate-sensitive "
            f"sectors like {bot1} that already underperformed this week."
        )
    else:
        macro = _fallback_cell("macro", market_context)

    # ── FED CELL ─────────────────────────────────
    fed_events = _fmt_event_list(buckets["fed"])
    if fed_events:
        if tnx > 4.25:
            fed_tone = "restrictive territory — markets will parse every word for pivot signals"
        elif tnx > 3.75:
            fed_tone = "a data-dependent range — tone consistency across speakers will be key"
        else:
            fed_tone = "accommodative levels — any hawkish surprise could rapidly reprice risk"
        fed = (
            f"Fed calendar: {fed_events}. "
            f"With the 10-year at {tnx:.2f}% — {fed_tone} — "
            f"any divergence between hawkish regional presidents and a more measured Chair "
            f"can move rate futures meaningfully and spill into equity sector rotation."
        )
    else:
        fed = _fallback_cell("fed", market_context)

    # ── EARNINGS & CATALYSTS CELL ─────────────────
    earn_events = _fmt_event_list(buckets["earnings"])
    if earn_events:
        earn = (
            f"Earnings on deck: {earn_events}. "
            f"Given this week's rotation into {top1} and out of {bot1}, "
            f"guidance and forward commentary will matter more than the backward-looking "
            f"beats — investors will be looking for demand confirmation in the leading sectors "
            f"and any green shoots of stabilisation in the laggards."
        )
    else:
        earn = _fallback_cell("earnings", market_context)

    # ── RISK FACTORS CELL ────────────────────────
    risk_events = _fmt_event_list(buckets["risk"])
    vix_context = (
        f"elevated VIX ({vix:.2f}) already flagging hedging demand" if vix >= 22
        else f"moderate VIX ({vix:.2f}) — complacency worth watching" if vix >= 16
        else f"suppressed VIX ({vix:.2f}) — market structurally underhedged"
    )
    if risk_events:
        risk = (
            f"Risk events to monitor: {risk_events}. "
            f"Against a backdrop of {vix_context}, these scheduled catalysts have "
            f"the potential to amplify {'the existing bearish momentum' if sp_pct < 0 else 'any reversal of this week\'s gains'} "
            f"if they surprise in a hawkish or risk-off direction."
        )
    else:
        risk = _fallback_cell("risk", market_context)

    print("  ✓ Section 08 built from FMP economic calendar.")
    return {
        "macro":                  macro,
        "fed_policy":             fed,
        "earnings_and_catalysts": earn,
        "risk_factors":           risk,
    }


# ─────────────────────────────────────────────
# FORMATTING HELPERS
# ─────────────────────────────────────────────

def fmt_date(dt, include_day=True):
    """Cross-platform date formatting without %-d (Linux-only)."""
    if include_day:
        return f"{dt.strftime('%b')} {dt.day}"
    return f"{dt.strftime('%B')} {dt.day}, {dt.strftime('%Y')}"


def fmt_chg(pct, abs_val=None, is_yield=False, is_points=False):
    sign = "+" if pct >= 0 else ""
    color = "pos" if pct >= 0 else "neg"
    arrow = "▲" if pct >= 0 else "▼"

    if is_yield and abs_val is not None:
        # abs_val is in percentage-point terms (e.g. 0.11 = 11 bps)
        bps = round(abs(abs_val) * 100)
        return f'<div class="t-chg {color}">{arrow} {sign}{bps} bps WTD</div>'
    elif is_points and abs_val is not None:
        return f'<div class="t-chg {color}">{arrow} {sign}{int(abs_val)} pts WTD</div>'
    else:
        return f'<div class="t-chg {color}">{arrow} {sign}{pct}% WTD</div>'


def get_t_item(name, val, pct, is_yield=False, abs_val=None, is_points=False):
    return f'''
    <div class="t-item">
      <div class="t-name">{name}</div>
      <div class="t-val">{val}</div>
      {fmt_chg(pct, abs_val=abs_val, is_yield=is_yield, is_points=is_points)}
    </div>'''


# ─────────────────────────────────────────────
# MAIN REPORT GENERATOR
# ─────────────────────────────────────────────

def generate_html():
    print("Fetching market data...")

    # ── Major Indices ──────────────────────────────────────────
    sp  = fetch_weekly_data('^GSPC')
    nd  = fetch_weekly_data('^IXIC')
    dj  = fetch_weekly_data('^DJI')
    rut = fetch_weekly_data('^RUT')
    vix = fetch_weekly_data('^VIX')
    tnx = fetch_weekly_data('^TNX')
    irx = fetch_weekly_data('^IRX')
    dxy = fetch_weekly_data('DX-Y.NYB')

    # ── Commodities & Crypto ───────────────────────────────────
    gold = fetch_weekly_data('GC=F')
    oil  = fetch_weekly_data('CL=F')
    btc  = fetch_weekly_data('BTC-USD')
    eth  = fetch_weekly_data('ETH-USD')
    sol  = fetch_weekly_data('SOL-USD')
    xrp  = fetch_weekly_data('XRP-USD')

    # ── Global ─────────────────────────────────────────────────
    n225  = fetch_weekly_data('^N225')
    stoxx = fetch_weekly_data('^STOXX50E')

    # ── Date Range (from live S&P data) ───────────────────────
    if sp["dates"]:
        # Parse dates back from the formatted strings for display
        sp_ticker = yf.Ticker('^GSPC')
        sp_hist = sp_ticker.history(period="5d")
        start_dt = sp_hist.index[0].to_pydatetime()
        end_dt   = sp_hist.index[-1].to_pydatetime()
        week_start_str = fmt_date(start_dt)
        today_str      = fmt_date(end_dt)
        year_str       = end_dt.strftime('%Y')
        full_date      = f"{end_dt.strftime('%B')} {end_dt.day}, {year_str}"
        week_end_date  = full_date
    else:
        now = datetime.datetime.now()
        week_start_str = fmt_date(now - datetime.timedelta(days=4))
        today_str      = fmt_date(now)
        year_str       = now.strftime('%Y')
        full_date      = f"{now.strftime('%B')} {now.day}, {year_str}"
        week_end_date  = full_date

    # ── Sectors ────────────────────────────────────────────────
    sectors = {
        'Technology (XLK)': 'XLK', 'Financials (XLF)': 'XLF',
        'Energy (XLE)': 'XLE', 'Healthcare (XLV)': 'XLV',
        'Industrials (XLI)': 'XLI', 'Cons. Discretionary (XLY)': 'XLY',
        'Cons. Staples (XLP)': 'XLP', 'Real Estate (XLRE)': 'XLRE',
        'Utilities (XLU)': 'XLU', 'Materials (XLB)': 'XLB',
        'Comm. Services (XLC)': 'XLC'
    }
    sector_perf = {}
    for name, ticker in sectors.items():
        r = fetch_weekly_data(ticker)
        sector_perf[name] = r["pct_change"]

    sorted_sectors = sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)
    top_sectors    = sorted_sectors[:4]
    bottom_sectors = sorted_sectors[-4:]

    # ── Mega Caps ──────────────────────────────────────────────
    mega_caps = {
        'AAPL': 'Apple', 'MSFT': 'Microsoft', 'NVDA': 'Nvidia',
        'AMZN': 'Amazon', 'META': 'Meta Platforms'
    }
    mega_cap_html = ""
    for tk, name in mega_caps.items():
        r = fetch_weekly_data(tk)
        c_close, c_pct = r["end_price"], r["pct_change"]
        c_color = "pos" if c_pct >= 0 else "neg"
        c_arrow = "▲" if c_pct >= 0 else "▼"
        c_sign  = "+" if c_pct >= 0 else ""
        err_note = f' <span style="color:var(--red);font-size:10px;">(data error)</span>' if r["error"] else ""
        mega_cap_html += f'''
        <div class="co-row">
          <span class="tkr">{tk}</span>
          <div class="co-desc"><strong>{name}</strong>{err_note} closed the week at ${c_close:,.2f}. As a core mega-cap weight, its {c_sign}{c_pct}% weekly move directly drove structural flows in the broader technology sector and index momentum.</div>
          <span class="co-mv {c_color}">{c_arrow} {c_sign}{c_pct}%</span>
        </div>'''

    # ── Section 08 — FMP economic calendar ────────────────────
    print("Generating Section 08 from FMP economic calendar...")
    lookahead = generate_lookahead_fmp({
        "sp_pct":       sp["pct_change"],
        "nd_pct":       nd["pct_change"],
        "vix_close":    vix["end_price"],
        "tnx_close":    tnx["end_price"],
        "tnx_pct":      tnx["pct_change"],
        "dxy_close":    dxy["end_price"],
        "dxy_pct":      dxy["pct_change"],
        "top_sectors":  ", ".join([s[0] for s in top_sectors[:2]]),
        "bottom_sectors": ", ".join([s[0] for s in bottom_sectors[:2]]),
        "btc_pct":      btc["pct_change"],
        "oil_pct":      oil["pct_change"],
        "gold_pct":     gold["pct_change"],
        "week_end_date": week_end_date,
    })

    # ── Ticker Bar ─────────────────────────────────────────────
    t_items = ""
    t_items += get_t_item("S&P 500",     f"{sp['end_price']:,.2f}",       sp["pct_change"])
    t_items += get_t_item("Nasdaq",      f"{nd['end_price']:,.2f}",       nd["pct_change"])
    t_items += get_t_item("DJIA",        f"{dj['end_price']:,.2f}",       dj["pct_change"], abs_val=dj["abs_change"], is_points=True)
    t_items += get_t_item("Russell 2000",f"{rut['end_price']:,.2f}",      rut["pct_change"])
    t_items += get_t_item("Crude Oil",   f"${oil['end_price']:,.2f}",     oil["pct_change"])
    t_items += get_t_item("Gold",        f"${gold['end_price']:,.2f}",    gold["pct_change"])
    t_items += get_t_item("VIX",         f"{vix['end_price']:,.2f}",      vix["pct_change"])
    t_items += get_t_item("Bitcoin",     f"${btc['end_price']:,.0f}",     btc["pct_change"])
    t_items += get_t_item("Ethereum",    f"${eth['end_price']:,.0f}",     eth["pct_change"])
    t_items += get_t_item("10-Yr Yield", f"{tnx['end_price']:,.2f}%",     tnx["pct_change"], abs_val=tnx["abs_change"], is_yield=True)
    ticker_html = f'<div class="ticker-wrapper"><div class="ticker-track">{t_items}{t_items}</div></div>'

    # ── Dynamic Badges & Takeaway ──────────────────────────────
    sp_pct = sp["pct_change"]
    market_tone = "▲ Risk-On / Rally" if sp_pct >= 0 else "⬇ Risk-Off / Pullback"
    badge_color = "badge-green" if sp_pct >= 0 else "badge-red"

    sp_card_class = "up" if sp_pct >= 0 else ""
    nd_card_class = "up" if nd["pct_change"] >= 0 else ""
    dj_card_class = "up" if dj["pct_change"] >= 0 else ""

    top_tags = "".join([f'<span class="tag g">{s[0]} ({"+" if s[1]>=0 else ""}{s[1]}%)</span>' for s in top_sectors])
    bot_tags = "".join([f'<span class="tag r">{s[0]} ({"+" if s[1]>=0 else ""}{s[1]}%)</span>' for s in bottom_sectors])

    vix_close = vix["end_price"]
    tnx_pct   = tnx["pct_change"]

    if sp_pct >= 0:
        if tnx_pct > 0:
            takeaway_text = f"The broader market demonstrated impressive resilience this week, advancing despite a backup in Treasury yields. Capital continued to flow into risk assets, signaling that underlying economic growth expectations are currently overpowering interest rate fears. The structural rotation into {top_sectors[0][0]} and {top_sectors[1][0]} suggests institutional participants remain constructive, choosing to buy dips and reallocate rather than retreat to cash."
        else:
            takeaway_text = f"A highly constructive week for risk assets as easing Treasury yields provided a strong macroeconomic tailwind for equity valuations. The market's tone remained firmly risk-on, with capital actively seeking yield and momentum. Institutional flows heavily favored {top_sectors[0][0]}, reinforcing the narrative that portfolio managers are comfortable extending risk exposure in a supportive liquidity environment."
    else:
        if vix_close >= 20:
            takeaway_text = f"This week's price action was characterized by a sharp defensive rotation and a spike in hedging activity, with the VIX pushing to {vix_close:,.2f}. Investors aggressively de-risked portfolios, shedding exposure in {bottom_sectors[0][0]} and moving capital toward the relative safety of {top_sectors[0][0]}. The dominant theme was capital preservation as the market rapidly recalibrated to shifting macroeconomic headwinds."
        else:
            takeaway_text = f"The market experienced a methodical, orderly pullback this week rather than outright panic. With the VIX remaining relatively subdued at {vix_close:,.2f}, the price action reflected healthy profit-taking and a rotation out of extended valuations. Portfolio managers tactically trimmed {bottom_sectors[0][0]} while hiding out in {top_sectors[0][0]}, signaling a cautious 'wait-and-see' approach rather than a structural shift to bearishness."

    # ── Crypto display ─────────────────────────────────────────
    def crypto_cell(label, result, fmt=".0f"):
        p = result["end_price"]
        pct = result["pct_change"]
        color = "pos" if pct >= 0 else "neg"
        arrow = "▲" if pct >= 0 else "▼"
        price_str = f"${p:,.{fmt.strip('.'+'f')}f}" if fmt == ".0f" else f"${p:,.4f}"
        return f'''
      <div class="cc">
        <div class="cc-name">{label}</div>
        <div class="cc-price">{price_str}</div>
        <div class="cc-chg {color}">{arrow} {abs(pct)}% WTD</div>
      </div>'''

    sp_dates = sp["dates"]
    sp_data  = sp["closes"]

    # ── Build Full HTML ────────────────────────────────────────
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Weekly Market Summary – {week_start_str}–{today_str}, {year_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #09090f;
    --surface: #10121a;
    --surface2: #181b26;
    --border: #1c1f2e;
    --accent: #e8c84a;
    --accent2: #4a9eff;
    --red: #f05b5b;
    --green: #3dd68c;
    --text: #dde1ee;
    --muted: #5c6480;
    --label: #8b94b2;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 300;
    line-height: 1.65;
  }}
  ::-webkit-scrollbar {{ width: 8px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background: var(--surface2); border-radius: 4px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--muted); }}

  .top-nav-wrapper {{
    position: sticky; top: 0; z-index: 1000;
    background: rgba(9, 9, 15, 0.85);
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--border);
  }}
  .masthead {{ padding: 32px 64px 24px; position: relative; overflow: hidden; }}
  .masthead::before {{ content: ''; position: absolute; top: -80px; right: -100px; width: 500px; height: 500px; background: radial-gradient(circle, rgba(232,200,74,0.06) 0%, transparent 65%); pointer-events: none; }}
  .masthead-row {{ display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 24px; }}
  .kicker {{ font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }}
  .week-title {{ font-family: 'Playfair Display', serif; font-size: clamp(26px, 3.5vw, 42px); font-weight: 900; line-height: 1.05; letter-spacing: -0.025em; color: #fff; }}
  .week-title span {{ color: var(--accent); }}
  .masthead-meta {{ text-align: right; }}
  .badge {{ display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.14em; text-transform: uppercase; padding: 5px 12px; border-radius: 2px; margin-bottom: 8px; }}
  .badge-red {{ background: rgba(240,91,91,0.1); border: 1px solid rgba(240,91,91,0.28); color: var(--red); }}
  .badge-green {{ background: rgba(61,214,140,0.1); border: 1px solid rgba(61,214,140,0.28); color: var(--green); }}
  .pub-date {{ font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--muted); }}

  .ticker-wrapper {{ border-top: 1px solid var(--border); overflow: hidden; white-space: nowrap; display: flex; align-items: center; background: rgba(16, 18, 26, 0.5); }}
  .ticker-track {{ display: inline-flex; align-items: center; animation: scrollTicker 45s linear infinite; }}
  .ticker-track:hover {{ animation-play-state: paused; }}
  @keyframes scrollTicker {{ 0% {{ transform: translateX(0); }} 100% {{ transform: translateX(-50%); }} }}
  .t-item {{ display: inline-flex; flex-direction: column; gap: 2px; padding: 12px 36px; min-width: max-content; position: relative; }}
  .t-item::after {{ content: ''; position: absolute; right: 0; top: 50%; transform: translateY(-50%); width: 1px; height: 38px; background: var(--border); }}
  .t-name {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.16em; color: var(--muted); text-transform: uppercase; }}
  .t-val {{ font-family: 'IBM Plex Mono', monospace; font-size: 14px; font-weight: 500; color: #fff; }}
  .t-chg {{ font-family: 'IBM Plex Mono', monospace; font-size: 10px; }}
  .neg {{ color: var(--red); }} .pos {{ color: var(--green); }}

  .container {{ max-width: 1120px; margin: 0 auto; padding: 0 64px 90px; }}
  .section {{ margin-top: 60px; padding-top: 56px; border-top: 1px solid var(--border); }}
  .section:first-child {{ border-top: none; padding-top: 40px; margin-top: 20px; }}
  .sec-label {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.26em; text-transform: uppercase; color: var(--accent); margin-bottom: 6px; }}
  .sec-title {{ font-family: 'Playfair Display', serif; font-size: 23px; font-weight: 700; color: #fff; margin-bottom: 28px; }}

  .idx-grid {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 2px; margin-bottom: 28px; }}
  .idx-card {{ background: var(--surface); padding: 26px; position: relative; overflow: hidden; }}
  .idx-card::after {{ content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 2px; background: var(--red); }}
  .idx-card.up::after {{ background: var(--green); }}
  .idx-name {{ font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.15em; color: var(--muted); text-transform: uppercase; margin-bottom: 8px; }}
  .idx-close {{ font-family: 'Playfair Display', serif; font-size: 28px; font-weight: 700; color: #fff; margin-bottom: 3px; }}
  .idx-wtd {{ font-family: 'IBM Plex Mono', monospace; font-size: 12px; margin-bottom: 6px; }}
  .idx-note {{ font-size: 11.5px; color: var(--label); line-height: 1.5; }}

  .blist {{ list-style: none; display: flex; flex-direction: column; gap: 11px; }}
  .blist li {{ padding-left: 20px; position: relative; font-size: 13.5px; color: #bcc3d6; line-height: 1.65; }}
  .blist li::before {{ content: '—'; position: absolute; left: 0; color: var(--accent); font-family: 'IBM Plex Mono', monospace; }}
  .blist li strong {{ color: var(--text); font-weight: 600; }}

  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 40px; }}
  .col-lbl {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; margin-bottom: 12px; }}
  .col-lbl.lead {{ color: var(--green); }} .col-lbl.lag {{ color: var(--red); }}
  .tag-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }}
  .tag {{ font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; padding: 4px 10px; border-radius: 2px; border: 1px solid; }}
  .tag.g {{ background: rgba(61,214,140,.07); border-color: rgba(61,214,140,.22); color: var(--green); }}
  .tag.r {{ background: rgba(240,91,91,.07); border-color: rgba(240,91,91,.22); color: var(--red); }}

  .data-row {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap: 2px; margin-bottom: 26px; }}
  .dcell {{ background: var(--surface); padding: 20px 22px; }}
  .dc-lbl {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.15em; color: var(--muted); text-transform: uppercase; margin-bottom: 4px; }}
  .dc-val {{ font-family: 'IBM Plex Mono', monospace; font-size: 17px; font-weight: 500; color: #fff; margin-bottom: 2px; }}
  .dc-val.hot {{ color: var(--red); }} .dc-val.warm {{ color: var(--accent); }} .dc-val.cool {{ color: var(--green); }}
  .dc-note {{ font-size: 11px; color: var(--label); line-height: 1.45; }}

  .co-row {{ display: flex; align-items: flex-start; gap: 14px; padding: 15px 0; border-bottom: 1px solid var(--border); }}
  .co-row:last-child {{ border-bottom: none; }}
  .tkr {{ font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 500; background: var(--surface2); border: 1px solid var(--border); padding: 4px 9px; min-width: 66px; text-align: center; flex-shrink: 0; margin-top: 1px; border-radius: 2px; color: #fff; }}
  .co-desc {{ font-size: 13.5px; color: #bcc3d6; line-height: 1.55; flex: 1; }}
  .co-mv {{ font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; flex-shrink: 0; margin-top: 2px; font-weight: 500; }}

  .crypto-grid {{ display: grid; grid-template-columns: repeat(2,1fr); gap: 2px; margin-bottom: 26px; }}
  .cc {{ background: var(--surface); padding: 20px 22px; }}
  .cc-name {{ font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.12em; color: var(--muted); text-transform: uppercase; margin-bottom: 6px; }}
  .cc-price {{ font-family: 'Playfair Display', serif; font-size: 21px; font-weight: 700; color: #fff; margin-bottom: 3px; }}
  .cc-chg {{ font-family: 'IBM Plex Mono', monospace; font-size: 11px; }}

  .gtable {{ width: 100%; border-collapse: collapse; }}
  .gtable th {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase; color: var(--muted); padding: 9px 16px; text-align: left; border-bottom: 1px solid var(--border); }}
  .gtable td {{ padding: 13px 16px; font-size: 13px; color: #bcc3d6; border-bottom: 1px solid var(--border); vertical-align: top; }}
  .gtable tr:last-child td {{ border-bottom: none; }}
  .gtable td:first-child {{ font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 500; color: #fff; white-space: nowrap; }}
  .gtable td:nth-child(2) {{ font-family: 'IBM Plex Mono', monospace; font-size: 11px; width: 110px; }}

  .takeaway {{ background: var(--surface); border-left: 3px solid var(--accent); padding: 30px 34px; font-size: 14.5px; color: #d0d5e8; line-height: 1.8; font-style: italic; }}

  .ahead-grid {{ display: grid; grid-template-columns: repeat(2,1fr); gap: 2px; }}
  .ahead-cell {{ background: var(--surface); padding: 20px 22px; }}
  .ahead-day {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--accent2); margin-bottom: 8px; }}
  .ahead-ev {{ font-size: 13px; color: #bcc3d6; line-height: 1.65; }}

  .chart-wrap {{ background: var(--surface); padding: 28px 28px 22px; }}
  .chart-hdr {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }}
  .chart-lbl {{ font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.14em; color: var(--muted); text-transform: uppercase; }}
  canvas {{ display: block; width: 100% !important; }}

  .footer {{ border-top: 1px solid var(--border); padding: 26px 64px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }}
  .footer-txt {{ font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--muted); letter-spacing: 0.04em; }}

  @media(max-width:780px){{
    .masthead,.container,.footer{{padding-left:20px;padding-right:20px;}}
    .idx-grid,.two-col,.crypto-grid,.ahead-grid{{grid-template-columns:1fr;}}
    .masthead-row {{ align-items: flex-start; flex-direction: column; gap: 16px; }}
  }}
</style>
</head>
<body>

<div class="top-nav-wrapper">
  <div class="masthead">
    <div class="masthead-row">
      <div>
        <div class="kicker">Weekly Market Summary · U.S. Equities &amp; Digital Assets</div>
        <div class="week-title">{week_start_str} – <span>{today_str}</span>, {year_str}</div>
      </div>
      <div class="masthead-meta">
        <div class="badge {badge_color}">{market_tone}</div>
        <div class="pub-date">Published {full_date} · Post Market Close</div>
      </div>
    </div>
  </div>
  {ticker_html}
</div>

<div class="container">
  <div class="section">
    <div class="sec-label">Section 01</div>
    <div class="sec-title">Major U.S. Indices</div>
    <div class="idx-grid">
      <div class="idx-card {sp_card_class}">
        <div class="idx-name">S&amp;P 500</div>
        <div class="idx-close">{sp['end_price']:,.2f}</div>
        <div class="idx-wtd {'pos' if sp_pct >= 0 else 'neg'}">{"▲" if sp_pct >= 0 else "▼"} {"+" if sp_pct >= 0 else ""}{sp_pct}% WTD</div>
        <div class="idx-note">Reflects broad market performance across the 500 largest U.S. publicly traded companies.</div>
      </div>
      <div class="idx-card {nd_card_class}">
        <div class="idx-name">Nasdaq Composite</div>
        <div class="idx-close">{nd['end_price']:,.2f}</div>
        <div class="idx-wtd {'pos' if nd['pct_change'] >= 0 else 'neg'}">{"▲" if nd['pct_change'] >= 0 else "▼"} {"+" if nd['pct_change'] >= 0 else ""}{nd['pct_change']}% WTD</div>
        <div class="idx-note">Tech-heavy index heavily influenced by mega-cap growth and semiconductor equities.</div>
      </div>
      <div class="idx-card {dj_card_class}">
        <div class="idx-name">Dow Jones Industrial Avg.</div>
        <div class="idx-close">{dj['end_price']:,.2f}</div>
        <div class="idx-wtd {'pos' if dj['pct_change'] >= 0 else 'neg'}">{"▲" if dj['pct_change'] >= 0 else "▼"} {"+" if dj['abs_change'] >= 0 else ""}{int(dj['abs_change'])} pts WTD</div>
        <div class="idx-note">Price-weighted index representing 30 prominent blue-chip U.S. corporations.</div>
      </div>
    </div>
    <ul class="blist">
      <li><strong>Market Tone:</strong> U.S. equities finished the week {"higher" if sp_pct >= 0 else "lower"}, with the S&P 500 recording a {"+" if sp_pct >= 0 else ""}{sp_pct}% move.</li>
      <li><strong>Volatility Profile:</strong> The VIX closed the week at {vix_close:,.2f}. Levels below 20 generally indicate a calmer equity environment, while prints above 20 signal elevated hedging activity.</li>
    </ul>
  </div>

  <div class="section">
    <div class="sec-label">Section 02</div>
    <div class="sec-title">Sector Performance</div>
    <div class="two-col" style="margin-bottom:26px;">
      <div>
        <div class="col-lbl lead">▲ Top Performing Sectors</div>
        <div class="tag-row">{top_tags}</div>
        <ul class="blist">
          <li>Capital rotated strongly into <strong>{top_sectors[0][0]}</strong>, making it the top performing segment of the S&P 500 this week.</li>
          <li>{top_sectors[1][0]} also exhibited strong relative momentum, capturing positive institutional inflows.</li>
        </ul>
      </div>
      <div>
        <div class="col-lbl lag">▼ Lagging Sectors</div>
        <div class="tag-row">{bot_tags}</div>
        <ul class="blist">
          <li><strong>{bottom_sectors[0][0]}</strong> lagged the broader market, absorbing the heaviest selling pressure over the 5-day period.</li>
          <li>{bottom_sectors[1][0]} also faced structural headwinds, underperforming relative to the core index benchmarks.</li>
        </ul>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="sec-label">Section 03</div>
    <div class="sec-title">Key Macro &amp; Rates Data</div>
    <div class="data-row">
      <div class="dcell">
        <div class="dc-lbl">10-Yr Treasury Yield</div>
        <div class="dc-val {'hot' if tnx['pct_change'] >= 0 else 'cool'}">{tnx['end_price']:,.2f}%</div>
        <div class="dc-note">Yield {"rose" if tnx['pct_change'] >= 0 else "fell"} WTD, acting as a primary driver for broader equity valuations and sector rotation.</div>
      </div>
      <div class="dcell">
        <div class="dc-lbl">U.S. Dollar Index (DXY)</div>
        <div class="dc-val {'hot' if dxy['pct_change'] >= 0 else 'cool'}">{dxy['end_price']:,.2f}</div>
        <div class="dc-note">The Dollar {"strengthened" if dxy['pct_change'] >= 0 else "weakened"} by {abs(dxy['pct_change'])}% over the 5-day period, impacting multinational revenue expectations.</div>
      </div>
      <div class="dcell">
        <div class="dc-lbl">13-Week T-Bill Yield</div>
        <div class="dc-val">{irx['end_price']:,.2f}%</div>
        <div class="dc-note">Tracks closely with the Federal Funds Rate. Yield moved by {abs(irx['pct_change'])}% this week.</div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="sec-label">Section 04</div>
    <div class="sec-title">Mega-Cap Tech &amp; Key Movers</div>
    <div style="margin-bottom:20px;">{mega_cap_html}</div>
  </div>

  <div class="section">
    <div class="sec-label">Section 05</div>
    <div class="sec-title">Cryptocurrency Market Recap</div>
    <div class="crypto-grid">
      <div class="cc">
        <div class="cc-name">Bitcoin (BTC)</div>
        <div class="cc-price">${btc['end_price']:,.0f}</div>
        <div class="cc-chg {'pos' if btc['pct_change'] >= 0 else 'neg'}">{"▲" if btc['pct_change'] >= 0 else "▼"} {abs(btc['pct_change'])}% WTD</div>
      </div>
      <div class="cc">
        <div class="cc-name">Ethereum (ETH)</div>
        <div class="cc-price">${eth['end_price']:,.0f}</div>
        <div class="cc-chg {'pos' if eth['pct_change'] >= 0 else 'neg'}">{"▲" if eth['pct_change'] >= 0 else "▼"} {abs(eth['pct_change'])}% WTD</div>
      </div>
      <div class="cc">
        <div class="cc-name">Solana (SOL)</div>
        <div class="cc-price">${sol['end_price']:,.2f}</div>
        <div class="cc-chg {'pos' if sol['pct_change'] >= 0 else 'neg'}">{"▲" if sol['pct_change'] >= 0 else "▼"} {abs(sol['pct_change'])}% WTD</div>
      </div>
      <div class="cc">
        <div class="cc-name">XRP</div>
        <div class="cc-price">${xrp['end_price']:,.4f}</div>
        <div class="cc-chg {'pos' if xrp['pct_change'] >= 0 else 'neg'}">{"▲" if xrp['pct_change'] >= 0 else "▼"} {abs(xrp['pct_change'])}% WTD</div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="sec-label">Section 06</div>
    <div class="sec-title">Global Market Context</div>
    <table class="gtable" style="margin-bottom:26px;">
      <thead><tr><th>Index / Asset</th><th>WTD Performance</th><th>Status</th></tr></thead>
      <tbody>
        <tr>
          <td>Nikkei 225 (Japan)</td>
          <td class="{'pos' if n225['pct_change'] >= 0 else 'neg'}">{"+" if n225['pct_change'] >= 0 else ""}{n225['pct_change']}%</td>
          <td>Japanese equities tracked broader global momentum flows this week.</td>
        </tr>
        <tr>
          <td>Euro Stoxx 50 (EU)</td>
          <td class="{'pos' if stoxx['pct_change'] >= 0 else 'neg'}">{"+" if stoxx['pct_change'] >= 0 else ""}{stoxx['pct_change']}%</td>
          <td>European blue-chip stocks digested the latest economic policy signaling.</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="section">
    <div class="sec-label">Section 07</div>
    <div class="sec-title">Investor Takeaway</div>
    <div class="takeaway">{takeaway_text}</div>
  </div>

  <div class="section">
    <div class="sec-label">Section 08</div>
    <div class="sec-title">Looking Ahead to Next Week</div>
    <div class="ahead-grid" style="margin-bottom:24px;">
      <div class="ahead-cell">
        <div class="ahead-day">Macro &amp; Economic Data</div>
        <div class="ahead-ev">{lookahead['macro']}</div>
      </div>
      <div class="ahead-cell">
        <div class="ahead-day">Federal Reserve Policy</div>
        <div class="ahead-ev">{lookahead['fed_policy']}</div>
      </div>
      <div class="ahead-cell">
        <div class="ahead-day">Earnings &amp; Catalysts</div>
        <div class="ahead-ev">{lookahead['earnings_and_catalysts']}</div>
      </div>
      <div class="ahead-cell">
        <div class="ahead-day">Key Risk Factors</div>
        <div class="ahead-ev">{lookahead['risk_factors']}</div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="sec-label">Section 09</div>
    <div class="sec-title">S&amp;P 500 — Daily Close ({week_start_str}–{today_str}, {year_str})</div>
    <div class="chart-wrap">
      <div class="chart-hdr">
        <div class="chart-lbl">S&amp;P 500 (SPX) · Actual Daily Closing Prices</div>
        <div class="chart-lbl">Live Data Generated via Python Automation</div>
      </div>
      <canvas id="spxChart" height="200"></canvas>
    </div>
  </div>
</div>

<div class="footer">
  <div class="footer-txt">Automated Market Summary · Post Market Close Edition</div>
  <div class="footer-txt">Live Data Sourced via YFinance API · {full_date}</div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
const labels = {json.dumps(sp_dates)};
const prices = {json.dumps(sp_data)};
const ctx = document.getElementById('spxChart').getContext('2d');
const minPrice = Math.min(...prices);
const maxPrice = Math.max(...prices);
const yPadding = (maxPrice - minPrice) * 0.15 || maxPrice * 0.01;
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: labels,
    datasets: [{{
      label: 'S&P 500 Close',
      data: prices,
      borderColor: '#e8c84a',
      backgroundColor: (ctx) => {{
        const c = ctx.chart.ctx, a = ctx.chart.chartArea;
        if (!a) return 'transparent';
        const g = c.createLinearGradient(0, a.top, 0, a.bottom);
        g.addColorStop(0, 'rgba(232,200,74,0.16)');
        g.addColorStop(1, 'rgba(232,200,74,0.01)');
        return g;
      }},
      fill: true, tension: 0.35,
      pointBackgroundColor: (ctx) => {{
        const v = ctx.parsed?.y;
        if (!v) return '#e8c84a';
        return v === Math.min(...prices) ? '#f05b5b' : v === Math.max(...prices) ? '#3dd68c' : '#e8c84a';
      }},
      pointBorderColor: '#09090f', pointBorderWidth: 2,
      pointRadius: 6, pointHoverRadius: 8, borderWidth: 2.5
    }}]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#181b26', borderColor: '#2a2e42', borderWidth: 1,
        titleColor: '#8b94b2', bodyColor: '#e8c84a',
        titleFont: {{ family: 'IBM Plex Mono', size: 10 }},
        bodyFont: {{ family: 'IBM Plex Mono', size: 13 }},
        callbacks: {{
          label: (c) => ` ${{c.parsed.y.toLocaleString('en-US',{{minimumFractionDigits:2,maximumFractionDigits:2}})}}`,
          afterLabel: (c) => {{
            const chg = ((c.parsed.y - prices[0]) / prices[0] * 100).toFixed(2);
            return ` WTD: ${{chg > 0 ? '+' : ''}}${{chg}}%`;
          }}
        }}
      }}
    }},
    scales: {{
      x: {{
        grid: {{ color: 'rgba(255,255,255,0.035)', drawBorder: false }},
        ticks: {{ color: '#5c6480', font: {{ family: 'IBM Plex Mono', size: 10 }} }},
        border: {{ display: false }}
      }},
      y: {{
        position: 'right',
        min: Math.floor(minPrice - yPadding),
        max: Math.ceil(maxPrice + yPadding),
        grid: {{ color: 'rgba(255,255,255,0.045)', drawBorder: false }},
        ticks: {{
          color: '#5c6480', font: {{ family: 'IBM Plex Mono', size: 10 }},
          callback: v => v.toLocaleString()
        }},
        border: {{ display: false }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"✓ Successfully generated index.html for {full_date}")


if __name__ == "__main__":
    generate_html()
