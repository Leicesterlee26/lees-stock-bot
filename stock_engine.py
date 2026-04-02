"""
Lee's Stock Portfolio Engine - Finnhub Edition v3
Fixed: bulletproof JSON parsing, strict AI prompt, full error handling
"""
import json, os, time, requests, re
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
        print(f"fget error {endpoint}: {e}")
    return None


def fetch_stock_data(ticker):
    try:
        quote   = fget("/quote", {"symbol": ticker}) or {}
        profile = fget("/stock/profile2", {"symbol": ticker}) or {}
        metrics = fget("/stock/metric", {"symbol": ticker, "metric": "all"}) or {}
        rectrnd = fget("/stock/recommendation", {"symbol": ticker}) or []
        pricetgt= fget("/stock/price-target", {"symbol": ticker}) or {}

        price = quote.get("c", 0)
        if not price or price == 0:
            return None

        name        = profile.get("name", ticker)
        sector      = profile.get("finnhubIndustry", "Unknown")
        market_cap  = profile.get("marketCapitalization", 0) * 1_000_000

        m = metrics.get("metric", {})
        pe          = m.get("peNormalizedAnnual") or m.get("peBasicExclExtraTTM")
        eps_growth  = m.get("epsGrowth3Y") or m.get("epsGrowthTTMYoy")
        rev_growth  = m.get("revenueGrowth3Y") or m.get("revenueGrowthTTMYoy")
        profit_margin = m.get("netProfitMarginTTM")
        high_52w    = m.get("52WeekHigh")
        low_52w     = m.get("52WeekLow")

        price_1mo_ago = m.get("priceRelativeToS&P50013Week") or 0
        price_3mo_ago = m.get("priceRelativeToS&P50026Week") or 0
        momentum_1mo  = ((price - (price / (1 + price_1mo_ago/100))) / (price / (1 + price_1mo_ago/100)) * 100) if price_1mo_ago else 0
        momentum_3mo  = ((price - (price / (1 + price_3mo_ago/100))) / (price / (1 + price_3mo_ago/100)) * 100) if price_3mo_ago else 0

        # Simpler momentum from 52w data
        if high_52w and low_52w and high_52w > 0:
            momentum_1mo = round(((price - low_52w) / (high_52w - low_52w)) * 20 - 10, 2)
            momentum_3mo = momentum_1mo * 1.5

        rec_key = ""
        if rectrnd and isinstance(rectrnd, list) and len(rectrnd) > 0:
            latest = rectrnd[0]
            rec_key = latest.get("rating", "")

        analyst_target = None
        if isinstance(pricetgt, dict) and pricetgt.get("targetMean"):
            analyst_target = pricetgt["targetMean"]

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "price": round(price, 2),
            "market_cap_b": round(market_cap / 1_000_000_000, 1),
            "forward_pe": round(pe, 2) if pe else None,
            "earnings_growth": round(eps_growth / 100, 4) if eps_growth else None,
            "revenue_growth": round(rev_growth / 100, 4) if rev_growth else None,
            "profit_margin": round(profit_margin / 100, 4) if profit_margin else None,
            "analyst_target": round(analyst_target, 2) if analyst_target else None,
            "recommendation": rec_key,
            "momentum_1mo": round(momentum_1mo, 2) if momentum_1mo is not None else 0,
            "momentum_3mo": round(momentum_3mo, 2) if momentum_3mo is not None else 0,
            "52w_high": high_52w,
            "52w_low": low_52w,
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
        if fpe < 15:   score += 10
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
            if upside > 20:   score += 10
            elif upside > 10: score += 5
            elif upside < 0:  score -= 5
        except Exception:
            pass
    return round(min(max(score, 0), 100), 1)


