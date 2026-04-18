import yfinance as yf
import datetime
import json
import os
import urllib.request

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL   = "claude-3-5-sonnet-20241022"

SANITY_BOUNDS = {
    "GC=F":      (1000, 8000),
    "CL=F":      (20,   200),
    "BTC-USD":   (1000, 500000),
    "ETH-USD":   (50,   50000),
    "SOL-USD":   (1,    10000),
    "XRP-USD":   (0.01, 100),
    "^GSPC":     (1000, 20000),
    "^IXIC":     (1000, 50000),
    "^DJI":      (5000, 200000),
    "^RUT":      (500,  10000),
    "^VIX":      (5,    150),
    "^TNX":      (0.1,  20),
    "^IRX":      (0.0,  20),
    "DX-Y.NYB":  (50,   200),
    "^N225":     (10000, 60000),
    "^STOXX50E": (2000,  7000),
    "^FTSE":     (4000,  15000),
    "^HSI":      (10000, 50000),
}

FALLBACKS = {
    "GC=F": "GLD",
    "CL=F": "USO",
}

# ─────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────
def is_sane(ticker_symbol, value):
    if ticker_symbol not in SANITY_BOUNDS:
        return True
    lo, hi = SANITY_BOUNDS[ticker_symbol]
    return lo <= value <= hi

def fetch_weekly_data(ticker_symbol):
    tickers_to_try = [ticker_symbol]
    if ticker_symbol in FALLBACKS:
        tickers_to_try.append(FALLBACKS[ticker_symbol])
    for tk in tickers_to_try:
        try:
            ticker = yf.Ticker(tk)
            hist   = ticker.history(period="10d")
            if len(hist) < 2:
                continue
            if len(hist) > 5:
                prev_close = hist['Close'].iloc[-6]
            else:
                prev_close = hist['Close'].iloc[0]
            chart_hist = hist.iloc[-5:]
            dates      = [d.strftime('%a %m/%d') for d in chart_hist.index]
            closes     = [round(float(v), 2) for v in chart_hist['Close'].tolist()]
            highs      = [round(float(v), 2) for v in chart_hist['High'].tolist()]
            lows       = [round(float(v), 2) for v in chart_hist['Low'].tolist()]
            end_price  = closes[-1]
            if not is_sane(tk, end_price):
                print(f"  Sanity check FAILED for {tk}: end_price={end_price} — trying fallback")
                continue
            pct_change = ((end_price - prev_close) / prev_close) * 100 if prev_close != 0 else 0.0
            abs_change = end_price - prev_close
            week_high  = max(highs) if highs else end_price
            week_low   = min(lows) if lows else end_price
            return {
                "dates": dates, "closes": closes, "end_price": end_price,
                "pct_change": round(pct_change, 2), "abs_change": round(abs_change, 2),
                "prev_close": round(prev_close, 2),
                "week_high": week_high, "week_low": week_low,
                "ticker_used": tk, "error": None,
            }
        except Exception as e:
            print(f"  Exception fetching {tk}: {e}")
            continue
    print(f"  All fetch attempts failed for {ticker_symbol}. Using zeroed data.")
    return {"dates": [], "closes": [], "end_price": 0.0, "pct_change": 0.0,
            "abs_change": 0.0, "prev_close": 0.0, "week_high": 0.0, "week_low": 0.0,
            "ticker_used": ticker_symbol, "error": f"Data unavailable for {ticker_symbol}"}

