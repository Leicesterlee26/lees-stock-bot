"""
Lee's Stock Portfolio Engine - Finnhub Edition
"""

import json, os, time, requests
from datetime import datetime

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
BASE = "https://finnhub.io/api/v1"

STOCK_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","JPM",
    "LLY","V","UNH","XOM","MA","COST","HD","PG","JNJ","ABBV","MRK","CVX",
    "CRM","BAC","NFLX","AMD","KO","WMT","PEP","TMO","CSCO","ACN","MCD","ABT",
    "ADBE","TXN","NKE","NEE","PM","AMGN","RTX","QCOM","MS","GS",
    "BLK","SPGI","INTU","CAT","ISRG","GE","SYK","BKNG","VRTX","AXP","NOW",
    "GILD","MDT","TJX","ADI","REGN","ZTS","LRCX","MO",
    "BSX","SO","DUK","ETN","EMR","WM","FCX","PSX",
    "SHW","NSC","HCA","ICE","MCO","CME","KLAC","MCHP","ANET","DVN","BAH"
]


def fget(endpoint, params):
    params["token"] = FINNHUB_KEY
    try:
        r = requests.get(f"{BASE}{endpoint}", params=params, timeout=10)
        if r.status_code == 429:
            print("Rate limited - sleeping 60s")
            time.sleep(60)
            r = requests.get(f"{BASE}{endpoint}", params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"API error {endpoint}: {e}")
    return {}