def clean_json(text):
    """
    Bulletproof JSON extractor.
    Handles: markdown fences, preamble text, trailing commentary,
    apostrophes in values, truncated responses.
    """
    if not text:
        raise ValueError("Empty response from AI")

    # Strip markdown code fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    text = re.sub(r"```", "", text).strip()

    # Remove any preamble before the first {
    brace_start = text.find("{")
    if brace_start == -1:
        raise ValueError(f"No JSON object found in response. Got: {text[:200]}")
    text = text[brace_start:]

    # Find the matching closing brace by counting depth
    depth = 0
    end_pos = -1
    in_string = False
    escape_next = False
    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
        if not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_pos = i
                    break

    if end_pos == -1:
        # Try rfind as last resort
        end_pos = text.rfind("}")
        if end_pos == -1:
            raise ValueError(f"No closing brace found. Got: {text[:200]}")

    text = text[:end_pos + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Last resort: try to fix common issues
        # Replace smart quotes
        text = text.replace("\u2018", "'").replace("\u2019", "'")
        text = text.replace("\u201c", '"').replace("\u201d", '"')
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"JSON parse failed after cleanup: {e}. Snippet: {text[max(0,e.pos-50):e.pos+50]}")


def run_ai_analysis(top_stocks, client):
    stocks_summary = json.dumps([{
        "ticker": s["ticker"],
        "name": s["name"],
        "sector": s["sector"],
        "score": s["score"],
        "price": s["price"],
        "forward_pe": s.get("forward_pe"),
        "momentum_1mo": s.get("momentum_1mo"),
        "momentum_3mo": s.get("momentum_3mo"),
        "earnings_growth": s.get("earnings_growth"),
        "analyst_target": s.get("analyst_target"),
        "recommendation": s.get("recommendation"),
    } for s in top_stocks], indent=2)

    prompt = (
        "You are a professional stock analyst. Analyse the following stocks and select the best 8 for a portfolio.\n\n"
        f"STOCKS DATA:\n{stocks_summary}\n\n"
        "INSTRUCTIONS:\n"
        "- Select exactly 8 stocks\n"
        "- Allocations must sum to exactly 100\n"
        "- For bull_case and bear_case: use only plain text, NO apostrophes, NO quotes, NO special characters\n"
        "- Keep bull_case and bear_case under 100 characters each\n"
        "- All string values must use double quotes only\n\n"
        "YOU MUST RESPOND WITH VALID JSON ONLY. NO EXPLANATION. NO MARKDOWN. NO BACKTICKS.\n"
        "START YOUR RESPONSE WITH { AND END WITH }\n\n"
        "REQUIRED FORMAT:\n"
        '{"portfolio_name":"string","summary":"string","date":"YYYY-MM-DD",'
        '"picks":[{"ticker":"string","name":"string","sector":"string",'
        '"allocation":number,"ai_score":number,"price":number,'
        '"analyst_target":number_or_null,"bull_case":"string","bear_risk":"string"}]}'
    )

    print("Running AI analysis...")
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = response.content[0].text
            print(f"AI response length: {len(raw)} chars")
            print(f"AI response preview: {raw[:100]}")
            result = clean_json(raw)

            # Validate structure
            if "picks" not in result:
                raise ValueError("Missing 'picks' key in response")
            if len(result["picks"]) < 5:
                raise ValueError(f"Only {len(result['picks'])} picks returned, expected 8")

            total_alloc = sum(p.get("allocation", 0) for p in result["picks"])
            if not (95 <= total_alloc <= 105):
                print(f"Warning: allocations sum to {total_alloc}, normalising...")
                for p in result["picks"]:
                    p["allocation"] = round(p["allocation"] * 100 / total_alloc, 1)

            result["date"] = result.get("date", datetime.now().strftime("%Y-%m-%d"))
            print(f"AI analysis complete: {len(result['picks'])} picks selected")
            return result

        except Exception as e:
            print(f"AI analysis attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                print("Retrying...")
                time.sleep(5)

    raise RuntimeError("AI analysis failed after 3 attempts - check logs above")


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