# ─────────────────────────────────────────────
# CLAUDE API HELPERS
# ─────────────────────────────────────────────
def claude(prompt, max_tokens=400, fallback=""):
    if not ANTHROPIC_API_KEY:
        print("  ANTHROPIC_API_KEY not set — using fallback.")
        return fallback
    try:
        payload = json.dumps({
            "model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            ANTHROPIC_API_URL, data=payload,
            headers={"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            text = body["content"][0]["text"].strip()
            print(f"  Claude OK ({len(text)} chars)")
            return text
    except Exception as e:
        print(f"  Claude API error: {e} — using fallback.")
        return fallback

def claude_json(prompt, required_keys, max_tokens=600, fallback=None):
    raw = claude(prompt, max_tokens=max_tokens, fallback="")
    if not raw:
        return fallback or {}
    try:
        start_idx = raw.find('{')
        end_idx   = raw.rfind('}')
        if start_idx == -1 or end_idx == -1:
            raise ValueError("No JSON object found in response")
        result = json.loads(raw[start_idx:end_idx + 1])
        if not required_keys.issubset(result.keys()):
            raise ValueError(f"Missing keys: {required_keys - result.keys()}")
        return result
    except Exception as e:
        print(f"  Claude JSON parse error: {e} — using fallback.")
        return fallback or {}

# ─────────────────────────────────────────────
# CLAUDE-POWERED SECTION GENERATORS
# ─────────────────────────────────────────────
def generate_lookahead_claude(market_context):
    sp_pct   = market_context["sp_pct"]
    vix      = market_context["vix_close"]
    tnx      = market_context["tnx_close"]
    tnx_pct  = market_context["tnx_pct"]
    dxy      = market_context["dxy_close"]
    dxy_pct  = market_context["dxy_pct"]
    top1     = market_context["top_sectors"].split(", ")[0]
    bot1     = market_context["bottom_sectors"].split(", ")[0]
    btc_pct  = market_context["btc_pct"]
    oil_pct  = market_context["oil_pct"]
    gold_pct = market_context["gold_pct"]

    prompt = (
        "You are a senior equity strategist writing the Looking Ahead section of a weekly market summary. "
        "Write four short paragraphs (2-3 sentences each) for next week. Be specific, analytical, and "
        "grounded in the data below — do not be generic. Reference actual numbers where relevant.\n\n"
        f"This week: S&P 500 {'+' if sp_pct >= 0 else ''}{sp_pct}% WTD, "
        f"VIX {vix:.2f}, 10-yr yield {tnx:.2f}% ({'+' if tnx_pct >= 0 else ''}{tnx_pct}% WTD), "
        f"DXY {dxy:.2f} ({'+' if dxy_pct >= 0 else ''}{dxy_pct}% WTD), "
        f"Gold {'+' if gold_pct >= 0 else ''}{gold_pct}% WTD, "
        f"Crude {'+' if oil_pct >= 0 else ''}{oil_pct}% WTD, "
        f"BTC {'+' if btc_pct >= 0 else ''}{btc_pct}% WTD. "
        f"Top sectors: {market_context['top_sectors']}. "
        f"Bottom sectors: {market_context['bottom_sectors']}.\n\n"
        "Respond ONLY with a JSON object with these exact keys: macro, fed_policy, earnings_and_catalysts, risk_factors. "
        "No markdown, no preamble."
    )
    fallback = {
        "macro": (
            f"Investors will monitor upcoming inflation and labour market prints for direction on the "
            f"consumer backdrop. Given the 10-year at {tnx:.2f}%, any upside surprise in price data "
            f"could reignite rate pressure on rate-sensitive sectors like {bot1}."
        ),
        "fed_policy": (
            f"The Fed remains data-dependent with yields at {tnx:.2f}%. Scheduled FOMC member speeches "
            f"will be parsed for consensus on the rate path — any hawkish lean could trigger another "
            f"leg of pressure on growth equities."
        ),
        "earnings_and_catalysts": (
            f"Earnings season continues with sector rotation firmly in focus. Reports from {top1} "
            f"constituents will be watched for guidance confirmation, while results from lagging "
            f"sectors will be scrutinised for signs of stabilisation."
        ),
        "risk_factors": (
            ("The VIX at " + f"{vix:.2f}" + " signals elevated tail risk heading into next week."
             if vix >= 20 else "The VIX at " + f"{vix:.2f}" + " reflects relative market complacency.")
            + f" Geopolitical developments, surprise macro data, and Fed communication shifts "
              "remain the primary exogenous risk factors."
        ),
    }
    result = claude_json(
        prompt,
        required_keys={"macro", "fed_policy", "earnings_and_catalysts", "risk_factors"},
        max_tokens=600, fallback=fallback,
    )
    print("  Section 08 generated via Claude.")
    return result

# ─────────────────────────────────────────────
# FORMATTING HELPERS
# ─────────────────────────────────────────────
def fmt_date(dt, include_day=True):
    if include_day:
        return f"{dt.strftime('%b')} {dt.day}"
    return f"{dt.strftime('%B')} {dt.day}, {dt.strftime('%Y')}"

def fmt_chg(pct, abs_val=None, is_yield=False, is_points=False):
    sign  = "+" if pct >= 0 else ""
    color = "pos" if pct >= 0 else "neg"
    arrow = "\u25b2" if pct >= 0 else "\u25bc"
    if is_yield and abs_val is not None:
        bps = round(abs(abs_val) * 100)
        return f'<div class="t-chg {color}">{arrow} {bps} bps WTD</div>'
    elif is_points and abs_val is not None:
        return f'<div class="t-chg {color}">{arrow} {sign}{int(abs(abs_val)):,} pts WTD</div>'
    else:
        return f'<div class="t-chg {color}">{arrow} {sign}{pct}% WTD</div>'

def get_t_item(name, val, pct, is_yield=False, abs_val=None, is_points=False):
    return (
        f'<div class="t-item">'
        f'<div class="t-name">{name}</div>'
        f'<div class="t-val">{val}</div>'
        f'{fmt_chg(pct, abs_val=abs_val, is_yield=is_yield, is_points=is_points)}'
        f'</div>'
    )

# ─────────────────────────────────────────────
# MAIN HTML GENERATOR
# ─────────────────────────────────────────────
def generate_html():
    print("Fetching market data...")
    sp   = fetch_weekly_data("^GSPC")
    nd   = fetch_weekly_data("^IXIC")
    dj   = fetch_weekly_data("^DJI")
    rut  = fetch_weekly_data("^RUT")
    vix  = fetch_weekly_data("^VIX")
    tnx  = fetch_weekly_data("^TNX")
    irx  = fetch_weekly_data("^IRX")
    dxy  = fetch_weekly_data("DX-Y.NYB")
    gold = fetch_weekly_data("GC=F")
    oil  = fetch_weekly_data("CL=F")
    btc  = fetch_weekly_data("BTC-USD")
    eth  = fetch_weekly_data("ETH-USD")
    sol  = fetch_weekly_data("SOL-USD")
    xrp  = fetch_weekly_data("XRP-USD")
    n225 = fetch_weekly_data("^N225")
    stoxx= fetch_weekly_data("^STOXX50E")
    ftse = fetch_weekly_data("^FTSE")
    hsi  = fetch_weekly_data("^HSI")

    if sp["dates"]:
        sp_ticker   = yf.Ticker("^GSPC")
        sp_hist     = sp_ticker.history(period="10d")
        trading_days= sp_hist.iloc[-5:] if len(sp_hist) >= 5 else sp_hist
        start_dt    = trading_days.index[0].to_pydatetime()
        end_dt      = trading_days.index[-1].to_pydatetime()
        week_start_str = fmt_date(start_dt)
        today_str      = fmt_date(end_dt)
        year_str       = end_dt.strftime('%Y')
        full_date      = fmt_date(end_dt, include_day=False)
        week_end_date  = full_date
    else:
        now            = datetime.datetime.now()
        week_start_str = fmt_date(now - datetime.timedelta(days=4))
        today_str      = fmt_date(now)
        year_str       = now.strftime('%Y')
        full_date      = fmt_date(now, include_day=False)
        week_end_date  = full_date

    sectors = {
        "Technology (XLK)": "XLK", "Financials (XLF)": "XLF",
        "Energy (XLE)": "XLE", "Healthcare (XLV)": "XLV",
        "Industrials (XLI)": "XLI", "Cons. Discretionary (XLY)": "XLY",
        "Cons. Staples (XLP)": "XLP", "Real Estate (XLRE)": "XLRE",
        "Utilities (XLU)": "XLU", "Materials (XLB)": "XLB",
        "Comm. Services (XLC)": "XLC",
    }
    sector_perf   = {name: fetch_weekly_data(ticker)["pct_change"] for name, ticker in sectors.items()}
    sorted_sectors= sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)
    top_sectors   = sorted_sectors[:4]
    bottom_sectors= sorted_sectors[-4:]

    sp_pct    = sp["pct_change"]
    vix_close = vix["end_price"]
    tnx_pct   = tnx["pct_change"]

    # Claude: sector bullets
    print("Generating sector analysis via Claude...")
    all_sectors_str = ", ".join(f"{s[0]} {'+' if s[1] >= 0 else ''}{s[1]}%" for s in sorted_sectors)
    sector_prompt = (
        "You are writing bullet point copy for a weekly institutional equity market summary. "
        "Write exactly two sentences for the top performing sectors and two for the bottom sectors. "
        "Each sentence must be distinct and specific to the actual sector named — do not use generic phrasing. "
        "Reference the actual performance percentages. "
        "Respond ONLY with JSON with keys top_bullet1, top_bullet2, bot_bullet1, bot_bullet2. No markdown.\n"
        f"All sectors this week: {all_sectors_str}\n"
        f"Top 4: {', '.join(f'{s[0]} {chr(43) if s[1] >= 0 else str(s[1])}%' for s in top_sectors)}\n"
        f"Bottom 4: {', '.join(f'{s[0]} {chr(43) if s[1] >= 0 else str(s[1])}%' for s in bottom_sectors)}\n"
        f"S&P 500 WTD: {sp_pct}%, VIX: {vix_close:.2f}, 10-yr yield: {tnx['end_price']:.2f}%"
    )
    sector_fallback = {
        "top_bullet1": f"Capital rotated strongly into <strong>{top_sectors[0][0]}</strong>, making it the top performing segment of the S&amp;P 500 this week.",
        "top_bullet2": f"{top_sectors[1][0]} also exhibited strong relative momentum, capturing positive institutional inflows.",
        "bot_bullet1": f"<strong>{bottom_sectors[0][0]}</strong> lagged the broader market, absorbing the heaviest selling pressure over the 5-day period.",
        "bot_bullet2": f"{bottom_sectors[1][0]} also faced structural headwinds, underperforming relative to the core index benchmarks.",
    }
    sector_bullets = claude_json(sector_prompt, required_keys={"top_bullet1","top_bullet2","bot_bullet1","bot_bullet2"}, max_tokens=300, fallback=sector_fallback)

    # Claude: mega-cap descriptions
    print("Generating mega-cap descriptions via Claude...")
    megacaps = {"AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon", "META": "Meta Platforms"}
    megacap_data = {tk: {"name": name, "result": fetch_weekly_data(tk)} for tk, name in megacaps.items()}
    mc_lines = "\n".join(
        f"- {tk} ({v['name']}) closed at ${v['result']['end_price']:,.2f}, "
        f"{'+' if v['result']['pct_change'] >= 0 else ''}{v['result']['pct_change']}% WTD"
        for tk, v in megacap_data.items()
    )
    mc_prompt = (
        "You are writing copy for a weekly institutional equity market summary. "
        "Write one sentence per ticker describing its weekly performance and what it signals for the broader market or its sector. "
        "Each sentence must be distinct — do not reuse phrasing. "
        "IMPORTANT: Do NOT start the sentence with the company name or ticker — the name is already displayed separately. "
        "Start with the action or insight directly. Be specific and analytical. Reference the actual closing price and move. "
        "Respond ONLY with a JSON object mapping ticker symbol to sentence string. No markdown.\n"
        f"Market context: S&P 500 {'+' if sp_pct >= 0 else ''}{sp_pct}% WTD, VIX at {vix_close:.2f}, 10-yr yield {tnx['end_price']:.2f}%.\n"
        f"Tickers:\n{mc_lines}"
    )
    mc_fallback = {
        tk: f"Closed the week at ${v['result']['end_price']:,.2f}, posting a {'+' if v['result']['pct_change'] >= 0 else ''}{v['result']['pct_change']}% move."
        for tk, v in megacap_data.items()
    }
    mc_descriptions = claude_json(mc_prompt, required_keys=set(megacap_data.keys()), max_tokens=500, fallback=mc_fallback)

    # TradingView stock logos
    # Pattern: https://s3-symbol-logo.tradingview.com/{slug}.svg
    logo_slugs = {
        "AAPL": "apple",
        "MSFT": "microsoft",
        "NVDA": "nvidia",
        "AMZN": "amazon",
        "META": "meta-platforms",
    }
    megacap_html = ""
    for tk, v in megacap_data.items():
        r       = v["result"]
        c_pct   = r["pct_change"]
        c_abs   = r["abs_change"]
        c_color = "pos" if c_pct >= 0 else "neg"
        c_arrow = "\u25b2" if c_pct >= 0 else "\u25bc"
        c_sign  = "+" if c_pct >= 0 else ""
        err_note= f' <span style="color:var(--red);font-size:10px;">data error</span>' if r["error"] else ""
        desc    = mc_descriptions.get(tk, mc_fallback.get(tk, ""))
        slug    = logo_slugs.get(tk, "")
        logo_html = f'<img src="https://s3-symbol-logo.tradingview.com/{slug}.svg" class="tkr-logo" alt="{tk} logo" onerror="this.style.display=\'none\'">' if slug else ""
        megacap_html += (
            f'<div class="co-row">'
            f'<div class="tkr-wrap">{logo_html}<span class="tkr">{tk}</span></div>'
            f'<div class="co-body">'
            f'<div class="co-desc"><strong>{v["name"]}</strong>{err_note} {desc}</div>'
            f'<div class="co-stats">'
            f'<span class="co-stat"><span class="co-stat-lbl">Close</span> <span class="co-stat-val">${r["end_price"]:,.2f}</span></span>'
            f'<span class="co-stat"><span class="co-stat-lbl">$ Chg</span> <span class="co-stat-val {c_color}">{c_sign}${abs(c_abs):,.2f}</span></span>'
            f'<span class="co-stat"><span class="co-stat-lbl">5D High</span> <span class="co-stat-val">${r["week_high"]:,.2f}</span></span>'
            f'<span class="co-stat"><span class="co-stat-lbl">5D Low</span> <span class="co-stat-val">${r["week_low"]:,.2f}</span></span>'
            f'</div>'
            f'</div>'
            f'<span class="co-mv {c_color}">{c_arrow} {c_sign}{c_pct}%</span>'
            f'</div>'
        )

    # Claude: section 08 lookahead
    print("Generating Section 08 via Claude...")
    lookahead = generate_lookahead_claude({
        "sp_pct": sp_pct, "nd_pct": nd["pct_change"],
        "vix_close": vix_close, "tnx_close": tnx["end_price"], "tnx_pct": tnx_pct,
        "dxy_close": dxy["end_price"], "dxy_pct": dxy["pct_change"],
        "top_sectors": ", ".join(s[0] for s in top_sectors[:2]),
        "bottom_sectors": ", ".join(s[0] for s in bottom_sectors[:2]),
        "btc_pct": btc["pct_change"], "oil_pct": oil["pct_change"], "gold_pct": gold["pct_change"],
        "week_end_date": week_end_date,
    })

    # Claude: global market status
    print("Generating global market context via Claude...")
    global_prompt = (
        "You are writing one-sentence status descriptions for a weekly global equity market summary. "
        "Each sentence must be specific to the index named and its actual performance — do not be generic. "
        "Do NOT start with the index name. Start with the insight or dynamic directly. "
        "Respond ONLY with JSON with keys nikkei, stoxx, ftse, hsi. No markdown.\n"
        f"Nikkei 225 (Japan): {'+' if n225['pct_change'] >= 0 else ''}{n225['pct_change']}% WTD, close {n225['end_price']:,.2f}\n"
        f"Euro Stoxx 50 (EU): {'+' if stoxx['pct_change'] >= 0 else ''}{stoxx['pct_change']}% WTD, close {stoxx['end_price']:,.2f}\n"
        f"FTSE 100 (UK): {'+' if ftse['pct_change'] >= 0 else ''}{ftse['pct_change']}% WTD, close {ftse['end_price']:,.2f}\n"
        f"Hang Seng (HK): {'+' if hsi['pct_change'] >= 0 else ''}{hsi['pct_change']}% WTD, close {hsi['end_price']:,.2f}\n"
        f"S&P 500 context: {'+' if sp_pct >= 0 else ''}{sp_pct}% WTD, VIX {vix_close:.2f}, 10-yr yield {tnx['end_price']:.2f}%"
    )
    global_fallback = {
        "nikkei": "Japanese equities tracked broader global momentum flows this week.",
        "stoxx":  "European blue-chip stocks digested the latest economic policy signaling.",
        "ftse":   "UK large-caps reflected commodity sensitivity and sterling moves against the dollar.",
        "hsi":    "Hong Kong shares traded on China policy cues and tech sector sentiment.",
    }
    global_status = claude_json(global_prompt, required_keys={"nikkei","stoxx","ftse","hsi"}, max_tokens=300, fallback=global_fallback)

    # Claude: crypto descriptions
    print("Generating crypto descriptions via Claude...")
    crypto_prompt = (
        "You are writing one-sentence analytical notes for a weekly cryptocurrency market summary. "
        "Each sentence must be specific to the asset and its actual performance this week — no generic phrasing. "
        "Do NOT start the sentence with the asset name. Start with the action, dynamic, or insight directly. "
        "Respond ONLY with JSON with keys btc, eth, sol, xrp. No markdown.\n"
        f"Bitcoin (BTC): {'+' if btc['pct_change'] >= 0 else ''}{btc['pct_change']}% WTD, close ${btc['end_price']:,.0f}, 5D high ${btc['week_high']:,.0f}, 5D low ${btc['week_low']:,.0f}\n"
        f"Ethereum (ETH): {'+' if eth['pct_change'] >= 0 else ''}{eth['pct_change']}% WTD, close ${eth['end_price']:,.0f}, 5D high ${eth['week_high']:,.0f}, 5D low ${eth['week_low']:,.0f}\n"
        f"Solana (SOL): {'+' if sol['pct_change'] >= 0 else ''}{sol['pct_change']}% WTD, close ${sol['end_price']:.2f}\n"
        f"XRP: {'+' if xrp['pct_change'] >= 0 else ''}{xrp['pct_change']}% WTD, close ${xrp['end_price']:.4f}\n"
        f"Equity context: S&P 500 {'+' if sp_pct >= 0 else ''}{sp_pct}% WTD, VIX {vix_close:.2f}"
    )
    crypto_fallback = {
        "btc": f"Closed at ${btc['end_price']:,.0f} with a 5-day range of ${btc['week_low']:,.0f}–${btc['week_high']:,.0f}, tracking broad risk sentiment.",
        "eth": f"Settled at ${eth['end_price']:,.0f}, with relative performance to BTC reflecting shifts in layer-1 narrative flow.",
        "sol": f"Finished at ${sol['end_price']:.2f}, moving in line with broader high-beta crypto exposure.",
        "xrp": f"Printed at ${xrp['end_price']:.4f}, with regulatory and payments-sector headlines driving the tape.",
    }
    crypto_descriptions = claude_json(crypto_prompt, required_keys={"btc","eth","sol","xrp"}, max_tokens=400, fallback=crypto_fallback)

    # TradingView crypto logos (with fallback hiding on error)
    # Pattern: s3-symbol-logo.tradingview.com/crypto/XTVC{SYMBOL}.svg
    def crypto_card(name, symbol, tv_symbol, price_str, data, desc):
        c_pct   = data["pct_change"]
        c_color = "pos" if c_pct >= 0 else "neg"
        c_arrow = "\u25b2" if c_pct >= 0 else "\u25bc"
        c_sign  = "+" if c_pct >= 0 else ""
        logo    = f'https://s3-symbol-logo.tradingview.com/crypto/XTVC{tv_symbol}.svg'
        return (
            f'<div class="cc">'
            f'<div class="cc-head">'
            f'<img src="{logo}" class="cc-logo" alt="{symbol} logo" onerror="this.style.display=\'none\'">'
            f'<div class="cc-name">{name} ({symbol})</div>'
            f'</div>'
            f'<div class="cc-price">{price_str}</div>'
            f'<div class="cc-chg {c_color}">{c_arrow} {c_sign}{c_pct}% WTD</div>'
            f'<div class="cc-range"><span class="cc-range-lbl">5D Range</span> '
            f'<span class="cc-range-val">${data["week_low"]:,.2f} – ${data["week_high"]:,.2f}</span></div>'
            f'<div class="cc-desc">{desc}</div>'
            f'</div>'
        )

    crypto_html = (
        crypto_card("Bitcoin", "BTC", "BTC", f"${btc['end_price']:,.0f}", btc, crypto_descriptions["btc"])
      + crypto_card("Ethereum", "ETH", "ETH", f"${eth['end_price']:,.0f}", eth, crypto_descriptions["eth"])
      + crypto_card("Solana", "SOL", "SOL", f"${sol['end_price']:.2f}", sol, crypto_descriptions["sol"])
      + crypto_card("XRP", "XRP", "XRP", f"${xrp['end_price']:.4f}", xrp, crypto_descriptions["xrp"])
    )

    # Claude: investor takeaway
    print("Generating investor takeaway via Claude...")
    direction = "higher" if sp_pct >= 0 else "lower"
    vix_note  = "elevated hedging activity" if vix_close >= 20 else "subdued volatility"
    takeaway_prompt = (
        "You are a senior equity strategist writing the Investor Takeaway for a weekly market summary. "
        "Write exactly 3 sentences — sharp, analytical, institutional in tone. No bullet points. No headers. "
        "Synthesize the data below into a coherent narrative about what actually happened this week and what it means. "
        "Do not be generic. Reference specific numbers.\n"
        f"S&P 500: {sp['end_price']:,.2f} ({'+' if sp_pct >= 0 else ''}{sp_pct}% WTD)\n"
        f"Nasdaq: {nd['end_price']:,.2f} ({'+' if nd['pct_change'] >= 0 else ''}{nd['pct_change']}% WTD)\n"
        f"DJIA: {dj['end_price']:,.2f} ({'+' if dj['pct_change'] >= 0 else ''}{dj['pct_change']}% WTD)\n"
        f"VIX: {vix_close:.2f} ({'+' if vix['pct_change'] >= 0 else ''}{vix['pct_change']}% WTD)\n"
        f"10-Yr Yield: {tnx['end_price']:.2f}% ({'+' if tnx_pct >= 0 else ''}{tnx_pct}% WTD)\n"
        f"DXY: {dxy['end_price']:.2f} ({'+' if dxy['pct_change'] >= 0 else ''}{dxy['pct_change']}% WTD)\n"
        f"Gold: {gold['end_price']:,.2f} ({'+' if gold['pct_change'] >= 0 else ''}{gold['pct_change']}% WTD)\n"
        f"Crude Oil: {oil['end_price']:,.2f} ({'+' if oil['pct_change'] >= 0 else ''}{oil['pct_change']}% WTD)\n"
        f"Bitcoin: {btc['end_price']:,.0f} ({'+' if btc['pct_change'] >= 0 else ''}{btc['pct_change']}% WTD)\n"
        f"Top sectors: {', '.join(f'{s[0]} {chr(43) if s[1] >= 0 else str(s[1])}%' for s in top_sectors)}\n"
        f"Bottom sectors: {', '.join(f'{s[0]} {chr(43) if s[1] >= 0 else str(s[1])}%' for s in bottom_sectors)}\n"
        f"Nikkei 225: {'+' if n225['pct_change'] >= 0 else ''}{n225['pct_change']}% WTD\n"
        f"Euro Stoxx 50: {'+' if stoxx['pct_change'] >= 0 else ''}{stoxx['pct_change']}% WTD"
    )
    takeaway_fallback = (
        f"U.S. equities finished the week {direction} with the S&amp;P 500 at {sp['end_price']:,.2f}, "
        f"as {vix_note} characterized the tape. "
        f"Sector rotation favored {top_sectors[0][0]} while {bottom_sectors[0][0]} faced the heaviest selling pressure."
    )
    takeaway_text = claude(takeaway_prompt, max_tokens=400, fallback=takeaway_fallback)

    # Build ticker bar
    t_items = (
        get_t_item("S&P 500",      f"{sp['end_price']:,.2f}",   sp_pct)
      + get_t_item("Nasdaq",       f"{nd['end_price']:,.2f}",   nd["pct_change"])
      + get_t_item("DJIA",         f"{dj['end_price']:,.2f}",   dj["pct_change"], abs_val=dj["abs_change"], is_points=True)
      + get_t_item("Russell 2000", f"{rut['end_price']:,.2f}",  rut["pct_change"])
      + get_t_item("Crude Oil",    f"${oil['end_price']:,.2f}", oil["pct_change"])
      + get_t_item("Gold",         f"${gold['end_price']:,.2f}",gold["pct_change"])
      + get_t_item("VIX",          f"{vix_close:.2f}",          vix["pct_change"])
      + get_t_item("Bitcoin",      f"${btc['end_price']:,.0f}", btc["pct_change"])
      + get_t_item("Ethereum",     f"${eth['end_price']:,.0f}", eth["pct_change"])
      + get_t_item("10-Yr Yield",  f"{tnx['end_price']:.2f}%",  tnx_pct, abs_val=tnx["abs_change"], is_yield=True)
    )
    ticker_html = f'<div class="ticker-wrapper"><div class="ticker-track">{t_items}{t_items}</div></div>'

    market_tone  = "\u25b2 RISK-ON RALLY"   if sp_pct >= 0 else "\u25bc RISK-OFF PULLBACK"
    badge_color  = "badge-green"             if sp_pct >= 0 else "badge-red"
    sp_card_class= "up"                      if sp_pct >= 0 else ""
    nd_card_class= "up"                      if nd["pct_change"] >= 0 else ""
    dj_card_class= "up"                      if dj["pct_change"] >= 0 else ""

    top_tags = "".join(f'<span class="tag g">{s[0]} ({chr(43) if s[1] >= 0 else ""}{s[1]}%)</span>' for s in top_sectors)
    bot_tags = "".join(f'<span class="tag r">{s[0]} ({chr(43) if s[1] >= 0 else ""}{s[1]}%)</span>' for s in bottom_sectors)

    sp_dates = sp["dates"]
    sp_data  = sp["closes"]

    # Global market table rows (Section 06)
    def global_row(name, data, status_text):
        color = "pos" if data["pct_change"] >= 0 else "neg"
        sign  = "+" if data["pct_change"] >= 0 else ""
        return (
            f'<tr>'
            f'<td>{name}</td>'
            f'<td>{data["end_price"]:,.2f}</td>'
            f'<td class="{color}">{sign}{data["pct_change"]}%</td>'
            f'<td>{status_text}</td>'
            f'</tr>'
        )

    global_rows_html = (
        global_row("Nikkei 225 (Japan)", n225, global_status["nikkei"])
      + global_row("Euro Stoxx 50 (EU)", stoxx, global_status["stoxx"])
      + global_row("FTSE 100 (UK)", ftse, global_status["ftse"])
      + global_row("Hang Seng (HK)", hsi, global_status["hsi"])
    )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Weekly Market Summary &ndash; {week_start_str}&ndash;{today_str}, {year_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0a0a0f;
    --surface: #111118;
    --surface2: #1a1a22;
    --surface3: #14141d;
    --border: #22222e;
    --accent: #00f0ff;
    --accent2: #ff00cc;
    --red: #ff3b5c;
    --green: #00ff9d;
    --text: #f0f4ff;
    --muted: #8a8fa8;
    --label: #a0a8c0;
    --nav-bg: rgba(10, 10, 15, 0.92);
    --title-color: #ffffff;
    --shadow-dark: 0 18px 40px -16px rgba(0, 0, 0, 0.45);
    --shadow-glow: 0 18px 38px -16px rgba(0, 240, 255, 0.22);
  }}

  .light {{
    --bg: #f8f9fc;
    --surface: #ffffff;
    --surface2: #f1f3f8;
    --surface3: #eef2f8;
    --border: #e2e6f0;
    --accent: #00aaff;
    --accent2: #ff0088;
    --red: #e63946;
    --green: #00c47d;
    --text: #1a1f2e;
    --muted: #64748b;
    --label: #475569;
    --nav-bg: rgba(248, 249, 252, 0.92);
    --title-color: #1a1f2e;
    --shadow-dark: 0 16px 34px -18px rgba(0, 0, 0, 0.14);
    --shadow-glow: 0 18px 34px -18px rgba(0, 170, 255, 0.16);
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ scroll-behavior: smooth; }}

  body {{
    min-height: 100vh;
    background:
      radial-gradient(circle at top right, rgba(0, 240, 255, 0.08), transparent 28%),
      radial-gradient(circle at bottom left, rgba(255, 0, 204, 0.05), transparent 26%),
      var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, sans-serif;
    font-weight: 400;
    line-height: 1.6;
    transition: background 0.3s ease, color 0.3s ease;
  }}

  .light body {{
    background:
      radial-gradient(circle at top right, rgba(0, 170, 255, 0.06), transparent 28%),
      radial-gradient(circle at bottom left, rgba(255, 0, 136, 0.04), transparent 26%),
      var(--bg);
  }}

  a {{ color: inherit; text-decoration: none; }}

  .header-font {{
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    letter-spacing: -0.02em;
  }}

  ::-webkit-scrollbar {{ width: 9px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{
    background: linear-gradient(180deg, var(--surface2), var(--border));
    border-radius: 999px;
  }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--muted); }}

  .top-nav-wrapper {{
    position: sticky;
    top: 0;
    z-index: 1000;
    background: var(--nav-bg);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    transition: background 0.3s ease, border-color 0.3s ease;
  }}

  .masthead {{
    padding: 28px 60px 20px;
    position: relative;
    overflow: hidden;
  }}

  .masthead::before {{
    content: '';
    position: absolute;
    top: -120px;
    right: -120px;
    width: 600px;
    height: 600px;
    background: radial-gradient(circle, rgba(0,240,255,0.12) 0%, transparent 70%);
    pointer-events: none;
    animation: pulse 15s infinite ease-in-out;
  }}

  .masthead-row {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 20px;
    position: relative;
    z-index: 1;
  }}

  .kicker {{
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 600;
    margin-bottom: 8px;
  }}

  .week-title {{
    font-size: clamp(28px, 4vw, 48px);
    line-height: 1.05;
    color: var(--title-color);
    transition: color 0.3s ease;
  }}

  .week-title span {{ color: var(--accent); }}

  .masthead-meta {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }}

  .badge {{
    font-size: 10px;
    letter-spacing: 0.08em;
    padding: 6px 14px;
    border-radius: 9999px;
    font-weight: 700;
    box-shadow: 0 2px 8px -2px rgba(0, 240, 255, 0.25);
  }}

  .badge-green {{
    background: rgba(0,255,157,0.15);
    color: var(--green);
    border: 1px solid rgba(0,255,157,0.3);
  }}

  .badge-red {{
    background: rgba(255,59,92,0.15);
    color: var(--red);
    border: 1px solid rgba(255,59,92,0.3);
  }}

  .pub-date {{
    font-size: 10.5px;
    color: var(--muted);
    font-weight: 500;
  }}

  .theme-btn {{
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 50%;
    width: 38px;
    height: 38px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    cursor: pointer;
    transition: all 0.25s ease;
    box-shadow: var(--shadow-dark);
  }}

  .theme-btn:hover {{
    transform: scale(1.08);
    background: var(--accent);
    color: #fff;
    border-color: transparent;
  }}

  .ticker-wrapper {{
    border-top: 1px solid var(--border);
    overflow: hidden;
    background: var(--surface);
    box-shadow: 0 4px 20px -8px rgba(0, 240, 255, 0.16);
  }}

  .ticker-track {{
    display: flex;
    width: max-content;
    animation: scrollTicker 60s linear infinite;
    will-change: transform;
  }}

  .ticker-track:hover {{ animation-play-state: paused; }}

  @keyframes scrollTicker {{
    from {{ transform: translateX(0); }}
    to   {{ transform: translateX(-50%); }}
  }}

  @keyframes pulse {{
    0%, 100% {{ opacity: 0.6; }}
    50% {{ opacity: 1; }}
  }}

  .t-item {{
    display: inline-flex;
    flex-direction: column;
    gap: 3px;
    padding: 14px 32px;
    flex-shrink: 0;
    border-right: 1px solid var(--border);
  }}

  .t-name {{
    font-size: 9px;
    letter-spacing: 0.1em;
    color: var(--muted);
    text-transform: uppercase;
    font-weight: 600;
  }}

  .t-val {{
    font-size: 15px;
    font-weight: 700;
  }}

  .t-chg {{
    font-size: 10.5px;
    font-weight: 700;
  }}

  .neg {{ color: var(--red); }}
  .pos {{ color: var(--green); }}

  .container {{
    max-width: 1180px;
    margin: 0 auto;
    padding: 0 60px 80px;
  }}

  .section {{
    margin-top: 68px;
    padding-top: 52px;
    border-top: 1px solid var(--border);
  }}

  .section:first-child {{
    margin-top: 12px;
    padding-top: 32px;
    border-top: none;
  }}

  .sec-label {{
    font-size: 10px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--accent);
    font-weight: 700;
    margin-bottom: 8px;
  }}

  .sec-title {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 26px;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin-bottom: 24px;
  }}

  .sec-intro {{
    font-size: 14px;
    color: var(--label);
    line-height: 1.65;
    margin-bottom: 24px;
    max-width: 820px;
  }}

  .idx-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }}

  .idx-card {{
    position: relative;
    cursor: pointer;
    background: var(--surface);
    padding: 28px;
    border-radius: 16px;
    box-shadow: var(--shadow-dark);
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.3s ease, background 0.3s ease;
    overflow: hidden;
  }}

  .idx-card:hover {{
    transform: translateY(-4px);
    box-shadow: var(--shadow-glow);
  }}

  .idx-card.up::after {{
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 4px;
    background: linear-gradient(90deg, var(--green), #00ff9d);
    border-radius: 0 0 16px 16px;
  }}

  .idx-name {{
    font-size: 10.5px;
    letter-spacing: 0.12em;
    color: var(--muted);
    font-weight: 600;
    margin-bottom: 8px;
    text-transform: uppercase;
  }}

  .idx-close {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 32px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 8px;
  }}

  .idx-wtd {{
    font-size: 13px;
    margin-bottom: 12px;
    font-weight: 600;
  }}

  .idx-note {{
    font-size: 13px;
    color: var(--label);
    line-height: 1.55;
  }}

  .blist {{
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }}

  .blist li {{
    padding-left: 24px;
    position: relative;
    font-size: 14.5px;
    line-height: 1.65;
    color: var(--text);
  }}

  .blist li::before {{
    content: '\u2192';
    position: absolute;
    left: 0;
    top: 0;
    color: var(--accent);
    font-size: 18px;
    line-height: 1.2;
  }}

  .blist li strong {{ font-weight: 700; }}

  .two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 48px;
  }}

  .col-lbl {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.1em;
    margin-bottom: 12px;
  }}

  .col-lbl.lead {{ color: var(--green); }}
  .col-lbl.lag  {{ color: var(--red); }}

  .tag-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 20px;
  }}

  .tag {{
    font-size: 11px;
    padding: 5px 14px;
    border-radius: 9999px;
    font-weight: 600;
    box-shadow: 0 2px 6px -2px rgba(0,0,0,0.15);
  }}

  .tag.g {{
    background: rgba(0,255,157,0.12);
    color: var(--green);
    border: 1px solid rgba(0,255,157,0.16);
  }}

  .tag.r {{
    background: rgba(255,59,92,0.12);
    color: var(--red);
    border: 1px solid rgba(255,59,92,0.16);
  }}

  .data-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
  }}

  .dcell {{
    background: var(--surface);
    padding: 24px;
    border-radius: 16px;
    box-shadow: var(--shadow-dark);
  }}

  .dc-lbl {{
    font-size: 10px;
    letter-spacing: 0.12em;
    color: var(--muted);
    text-transform: uppercase;
    font-weight: 700;
    margin-bottom: 6px;
  }}

  .dc-val {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 22px;
    font-weight: 700;
    margin-bottom: 6px;
    line-height: 1.1;
  }}

  .dc-val.hot  {{ color: var(--red); }}
  .dc-val.warm {{ color: var(--accent2); }}
  .dc-val.cool {{ color: var(--green); }}

  .dc-note {{
    font-size: 13px;
    color: var(--label);
    line-height: 1.55;
  }}

  .co-list {{
    background: var(--surface);
    border-radius: 18px;
    padding: 6px 24px;
    box-shadow: var(--shadow-dark);
  }}

  .co-row {{
    display: flex;
    align-items: flex-start;
    gap: 18px;
    padding: 22px 0;
    border-bottom: 1px solid var(--border);
  }}

  .co-row:last-child {{ border-bottom: none; }}

  .tkr-wrap {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }}

  .tkr-logo {{
    width: 40px;
    height: 40px;
    border-radius: 50%;
    object-fit: contain;
    background: var(--surface2);
    padding: 5px;
    box-shadow: 0 4px 12px -4px rgba(0,0,0,0.2);
  }}

  .tkr {{
    font-size: 11px;
    font-weight: 700;
    background: var(--surface2);
    border: 1px solid var(--border);
    padding: 4px 12px;
    border-radius: 8px;
    color: var(--text);
    min-width: 70px;
    text-align: center;
  }}

  .co-body {{
    flex: 1;
    min-width: 0;
  }}

  .co-desc {{
    font-size: 14.5px;
    line-height: 1.65;
    color: var(--text);
    margin-bottom: 10px;
  }}

  .co-desc strong {{ font-weight: 700; }}

  .co-stats {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    font-size: 12px;
    padding-top: 8px;
    border-top: 1px dashed var(--border);
  }}

  .co-stat {{
    display: inline-flex;
    gap: 6px;
    align-items: baseline;
  }}

  .co-stat-lbl {{
    font-size: 9.5px;
    letter-spacing: 0.1em;
    color: var(--muted);
    text-transform: uppercase;
    font-weight: 700;
  }}

  .co-stat-val {{
    font-weight: 700;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
  }}

  .co-mv {{
    font-size: 14px;
    font-weight: 700;
    margin-top: 4px;
    white-space: nowrap;
  }}

  .crypto-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 14px;
    margin-bottom: 32px;
  }}

  .cc {{
    background: var(--surface);
    padding: 24px;
    border-radius: 16px;
    box-shadow: var(--shadow-dark);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}

  .cc-head {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}

  .cc-logo {{
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: contain;
    background: var(--surface2);
    padding: 3px;
    flex-shrink: 0;
  }}

  .cc-name {{
    font-size: 11px;
    letter-spacing: 0.12em;
    color: var(--muted);
    text-transform: uppercase;
    font-weight: 700;
  }}

  .cc-price {{
    font-family: 'Space Grotesk', sans-serif;
    font-size: 28px;
    font-weight: 700;
    line-height: 1;
  }}

  .cc-chg {{
    font-size: 13px;
    font-weight: 700;
  }}

  .cc-range {{
    font-size: 11.5px;
    color: var(--label);
    display: flex;
    gap: 8px;
    align-items: baseline;
    padding-top: 4px;
    border-top: 1px dashed var(--border);
  }}

  .cc-range-lbl {{
    font-size: 9.5px;
    letter-spacing: 0.1em;
    color: var(--muted);
    text-transform: uppercase;
    font-weight: 700;
  }}

  .cc-range-val {{
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    color: var(--text);
  }}

  .cc-desc {{
    font-size: 13px;
    line-height: 1.6;
    color: var(--label);
  }}

  .table-wrap {{
    background: var(--surface);
    border-radius: 18px;
    overflow: hidden;
    box-shadow: var(--shadow-dark);
  }}

  .gtable {{
    width: 100%;
    border-collapse: collapse;
  }}

  .gtable th {{
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    padding: 14px 18px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-weight: 700;
    background: var(--surface3);
  }}

  .gtable td {{
    padding: 16px 18px;
    font-size: 14px;
    color: var(--text);
    border-bottom: 1px solid var(--border);
    vertical-align: top;
    line-height: 1.6;
  }}

  .gtable tr:last-child td {{ border-bottom: none; }}
  .gtable td:first-child {{ font-weight: 700; white-space: nowrap; }}
  .gtable td:nth-child(2) {{ font-weight: 700; width: 120px; font-family: 'Space Grotesk', sans-serif; }}
  .gtable td:nth-child(3) {{ font-weight: 700; width: 100px; }}

  .takeaway {{
    background: var(--surface);
    border-left: 5px solid var(--accent);
    padding: 32px 36px;
    border-radius: 16px;
    font-size: 15px;
    line-height: 1.75;
    box-shadow: 0 12px 32px -12px rgba(0,240,255,0.22);
    color: var(--text);
  }}

  .ahead-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  }}

  .ahead-cell {{
    background: var(--surface);
    padding: 24px;
    border-radius: 16px;
    box-shadow: var(--shadow-dark);
  }}

  .ahead-day {{
    font-size: 10px;
    letter-spacing: 0.12em;
    color: var(--accent);
    font-weight: 700;
    text-transform: uppercase;
    margin-bottom: 10px;
  }}

  .ahead-ev {{
    font-size: 14px;
    line-height: 1.65;
    color: var(--text);
  }}

  .chart-wrap {{
    background: var(--surface);
    padding: 32px;
    border-radius: 20px;
    box-shadow: var(--shadow-dark);
  }}

  .chart-hdr {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 18px;
    gap: 12px;
    flex-wrap: wrap;
  }}

  .chart-lbl {{
    font-size: 10px;
    letter-spacing: 0.12em;
    color: var(--muted);
    text-transform: uppercase;
    font-weight: 700;
  }}

  .footer {{
    border-top: 1px solid var(--border);
    padding: 32px 60px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    font-size: 10.5px;
    color: var(--muted);
  }}

  @media (max-width: 980px) {{
    .two-col, .ahead-grid {{ grid-template-columns: 1fr; }}
  }}

  @media (max-width: 820px) {{
    .masthead, .container, .footer {{ padding-left: 24px; padding-right: 24px; }}
    .idx-grid, .crypto-grid, .data-row {{ grid-template-columns: 1fr; }}
    .masthead-row, .chart-hdr {{ align-items: flex-start; }}
    .masthead-meta {{ justify-content: flex-start; }}
  }}

  @media (prefers-reduced-motion: reduce) {{
    * {{
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }}
  }}
