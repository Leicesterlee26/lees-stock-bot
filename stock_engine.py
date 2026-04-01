"""
Lee's Stock Portfolio Engine - Batch Mode
Uses yfinance batch download to avoid rate limiting
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


def fetch_all_stocks():
    """Fetch all stocks in one batch request - much faster and avoids rate limits."""
    scored = []
    try:
        tickers_str = " ".join(STOCK_UNIVERSE)
        print(f"Downloading batch data for {len(STOCK_UNIVERSE)} stocks...")
        data = yf.download(
            tickers_str,
            period="3mo",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True
        )
        print("Batch download complete, processing...")

        for ticker in STOCK_UNIVERSE:
            try:
                if ticker in data.columns.get_level_values(0):
                    hist = data[ticker].dropna()
                else:
                    continue

                if len(hist) < 10:
                    continue

                close = hist["Close"]
                volume = hist["Volume"]

                current_price = float(close.iloc[-1])
                price_1mo_ago = float(close.iloc[-22]) if len(close) >= 22 else float(close.iloc[0])
                price_3mo_ago = float(close.iloc[0])

                momentum_1mo = ((current_price - price_1mo_ago) / price_1mo_ago) * 100
                momentum_3mo = ((current_price - price_3mo_ago) / price_3mo_ago) * 100

                avg_vol_recent = float(volume.iloc[-10:].mean())
                avg_vol_prior = float(volume.iloc[-30:-10].mean())
                vol_trend = ((avg_vol_recent - avg_vol_prior) / avg_vol_prior) * 100 if avg_vol_prior > 0 else 0

                # Get fundamentals separately (lightweight call)
                try:
                    info = yf.Ticker(ticker).fast_info
                    market_cap = getattr(info, "market_cap", 0) or 0
                    last_price = getattr(info, "last_price", current_price) or current_price
                except Exception:
                    market_cap = 0
                    last_price = current_price

                stock_data = {
                    "ticker": ticker,
                    "name": ticker,
                    "sector": "Unknown",
                    "price": round(current_price, 2),
                    "market_cap_b": round(market_cap / 1e9, 1),
                    "pe_ratio": None,
                    "forward_pe": None,
                    "earnings_growth": None,
                    "revenue_growth": None,
                    "profit_margin": None,
                    "analyst_target": None,
                    "recommendation": "none",
                    "momentum_1mo": round(momentum_1mo, 1),
                    "momentum_3mo": round(momentum_3mo, 1),
                    "volume_trend": round(vol_trend, 1),
                }
                stock_data["score"] = score_stock(stock_data)
                scored.append(stock_data)

            except Exception as e:
                print(f"Error processing {ticker}: {e}")
                continue

    except Exception as e:
        print(f"Batch download error: {e}")

    print(f"Successfully scored {len(scored)} stocks")
    return scored


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
    if data.get("volume_trend", 0) > 15: score += 5
    elif data.get("volume_trend", 0) < -15: score -= 3
    return round(min(max(score, 0), 100), 1)


def run_ai_analysis(top_stocks, client):
    stocks_summary = json.dumps([{
        "ticker": s["ticker"], "name": s["name"], "sector": s["sector"],
        "score": s["score"], "price": s["price"],
        "momentum_1mo": s.get("momentum_1mo"), "momentum_3mo": s.get("momentum_3mo"),
        "volume_trend": s.get("volume_trend"),
    } for s in top_stocks], indent=2)

    today = datetime.now().strftime("%d %B %Y")
    date_str = datetime.now().strftime("%d %b %Y")

    prompt = (
        f"You are an autonomous AI portfolio manager. Today is {today}.\n"
        f"You have scored {len(top_stocks)} stocks by price momentum and volume trends.\n"
        "Select the BEST 10-12 for a growth-focused portfolio.\n\n"
        f"Stock data:\n{stocks_summary}\n\n"
        "INSTRUCTIONS: Select 10-12 stocks, balance sectors, assign allocation % totalling 100%.\n"
        "Provide 1-line bull thesis and 1-line bear risk for each.\n"
        "Give portfolio a name and overall thesis paragraph.\n\n"
        "Respond ONLY with valid JSON:\n"
        "{\n"
        '  "portfolio_name": "...",\n'
        '  "overall_thesis": "...",\n'
        f'  "date": "{date_str}",\n'
        '  "stocks": [\n'
        '    {"ticker":"AAPL","name":"Apple Inc","sector":"Technology","allocation_pct":10,\n'
        '     "score":72,"bull_case":"...","bear_risk":"...","analyst_target":null,"current_price":195}\n'
        "  ]\n}"
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def build_portfolio(client, status_callback=None):
    if status_callback:
        status_callback("Downloading market data (batch mode)...")

    scored = fetch_all_stocks()

    if not scored:
        raise ValueError("No stock data retrieved")

    scored.sort(key=lambda x: x["score"], reverse=True)
    top_30 = scored[:30]

    if status_callback:
        status_callback(f"Running AI analysis on top {len(top_30)} candidates...")

    portfolio = run_ai_analysis(top_30, client)
    portfolio["all_scored"] = scored[:50]
    return portfolio