def fetch_stock_data(ticker):
    try:
        quote = fget("/quote", {"symbol": ticker})
        price = quote.get("c")
        if not price:
            return None
        metrics_resp = fget("/stock/metric", {"symbol": ticker, "metric": "all"})
        m = metrics_resp.get("metric", {})
        momentum_1mo = m.get("4WeekPriceReturnDaily")
        momentum_3mo = m.get("13WeekPriceReturnDaily")
        pe = m.get("peBasicExclExtraTTM") or m.get("peTTM")
        eps_growth = m.get("epsGrowthTTMYoy")
        rev_growth = m.get("revenueGrowthTTMYoy")
        profit_margin = m.get("netProfitMarginTTM")
        high_52w = m.get("52WeekHigh")
        low_52w = m.get("52WeekLow")
        profile = fget("/stock/profile2", {"symbol": ticker})
        name = profile.get("name", ticker)
        sector = profile.get("finnhubIndustry", "Unknown")
        market_cap = profile.get("marketCapitalization", 0)
        recs = fget("/stock/recommendation", {"symbol": ticker})
        rec_key = "none"
        analyst_target = None
        if recs and isinstance(recs, list) and len(recs) > 0:
            latest = recs[0]
            strong_buy = latest.get("strongBuy", 0)
            buy = latest.get("buy", 0)
            hold = latest.get("hold", 0)
            sell = latest.get("sell", 0) + latest.get("strongSell", 0)
            total = strong_buy + buy + hold + sell
            if total > 0:
                buy_ratio = (strong_buy + buy) / total
                if buy_ratio >= 0.7: rec_key = "strong_buy"
                elif buy_ratio >= 0.5: rec_key = "buy"
                elif sell / total >= 0.4: rec_key = "sell"
                else: rec_key = "hold"
        pt = fget("/stock/price-target", {"symbol": ticker})
        if pt.get("targetMean"):
            analyst_target = pt["targetMean"]
        return {
            "ticker": ticker, "name": name, "sector": sector,
            "price": round(price, 2),
            "market_cap_b": round(market_cap / 1000, 1),
            "forward_pe": round(pe, 2) if pe else None,
            "earnings_growth": round(eps_growth / 100, 4) if eps_growth else None,
            "revenue_growth": round(rev_growth / 100, 4) if rev_growth else None,
            "profit_margin": round(profit_margin / 100, 4) if profit_margin else None,
            "analyst_target": round(analyst_target, 2) if analyst_target else None,
            "recommendation": rec_key,
            "momentum_1mo": round(momentum_1mo, 2) if momentum_1mo is not None else 0,
            "momentum_3mo": round(momentum_3mo, 2) if momentum_3mo is not None else 0,
            "52w_high": high_52w, "52w_low": low_52w,
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None


def score_stock(data):
    score = 50.0
    m1 = data.get("momentum_1mo") or 0
    m3 = data.get("momentum_3mo") or 0
    score += min(max(m1 * 0.8, -10), 10)
    score += min(max(m3 * 0.3, -10), 10)
    fpe = data.get("forward_pe")
    if fpe and 0 < fpe < 50:
        if fpe < 15: score += 10
        elif fpe < 25: score += 5
        elif fpe > 35: score -= 8
    eg = data.get("earnings_growth")
    if eg and eg > 0: score += min(eg * 30, 15)
    rg = data.get("revenue_growth")
    if rg and rg > 0: score += min(rg * 20, 10)
    pm = data.get("profit_margin")
    if pm and pm > 0.15: score += 8
    elif pm and pm > 0.05: score += 4
    rec = data.get("recommendation", "").lower()
    if rec in ["strong_buy", "strongbuy"]: score += 8
    elif rec == "buy": score += 5
    elif rec in ["sell", "strong_sell"]: score -= 10
    if data.get("analyst_target") and data.get("price"):
        try:
            upside = ((data["analyst_target"] - data["price"]) / data["price"]) * 100
            if upside > 20: score += 7
            elif upside > 10: score += 4
            elif upside < -5: score -= 5
        except Exception: pass
    if m1 > 5: score += 5
    elif m1 < -10: score -= 3
    return round(min(max(score, 0), 100), 1)


def run_ai_analysis(top_stocks, client):
    stocks_summary = json.dumps([{
        "ticker": s["ticker"], "name": s["name"], "sector": s["sector"],
        "score": s["score"], "price": s["price"],
        "forward_pe": s.get("forward_pe"),
        "momentum_1mo": s.get("momentum_1mo"),
        "momentum_3mo": s.get("momentum_3mo"),
        "earnings_growth": s.get("earnings_growth"),
        "analyst_target": s.get("analyst_target"),
        "recommendation": s.get("recommendation"),
    } for s in top_stocks], indent=2)
    today = datetime.now().strftime("%d %B %Y")
    date_str = datetime.now().strftime("%d %b %Y")
    prompt = (
        f"You are an autonomous AI portfolio manager. Today is {today}.\n"
        f"You have scored {len(top_stocks)} S&P 500 stocks. "
        "Select the BEST 10-12 for a growth-focused portfolio.\n\n"
        f"Stock scoring data:\n{stocks_summary}\n\n"
        "Select 10-12 stocks, balance sectors, total allocation = 100%.\n"
        "1-line bull thesis and bear risk per stock.\n"
        "Give portfolio a name and overall thesis.\n\n"
        "Respond ONLY with valid JSON (no markdown):\n"
        "{\n  \"portfolio_name\": \"...\",\n  \"overall_thesis\": \"...\",\n"
        f"  \"date\": \"{date_str}\",\n"
        "  \"stocks\": [{\"ticker\":\"AAPL\",\"name\":\"Apple\",\"sector\":\"Technology\","
        "\"allocation_pct\":10,\"score\":78,\"bull_case\":\"...\","
        "\"bear_risk\":\"...\",\"analyst_target\":230,\"current_price\":255}]\n}"
    )
    response = client.messages.create(
        model="claude-opus-4-6", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw.strip())


def build_portfolio(client, status_callback=None):
    if not FINNHUB_KEY:
        raise ValueError("FINNHUB_API_KEY environment variable not set")
    if status_callback:
        status_callback("Fetching market data via Finnhub...")
    scored = []
    total = len(STOCK_UNIVERSE)
    for i, ticker in enumerate(STOCK_UNIVERSE):
        if status_callback and i % 10 == 0:
            status_callback(f"Scanning stocks... ({i}/{total})")
        data = fetch_stock_data(ticker)
        if data:
            data["score"] = score_stock(data)
            scored.append(data)
            print(f"  {ticker}: ${data['price']} | score={data['score']} | 1mo={data['momentum_1mo']}%")
        else:
            print(f"  {ticker}: no data")
        time.sleep(0.5)
    print(f"\nFetched {len(scored)}/{total} stocks")
    if not scored:
        raise ValueError("No stock data retrieved - check FINNHUB_API_KEY")
    scored.sort(key=lambda x: x["score"], reverse=True)
    top_30 = scored[:30]
    if status_callback:
        status_callback(f"Running AI analysis on top {len(top_30)} candidates...")
    portfolio = run_ai_analysis(top_30, client)
    portfolio["all_scored"] = scored[:50]
    return portfolio