</style>
</head>
<body>
<div class="top-nav-wrapper">
  <div class="masthead">
    <div class="masthead-row">
      <div>
        <div class="kicker">WEEKLY MARKET SUMMARY &bull; U.S. EQUITIES &amp; DIGITAL ASSETS</div>
        <div class="week-title header-font">{week_start_str} &ndash; <span>{today_str}</span>, {year_str}</div>
      </div>
      <div class="masthead-meta">
        <div class="badge {badge_color}">{market_tone}</div>
        <div class="pub-date">Published {full_date} &bull; Post-Market Close</div>
        <button onclick="toggleTheme()" class="theme-btn" title="Toggle light/dark mode" aria-label="Toggle theme">&#x1F317;</button>
      </div>
    </div>
  </div>
  {ticker_html}
</div>

<div class="container">
  <div class="section">
    <div class="sec-label">SECTION 01</div>
    <div class="sec-title">Major U.S. Indices</div>
    <div class="idx-grid">
      <a href="https://www.perplexity.ai/finance/%5ESPX" target="_blank" rel="noopener noreferrer">
        <div class="idx-card {sp_card_class}">
          <div class="idx-name">S&amp;P 500</div>
          <div class="idx-close">{sp['end_price']:,.2f}</div>
          <div class="idx-wtd {'pos' if sp_pct >= 0 else 'neg'}">{'&#9650;' if sp_pct >= 0 else '&#9660;'} {'+' if sp_pct >= 0 else ''}{sp_pct}% WTD</div>
          <div class="idx-note">Broad-market benchmark reflecting the 500 largest U.S. companies.</div>
        </div>
      </a>
      <a href="https://www.perplexity.ai/finance/%5EIXIC" target="_blank" rel="noopener noreferrer">
        <div class="idx-card {nd_card_class}">
          <div class="idx-name">Nasdaq Composite</div>
          <div class="idx-close">{nd['end_price']:,.2f}</div>
          <div class="idx-wtd {'pos' if nd['pct_change'] >= 0 else 'neg'}">{'&#9650;' if nd['pct_change'] >= 0 else '&#9660;'} {'+' if nd['pct_change'] >= 0 else ''}{nd['pct_change']}% WTD</div>
          <div class="idx-note">Tech-driven index led by growth and semiconductor leaders.</div>
        </div>
      </a>
      <a href="https://www.perplexity.ai/finance/%5EDJI" target="_blank" rel="noopener noreferrer">
        <div class="idx-card {dj_card_class}">
          <div class="idx-name">Dow Jones Industrial Average</div>
          <div class="idx-close">{dj['end_price']:,.2f}</div>
          <div class="idx-wtd {'pos' if dj['pct_change'] >= 0 else 'neg'}">{'&#9650;' if dj['pct_change'] >= 0 else '&#9660;'} {'+' if dj['abs_change'] >= 0 else ''}{int(abs(dj['abs_change'])):,} pts WTD</div>
          <div class="idx-note">Price-weighted gauge of 30 blue-chip U.S. corporations.</div>
        </div>
      </a>
    </div>
    <ul class="blist">
      <li><strong>Market Tone:</strong> U.S. equities finished the week {'higher' if sp_pct >= 0 else 'lower'}, with the S&amp;P 500 recording a {'+' if sp_pct >= 0 else ''}{sp_pct}% move.</li>
      <li><strong>Volatility Profile:</strong> The VIX closed the week at {vix_close:.2f}. Levels below 20 generally indicate a calmer equity environment, while prints above 20 signal elevated hedging activity.</li>
    </ul>
  </div>

  <div class="section">
    <div class="sec-label">SECTION 02</div>
    <div class="sec-title">Sector Performance</div>
    <div class="two-col" style="margin-bottom:26px;">
      <div>
        <div class="col-lbl lead">&#9650; TOP PERFORMING SECTORS</div>
        <div class="tag-row">{top_tags}</div>
        <ul class="blist">
          <li>{sector_bullets['top_bullet1']}</li>
          <li>{sector_bullets['top_bullet2']}</li>
        </ul>
      </div>
      <div>
        <div class="col-lbl lag">&#9660; LAGGING SECTORS</div>
        <div class="tag-row">{bot_tags}</div>
        <ul class="blist">
          <li>{sector_bullets['bot_bullet1']}</li>
          <li>{sector_bullets['bot_bullet2']}</li>
        </ul>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="sec-label">SECTION 03</div>
    <div class="sec-title">Key Macro &amp; Rates Data</div>
    <div class="data-row">
      <div class="dcell">
        <div class="dc-lbl">10-Yr Treasury Yield</div>
        <div class="dc-val {'hot' if tnx['pct_change'] >= 0 else 'cool'}">{tnx['end_price']:.2f}%</div>
        <div class="dc-note">Yield {'rose' if tnx['pct_change'] >= 0 else 'fell'} WTD, acting as a primary driver for broader equity valuations and sector rotation.</div>
      </div>
      <div class="dcell">
        <div class="dc-lbl">U.S. Dollar Index (DXY)</div>
        <div class="dc-val {'hot' if dxy['pct_change'] >= 0 else 'cool'}">{dxy['end_price']:.2f}</div>
        <div class="dc-note">The dollar {'strengthened' if dxy['pct_change'] >= 0 else 'weakened'} by {abs(dxy['pct_change']):.2f}% over the 5-day period, impacting multinational revenue expectations.</div>
      </div>
      <div class="dcell">
        <div class="dc-lbl">13-Week T-Bill Yield</div>
        <div class="dc-val">{irx['end_price']:.2f}%</div>
        <div class="dc-note">Tracks closely with the Federal Funds Rate. Yield moved by {abs(irx['pct_change']):.2f}% this week.</div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="sec-label">SECTION 04</div>
    <div class="sec-title">Mega-Cap Tech &amp; Key Movers</div>
    <div class="sec-intro">The five largest U.S. mega-cap tech constituents drive a disproportionate share of index-level moves. Each row below shows the weekly close, absolute dollar change, and the intraweek 5-day high/low range alongside the analyst note.</div>
    <div class="co-list">{megacap_html}</div>
  </div>

  <div class="section">
    <div class="sec-label">SECTION 05</div>
    <div class="sec-title">Cryptocurrency Market Recap</div>
    <div class="sec-intro">Weekly performance across the four most-tracked digital assets. Each tile shows the closing price, WTD change, the intraweek 5-day range, and an analyst note on what drove the move.</div>
    <div class="crypto-grid">{crypto_html}</div>
  </div>

  <div class="section">
    <div class="sec-label">SECTION 06</div>
    <div class="sec-title">Global Market Context</div>
    <div class="sec-intro">Non-U.S. developed and Asian market performance provides cross-border read-through on macro drivers, currency effects, and regional risk appetite.</div>
    <div class="table-wrap" style="margin-bottom:26px;">
      <table class="gtable">
        <thead><tr><th>Index / Asset</th><th>Close</th><th>WTD</th><th>Status</th></tr></thead>
        <tbody>
          {global_rows_html}
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="sec-label">SECTION 07</div>
    <div class="sec-title">Investor Takeaway</div>
    <div class="takeaway">{takeaway_text}</div>
  </div>

  <div class="section">
    <div class="sec-label">SECTION 08</div>
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
    <div class="sec-label">SECTION 09</div>
    <div class="sec-title">S&amp;P 500 &mdash; Daily Close {week_start_str}&ndash;{today_str}, {year_str}</div>
    <div class="chart-wrap">
      <div class="chart-hdr">
        <div class="chart-lbl">S&amp;P 500 (SPX) &bull; Actual Daily Closing Prices</div>
        <div class="chart-lbl">Live Data via yfinance &bull; AI Analysis via Claude</div>
      </div>
      <canvas id="spxChart" height="220"></canvas>
    </div>
  </div>
