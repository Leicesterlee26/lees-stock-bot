"""
Lee's Stock Portfolio Engine
Scores stocks, runs AI bull/bear analysis, selects top portfolio picks
"""

import yfinance as yf
import pandas as pd
import anthropic
import json
import os
from datetime import datetime

STOCK_UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","JPM",
    "LLY","V","UNH","XOM","MA","COST","HD","PG","JNJ","ABBV","MRK","CVX",
    "CRM","BAC","NFLX","AMD","KO","WMT","PEP","TMO","CSCO","ACN","MCD","ABT",
    "ADBE","LIN","DHR","TXN","NKE","NEE","PM","AMGN","RTX","QCOM","MS","GS",
    "BLK","SPGI","INTU","CAT","ISRG","GE","SYK","BKNG","VRTX","AXP","NOW",
    "PLD","GILD","MDT","TJX","CB","ADI","REGN","MMC","ZTS","C","LRCX","MO",
    "BSX","SO","DUK","ITW","CL","ETN","AON","EMR","WM","FCX","PSX","USB",
    "SHW","APD","NSC","HCA","ICE","MCO","EW","CME","PH","KLAC","MCHP","ANET",
    "VST","OKTA","HALO","DVN","BAH"
]


def fetch_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="3mo")
        if hist.empty or len(hist) < 10:
            return None
        current_price = hist['Close'].iloc[-1]
        price_1mo_ago = hist['Close'].iloc[-22] if len(hist) >= 22 else hist['Close'].iloc[0]
        price_3mo_ago = hist['Close'].iloc[0]
        momentum_1mo = ((current_price - price_1mo_ago) / price_1mo_ago) * 100
        momentum_3mo = ((current_price - price_3mo_ago) / price_3mo_ago) * 100
        avg_vol_recent = hist['Volume'].iloc[-10:].mean()
        avg_vol_prior = hist['Volume'].iloc[-30:-10].mean()
        vol_trend = ((avg_vol_recent - avg_vol_prior) / avg_vol_prior) * 100 if avg_vol_prior > 0 else 0
        return {
            "ticker": ticker, "name": info.get("shortName", ticker),
            "sector": info.get("sector", "Unknown"), "price": round(current_price, 2),
            "market_cap_b": round(info.get("marketCap", 0) / 1e9, 1),
            "pe_ratio": info.get("trailingPE"), "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"), "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"), "profit_margin": info.get("profitMargins"),
            "roe": info.get("returnOnEquity"), "debt_to_equity": info.get("debtToEquity"),
            "momentum_1mo": round(momentum_1mo, 1), "momentum_3mo": round(momentum_3mo, 1),
            "volume_trend": round(vol_trend, 1), "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"), "analyst_target": info.get("targetMeanPrice"),
            "recommendation": info.get("recommendationKey", "none"),
        }
    except Exception:
        return None


def score_stock(data):
    score = 50.0
    if data.get("momentum_1mo") is not None:
        score += min(max(data["momentum_1mo"] * 0.8, -10), 10)
    if data.get("momentum_3mo") is not None:
        score += min(max(data["momentum_3mo"] * 0.3, -10), 10)
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
        except: pass
    if data.get("volume_trend", 0) > 15: score += 5
    elif data.get("volume_trend", 0) < -15: score -= 3
    return round(min(max(score, 0), 100), 1)


def run_ai_analysis(top_stocks, client):
    stocks_summary = json.dumps([{
        "ticker": s["ticker"], "name": s["name"], "sector": s["sector"],
        "score": s["score"], "price": s["price"], "forward_pe": s.get("forward_pe"),
        "momentum_1mo": s.get("momentum_1mo"), "momentum_3mo": s.get("momentum_3mo"),
        "earnings_growth": s.get("earnings_growth"), "revenue_growth": s.get("revenue_growth"),
        "analyst_target": s.get("analyst_target"), "recommendation": s.get("recommendation"),
    } for s in top_stocks], indent=2)

    prompt = f"""You are an autonomous AI portfolio manager. Today is {datetime.now().strftime('%d %B %Y')}.
You have scored {len(top_stocks)} stocks. Select the BEST 10-12 for a growth-focused portfolio.
For each, argue bull and bear case, then decide if it makes the cut.

Scoring data:
{stocks_summary}

INSTRUCTIONS:
- Select 10-12 stocks balancing sector exposure
- Assign allocation % (must total 100%)
- Provide 1-line bull thesis and 1-line bear risk per stock
- Give the portfolio a name and one-paragraph overall thesis

Respond ONLY with valid JSON:
{{
  "portfolio_name": "...",
  "overall_thesis": "...",
  "date": "{datetime.now().strftime('%d %b %Y')}",
  "stocks": [
    {{
      "ticker": "AAPL", "name": "Apple Inc", "sector": "Technology",
      "allocation_pct": 10, "score": 78.5,
      "bull_case": "...", "bear_risk": "...",
      "analyst_target": 230.00, "current_price": 195.50
    }}
  ]
}}"""

    response = client.messages.create(model="claude-opus-4-6", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}])
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return json.loads(raw.strip())


def build_portfolio(client, status_callback=None):
    if status_callback:
        status_callback("📊 Fetching market data...")
    scored = []
    for i, ticker in enumerate(STOCK_UNIVERSE):
        if status_callback and i % 20 == 0:
            status_callback(f"⏳ Scanning stocks... ({i}/{len(STOCK_UNIVERSE)})")
        data = fetch_stock_data(ticker)
        if data:
            data["score"] = score_stock(data)
            scored.append(data)
    if not scored:
        raise ValueError("No stock data retrieved")
    scored.sort(key=lambda x: x["score"], reverse=True)
    top_30 = scored[:30]
    if status_callback:
        status_callback(f"🤖 Running AI analysis on top {len(top_30)} candidates...")
    portfolio = run_ai_analysis(top_30, client)
    portfolio["all_scored"] = scored[:50]
    return portfolio
