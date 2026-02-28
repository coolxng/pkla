import yfinance as yf
import datetime
import json

def fetch_weekly_data(ticker_symbol):
    """Fetches the last 5 days of closing prices for a given ticker."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="5d")
        
        if len(hist) < 2:
            return [], [], 0.0, 0.0
            
        dates = [d.strftime('%a %m/%d') for d in hist.index]
        closes = [round(val, 2) for val in hist['Close'].tolist()]
        
        start_price = closes[0]
        end_price = closes[-1]
        pct_change = ((end_price - start_price) / start_price) * 100
        
        return dates, closes, end_price, round(pct_change, 2)
    except Exception:
        return [], [], 0.0, 0.0

def generate_html():
    print("Fetching market data...")
    
    # 1. Fetch Major Indices & Extract EXACT Dates from the market data
    sp_ticker = yf.Ticker('^GSPC')
    sp_hist = sp_ticker.history(period="5d")
    
    if len(sp_hist) >= 2:
        start_date = sp_hist.index[0]
        end_date = sp_hist.index[-1]
        week_start_str = start_date.strftime('%b %d').replace(' 0', ' ')
        today_str = end_date.strftime('%b %d').replace(' 0', ' ')
        year_str = end_date.strftime('%Y')
        full_date = end_date.strftime('%B %d, %Y')
    else:
        # Fallback if market is closed/error
        now = datetime.datetime.now()
        week_start_str = (now - datetime.timedelta(days=4)).strftime('%b %d')
        today_str = now.strftime('%b %d')
        year_str = now.strftime('%Y')
        full_date = now.strftime('%B %d, %Y')

    # Fetch remaining data
    sp_dates, sp_data, sp_close, sp_pct = fetch_weekly_data('^GSPC')    
    _, nd_data, nd_close, nd_pct = fetch_weekly_data('^IXIC')           
    _, dj_data, dj_close, dj_pct = fetch_weekly_data('^DJI')            
    _, vix_data, vix_close, vix_pct = fetch_weekly_data('^VIX')         
    _, tnx_data, tnx_close, tnx_pct = fetch_weekly_data('^TNX')         
    _, dxy_data, dxy_close, dxy_pct = fetch_weekly_data('DX-Y.NYB')

    # 2. Fetch Crypto
    _, _, btc_close, btc_pct = fetch_weekly_data('BTC-USD')      
    _, _, eth_close, eth_pct = fetch_weekly_data('ETH-USD')      
    _, _, sol_close, sol_pct = fetch_weekly_data('SOL-USD')
    _, _, xrp_close, xrp_pct = fetch_weekly_data('XRP-USD')

    # 3. Fetch Global
    _, _, n225_close, n225_pct = fetch_weekly_data('^N225')
    _, _, stoxx_close, stoxx_pct = fetch_weekly_data('^STOXX50E')

    # 4. Fetch & Sort Sectors
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
        _, _, _, pct = fetch_weekly_data(ticker)
        sector_perf[name] = pct
    
    sorted_sectors = sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)
    top_sectors = sorted_sectors[:4]
    bottom_sectors = sorted_sectors[-4:]

    # Formatting Helpers
    def fmt_chg(pct, is_yield=False):
        sign = "+" if pct >= 0 else ""
        color = "pos" if pct >= 0 else "neg"
        arrow = "▲" if pct >= 0 else "▼"
        suffix = " bps" if is_yield else "%"
        return f'<div class="t-chg {color}">{arrow} {sign}{pct}{suffix} This Week</div>'
        
    def fmt_card_chg(pct):
        sign = "+" if pct >= 0 else ""
        color = "pos" if pct >= 0 else "neg"
        arrow = "▲" if pct >= 0 else "▼"
        return f'<div class="idx-wtd {color}">{arrow} {sign}{pct}% This Week</div>'

    # Dynamic tone and borders
    sp_card_class = "up" if sp_pct >= 0 else ""
    nd_card_class = "up" if nd_pct >= 0 else ""
    dj_card_class = "up" if dj_pct >= 0 else ""
    
    market_tone = "▲ Risk-On / Rally" if sp_pct >= 0 else "⬇ Risk-Off / Pullback"
    badge_color = "badge-green" if sp_pct >= 0 else "badge-red"

    # Build Top/Bottom Sector Tags
    top_tags = "".join([f'<span class="tag g">{s[0]} ({"+" if s[1]>=0 else ""}{s[1]}%)</span>' for s in top_sectors])
    bot_tags = "".join([f'<span class="tag r">{s[0]} ({"+" if s[1]>=0 else ""}{s[1]}%)</span>' for s in bottom_sectors])

    # Build Mega-Cap Rows Dynamically
    mega_caps = {'AAPL': 'Apple', 'MSFT': 'Microsoft', 'NVDA': 'Nvidia', 'AMZN': 'Amazon', 'META': 'Meta Platforms'}
    mega_cap_html = ""
    for tk, name in mega_caps.items():
        _, _, c_close, c_pct = fetch_weekly_data(tk)
        c_color = "pos" if c_pct >= 0 else "neg"
        c_arrow = "▲" if c_pct >= 0 else "▼"
        c_sign = "+" if c_pct >= 0 else ""
        mega_cap_html += f'''
        <div class="co-row">
          <span class="tkr">{tk}</span>
          <div class="co-desc"><strong>{name}</strong> closed the week at ${c_close:,.2f}. As a core mega-cap constituent, its {c_sign}{c_pct}% weekly move heavily influenced the broader technology sector and market cap-weighted indices.</div>
          <span class="co-mv {c_color}">{c_arrow} {c_sign}{c_pct}%</span>
        </div>'''

    # Build HTML Template
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

  .masthead {{ padding: 52px 64px 40px; border-bottom: 1px solid var(--border); position: relative; overflow: hidden; }}
  .masthead::before {{ content: ''; position: absolute; top: -80px; right: -100px; width: 500px; height: 500px; background: radial-gradient(circle, rgba(232,200,74,0.055) 0%, transparent 65%); pointer-events: none; }}
  .masthead-row {{ display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 24px; }}
  .kicker {{ font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; }}
  .week-title {{ font-family: 'Playfair Display', serif; font-size: clamp(30px, 4.5vw, 54px); font-weight: 900; line-height: 1.05; letter-spacing: -0.025em; color: #fff; }}
  .week-title span {{ color: var(--accent); }}
  .masthead-meta {{ text-align: right; }}
  .badge {{ display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; letter-spacing: 0.14em; text-transform: uppercase; padding: 5px 12px; border-radius: 2px; margin-bottom: 8px; }}
  .badge-red {{ background: rgba(240,91,91,0.1); border: 1px solid rgba(240,91,91,0.28); color: var(--red); }}
  .badge-green {{ background: rgba(61,214,140,0.1); border: 1px solid rgba(61,214,140,0.28); color: var(--green); }}
  .pub-date {{ font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--muted); }}

  .ticker-bar {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 64px; display: flex; gap: 36px; flex-wrap: wrap; align-items: center; }}
  .t-item {{ display: flex; flex-direction: column; gap: 2px; }}
  .t-name {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: 0.16em; color: var(--muted); text-transform: uppercase; }}
  .t-val {{ font-family: 'IBM Plex Mono', monospace; font-size: 14px; font-weight: 500; color: #fff; }}
  .t-chg {{ font-family: 'IBM Plex Mono', monospace; font-size: 10px; }}
  .neg {{ color: var(--red); }} .pos {{ color: var(--green); }}
  .vdiv {{ width: 1px; height: 38px; background: var(--border); }}

  .container {{ max-width: 1120px; margin: 0 auto; padding: 0 64px 90px; }}
  .section {{ margin-top: 60px; padding-top: 56px; border-top: 1px solid var(--border); }}
  .section:first-child {{ border-top: none; padding-top: 0; }}
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
    .masthead,.ticker-bar,.container,.footer{{padding-left:20px;padding-right:20px;}}
    .idx-grid,.two-col,.crypto-grid,.ahead-grid{{grid-template-columns:1fr;}}
  }}
</style>
</head>
<body>

<!-- MASTHEAD -->
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

<!-- TICKER BAR -->
<div class="ticker-bar">
  <div class="t-item">
    <div class="t-name">S&amp;P 500</div>
    <div class="t-val">{sp_close:,.2f}</div>
    {fmt_chg(sp_pct)}
  </div>
  <div class="vdiv"></div>
  <div class="t-item">
    <div class="t-name">Nasdaq</div>
    <div class="t-val">{nd_close:,.2f}</div>
    {fmt_chg(nd_pct)}
  </div>
  <div class="vdiv"></div>
  <div class="t-item">
    <div class="t-name">DJIA</div>
    <div class="t-val">{dj_close:,.2f}</div>
    {fmt_chg(dj_pct)}
  </div>
  <div class="vdiv"></div>
  <div class="t-item">
    <div class="t-name">VIX</div>
    <div class="t-val">{vix_close:,.2f}</div>
    {fmt_chg(vix_pct)}
  </div>
  <div class="vdiv"></div>
  <div class="t-item">
    <div class="t-name">Bitcoin</div>
    <div class="t-val">${btc_close:,.0f}</div>
    {fmt_chg(btc_pct)}
  </div>
  <div class="vdiv"></div>
  <div class="t-item">
    <div class="t-name">10-Yr Yield</div>
    <div class="t-val">{tnx_close:,.2f}%</div>
    {fmt_chg(tnx_pct, is_yield=True)}
  </div>
</div>

<div class="container">

  <!-- ① INDICES -->
  <div class="section" style="margin-top:52px;padding-top:0;border-top:none;">
    <div class="sec-label">Section 01</div>
    <div class="sec-title">Major U.S. Indices</div>

    <div class="idx-grid">
      <div class="idx-card {sp_card_class}">
        <div class="idx-name">S&amp;P 500</div>
        <div class="idx-close">{sp_close:,.2f}</div>
        {fmt_card_chg(sp_pct)}
        <div class="idx-note">Reflects broad market performance across the 500 largest U.S. publicly traded companies.</div>
      </div>
      <div class="idx-card {nd_card_class}">
        <div class="idx-name">Nasdaq Composite</div>
        <div class="idx-close">{nd_close:,.2f}</div>
        {fmt_card_chg(nd_pct)}
        <div class="idx-note">Tech-heavy index heavily influenced by mega-cap growth and semiconductor equities.</div>
      </div>
      <div class="idx-card {dj_card_class}">
        <div class="idx-name">Dow Jones Industrial Avg.</div>
        <div class="idx-close">{dj_close:,.2f}</div>
        {fmt_card_chg(dj_pct)}
        <div class="idx-note">Price-weighted index representing 30 prominent blue-chip U.S. corporations.</div>
      </div>
    </div>
    
    <ul class="blist">
      <li><strong>Market Tone:</strong> U.S. equities finished the week {"higher" if sp_pct >= 0 else "lower"}, with the S&P 500 recording a {sp_pct}% move.</li>
      <li><strong>Volatility Profile:</strong> The VIX closed the week at {vix_close:,.2f}. Levels below 20 generally indicate a calmer equity environment, while prints above 20 signal elevated hedging activity.</li>
    </ul>
  </div>

  <!-- ② SECTORS -->
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

  <!-- ③ MACRO -->
  <div class="section">
    <div class="sec-label">Section 03</div>
    <div class="sec-title">Key Macro &amp; Rates Data</div>

    <div class="data-row">
      <div class="dcell">
        <div class="dc-lbl">10-Yr Treasury Yield</div>
        <div class="dc-val {'hot' if tnx_pct >= 0 else 'cool'}">{tnx_close:,.2f}%</div>
        <div class="dc-note">Yield {"rose" if tnx_pct >= 0 else "fell"} by {abs(tnx_pct)} bps this week, acting as a primary driver for broader equity valuations and sector rotation.</div>
      </div>
      <div class="dcell">
        <div class="dc-lbl">U.S. Dollar Index (DXY)</div>
        <div class="dc-val {'hot' if dxy_pct >= 0 else 'cool'}">{dxy_close:,.2f}</div>
        <div class="dc-note">The Dollar {"strengthened" if dxy_pct >= 0 else "weakened"} by {abs(dxy_pct)}% over the 5-day period, impacting multinational revenue expectations.</div>
      </div>
      <div class="dcell">
        <div class="dc-lbl">Volatility Index (VIX)</div>
        <div class="dc-val {'hot' if vix_close >= 20 else 'cool'}">{vix_close:,.2f}</div>
        <div class="dc-note">A weekly change of {vix_pct}%. Currently trading in the {"Fear/Hedging Zone" if vix_close >= 20 else "Normal/Calm Zone"}, reflecting institutional positioning.</div>
      </div>
    </div>
  </div>

  <!-- ④ COMPANIES -->
  <div class="section">
    <div class="sec-label">Section 04</div>
    <div class="sec-title">Mega-Cap Tech &amp; Key Movers</div>

    <div style="margin-bottom:20px;">
      {mega_cap_html}
    </div>
  </div>

  <!-- ⑤ CRYPTO -->
  <div class="section">
    <div class="sec-label">Section 05</div>
    <div class="sec-title">Cryptocurrency Market Recap</div>

    <div class="crypto-grid">
      <div class="cc">
        <div class="cc-name">Bitcoin (BTC)</div>
        <div class="cc-price">${btc_close:,.0f}</div>
        <div class="cc-chg {'pos' if btc_pct >= 0 else 'neg'}">{"▲" if btc_pct >= 0 else "▼"} {abs(btc_pct)}% WTD</div>
      </div>
      <div class="cc">
        <div class="cc-name">Ethereum (ETH)</div>
        <div class="cc-price">${eth_close:,.0f}</div>
        <div class="cc-chg {'pos' if eth_pct >= 0 else 'neg'}">{"▲" if eth_pct >= 0 else "▼"} {abs(eth_pct)}% WTD</div>
      </div>
      <div class="cc">
        <div class="cc-name">Solana (SOL)</div>
        <div class="cc-price">${sol_close:,.2f}</div>
        <div class="cc-chg {'pos' if sol_pct >= 0 else 'neg'}">{"▲" if sol_pct >= 0 else "▼"} {abs(sol_pct)}% WTD</div>
      </div>
      <div class="cc">
        <div class="cc-name">XRP</div>
        <div class="cc-price">${xrp_close:,.4f}</div>
        <div class="cc-chg {'pos' if xrp_pct >= 0 else 'neg'}">{"▲" if xrp_pct >= 0 else "▼"} {abs(xrp_pct)}% WTD</div>
      </div>
    </div>
  </div>

  <!-- ⑥ GLOBAL -->
  <div class="section">
    <div class="sec-label">Section 06</div>
    <div class="sec-title">Global Market Context</div>

    <table class="gtable" style="margin-bottom:26px;">
      <thead>
        <tr>
          <th>Index / Asset</th>
          <th>WTD Performance</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Nikkei 225 (Japan)</td>
          <td class="{'pos' if n225_pct >= 0 else 'neg'}">{"+" if n225_pct >= 0 else ""}{n225_pct}%</td>
          <td>Japanese equities tracked broader global momentum flows this week.</td>
        </tr>
        <tr>
          <td>Euro Stoxx 50 (EU)</td>
          <td class="{'pos' if stoxx_pct >= 0 else 'neg'}">{"+" if stoxx_pct >= 0 else ""}{stoxx_pct}%</td>
          <td>European blue-chip stocks digested the latest economic policy signaling.</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- ⑦ TAKEAWAY -->
  <div class="section">
    <div class="sec-label">Section 07</div>
    <div class="sec-title">Investor Takeaway</div>
    <div class="takeaway">
      U.S. equities finished the week <strong>{'higher' if sp_pct >= 0 else 'lower'}</strong>, with the S&P 500 registering a {sp_pct}% change, while the tech-heavy Nasdaq moved {nd_pct}%. Market internals showed capital flowing heavily into {top_sectors[0][0]} and {top_sectors[1][0]}, establishing them as the clear leaders for the week. Conversely, {bottom_sectors[0][0]} faced the most sustained pressure. In the fixed-income market, the 10-Year Treasury yield closed at {tnx_close}%, and the VIX volatility index settled at {vix_close}. In the digital asset space, Bitcoin moved {btc_pct}% over the last 5 days to close the traditional trading week near ${btc_close:,.0f}.
    </div>
  </div>

  <!-- ⑧ AHEAD -->
  <div class="section">
    <div class="sec-label">Section 08</div>
    <div class="sec-title">Looking Ahead to Next Week</div>

    <div class="ahead-grid" style="margin-bottom:24px;">
      <div class="ahead-cell">
        <div class="ahead-day">Macro &amp; Economic Data</div>
        <div class="ahead-ev">Investors will focus heavily on upcoming inflation prints and labor market reports to gauge the broader health of the consumer and the trajectory of monetary policy.</div>
      </div>
      <div class="ahead-cell">
        <div class="ahead-day">Federal Reserve Policy</div>
        <div class="ahead-ev">Speeches from regional Fed presidents and FOMC members will be closely monitored for clues regarding interest rate adjustments and balance sheet runoff.</div>
      </div>
    </div>
  </div>

  <!-- ⑨ CHART -->
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

<!-- FOOTER -->
<div class="footer">
  <div class="footer-txt">Automated Market Summary · Post Market Close Edition</div>
  <div class="footer-txt">Live Data Sourced via YFinance API · {full_date}</div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
// Injected Dynamic Data from Python
const labels = {json.dumps(sp_dates)};
const prices = {json.dumps(sp_data)};

const ctx = document.getElementById('spxChart').getContext('2d');
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
      }},
      annotation: {{}}
    }},
    scales: {{
      x: {{
        grid: {{ color: 'rgba(255,255,255,0.035)', drawBorder: false }},
        ticks: {{ color: '#5c6480', font: {{ family: 'IBM Plex Mono', size: 10 }} }},
        border: {{ display: false }}
      }},
      y: {{
        position: 'right',
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
    print("Successfully generated true data-driven index.html")

if __name__ == "__main__":
    generate_html()