</div>

<div class="footer">
  <div>Automated Weekly Market Summary &bull; Post-Market Close Edition</div>
  <div>Live Data via yfinance &bull; AI Analysis via Claude &bull; {full_date}</div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
  const labels = {json.dumps(sp_dates)};
  const prices = {json.dumps(sp_data)};
  const root = document.documentElement;

  function getCssVar(name) {{
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }}

  const ctx = document.getElementById('spxChart').getContext('2d');
  let spxChart;

  function buildGradient(context, chartArea) {{
    const gradient = context.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    const isLight = document.documentElement.classList.contains('light');
    const accent  = isLight ? 'rgba(0,170,255,0.24)' : 'rgba(0,240,255,0.25)';
    const bottom  = isLight ? 'rgba(0,170,255,0.03)' : 'rgba(0,240,255,0.02)';
    gradient.addColorStop(0, accent);
    gradient.addColorStop(1, bottom);
    return gradient;
  }}

  function renderChart() {{
    const textMuted  = getCssVar('--muted');
    const isLight    = document.documentElement.classList.contains('light');
    const border     = isLight ? 'rgba(15,23,42,0.08)' : 'rgba(255,255,255,0.08)';
    const lineColor  = getCssVar('--accent');
    const pointBorder= getCssVar('--accent');

    if (spxChart) spxChart.destroy();

    spxChart = new Chart(ctx, {{
      type: 'line',
      data: {{
        labels,
        datasets: [{{
          label: 'S&P 500 Close',
          data: prices,
          borderColor: lineColor,
          backgroundColor: (context) => {{
            const chart = context.chart;
            const {{ ctx: c, chartArea }} = chart;
            if (!chartArea) return 'transparent';
            return buildGradient(c, chartArea);
          }},
          fill: true,
          tension: 0.4,
          borderWidth: 3,
          pointRadius: 5,
          pointHoverRadius: 8,
          pointBackgroundColor: '#fff',
          pointBorderColor: pointBorder,
          pointBorderWidth: 2
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: true,
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            mode: 'index',
            intersect: false,
            backgroundColor: isLight ? '#ffffff' : '#111118',
            titleColor: getCssVar('--text'),
            bodyColor: getCssVar('--text'),
            borderColor: getCssVar('--border'),
            borderWidth: 1
          }}
        }},
        scales: {{
          x: {{
            grid: {{ color: border, drawBorder: false }},
            ticks: {{ color: textMuted, font: {{ size: 11, weight: '600' }} }}
          }},
          y: {{
            grid: {{ color: border, drawBorder: false }},
            ticks: {{ color: textMuted, font: {{ size: 11, weight: '600' }},
              callback: v => v.toLocaleString() }}
          }}
        }}
      }}
    }});
  }}

  function toggleTheme() {{
    document.documentElement.classList.toggle('light');
    renderChart();
  }}

  renderChart();
</script>
</body>
</html>"""

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Successfully generated index.html for {full_date}")


if __name__ == "__main__":
    generate_html()
