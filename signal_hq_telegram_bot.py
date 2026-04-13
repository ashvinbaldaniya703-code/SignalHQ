import os
import requests
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

# ========== YOUR API KEYS ==========
TELEGRAM_BOT_TOKEN = "8381016190:AAED0OqTzGEeiiJRet7udcGVxCPOpCGPk5o"
TELEGRAM_CHAT_ID = "711929429"
DHAN_CLIENT_ID = "1110607169"
DHAN_ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzc2MTMyODU4LCJpYXQiOjE3NzYwNDY0NTgsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTEwNjA3MTY5In0.4BgYc_CDu85o7mquXQ9LfrCpzMH9nEVjXGljg0k8clAxCvy9y7kBesClG3iz_0mWHOzCDWnDoGDnfykS4MlR3Q"

# ===================================

from dhanhq import dhanhq
dhan = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
print("✅ Dhan API initialized")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Telegram error: {r.text}")
    except Exception as e:
        print(f"Send failed: {e}")

def get_nifty_option_chain():
    try:
        underlying_security_id = "13"
        option_chain = dhan.option_chain(underlying_security_id=underlying_security_id, expiry_code="NEAREST")
        strikes = []
        for item in option_chain['data']:
            strikes.append({
                'strike': item['strikePrice'],
                'ce_oi': item['ce']['openInterest'],
                'ce_ltp': item['ce']['lastTradedPrice'],
                'ce_iv': item['ce']['impliedVolatility'],
                'pe_oi': item['pe']['openInterest'],
                'pe_ltp': item['pe']['lastTradedPrice'],
                'pe_iv': item['pe']['impliedVolatility'],
                'pcr': item['pe']['openInterest'] / max(item['ce']['openInterest'], 1)
            })
        return pd.DataFrame(strikes)
    except Exception as e:
        print(f"Option Chain error: {e}")
        return None

def calculate_max_pain(df):
    if df is None or df.empty:
        return None
    strikes = df['strike'].values
    pains = []
    for s in strikes:
        total = 0
        for _, r in df.iterrows():
            total += max(s - r['strike'], 0) * r['ce_oi']
            total += max(r['strike'] - s, 0) * r['pe_oi']
        pains.append(total)
    return strikes[np.argmin(pains)]

def get_historical_data(symbol, exchange_segment, instrument_type, days=30):
    try:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        return dhan.historical_daily_data(
            symbol=symbol,
            exchange_segment=exchange_segment,
            instrument_type=instrument_type,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d")
        )
    except Exception as e:
        print(f"Historical error: {e}")
        return None

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not rsi.empty else 50

def calculate_macd(series):
    exp1 = series.ewm(span=12, adjust=False).mean()
    exp2 = series.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd.iloc[-1], signal.iloc[-1]

def get_gift_nifty():
    try:
        ticker = yf.Ticker("NIFTY1!")
        data = ticker.history(period="2d")
        if len(data) >= 2:
            last = data['Close'].iloc[-1]
            prev = data['Close'].iloc[-2]
            change = last - prev
            pct = (change / prev) * 100
            return {"price": round(last, 2), "change": round(change, 2), "pct": round(pct, 2)}
    except:
        pass
    return None

def generate_signal(price_df, option_df):
    if price_df is None or len(price_df) < 30:
        return "WAIT", {}
    close = price_df['close']
    rsi = calculate_rsi(close)
    macd, macd_sig = calculate_macd(close)
    price = close.iloc[-1]
    ema9 = close.ewm(span=9).mean().iloc[-1]
    ema21 = close.ewm(span=21).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    vwap = (price_df['volume'] * price_df['close']).sum() / price_df['volume'].sum()
    pcr = option_df['pcr'].mean() if option_df is not None else 1.0
    max_pain = calculate_max_pain(option_df) if option_df is not None else None

    bull = bear = 0
    if rsi < 35: bull += 1
    elif rsi > 70: bear += 1
    if macd > macd_sig: bull += 1
    else: bear += 1
    if price > ema9: bull += 1
    else: bear += 1
    if price > ema21: bull += 1
    else: bear += 1
    if price > ema50: bull += 1
    else: bear += 1
    if price > vwap: bull += 1
    else: bear += 1
    if pcr > 1.3: bull += 1
    elif pcr < 0.7: bear += 1
    if max_pain:
        if price > max_pain: bear += 1
        elif price < max_pain: bull += 1

    if bull >= 6: sig = "🔴 STRONG BUY (CALL)"
    elif bull >= 5: sig = "🟡 WEAK BUY (CALL)"
    elif bear >= 6: sig = "🔴 STRONG SELL (PUT)"
    elif bear >= 5: sig = "🟡 WEAK SELL (PUT)"
    else: sig = "⚪ WAIT"

    details = {
        "price": price, "rsi": round(rsi, 1), "pcr": round(pcr, 2),
        "bull_votes": bull, "bear_votes": bear, "max_pain": max_pain,
        "ema9": round(ema9, 2), "ema21": round(ema21, 2), "ema50": round(ema50, 2), "vwap": round(vwap, 2)
    }
    return sig, details

def create_pro_message():
    msg = "<b>📊 SIGNALHQ PRO</b>\n"
    msg += f"🕒 {datetime.now().strftime('%d-%m-%Y %I:%M %p')} IST\n\n"

    gift = get_gift_nifty()
    if gift:
        emoji = "📈" if gift['change'] > 0 else "📉"
        msg += f"<b>🎁 GIFT NIFTY</b> {emoji}\n"
        msg += f"Price: {gift['price']}  |  Chg: {gift['change']:+.2f} ({gift['pct']:+.2f}%)\n\n"

    option_df = get_nifty_option_chain()
    hist = get_historical_data("NIFTY", "NSE", "INDEX")

    # Default values - this ensures 'signal' is ALWAYS defined
    signal = "⚪ WAIT"
    details = {"price": 0, "rsi": 50, "pcr": 1.0, "bull_votes": 0, "bear_votes": 0,
               "max_pain": None, "ema9": 0, "ema21": 0, "ema50": 0, "vwap": 0}

    if hist and len(hist) > 0:
        df = pd.DataFrame(hist)
        df['close'] = df['closePrice']
        df['volume'] = df['volume']
        signal, details = generate_signal(df, option_df)

        msg += f"<b>🎯 NIFTY SIGNAL:</b> {signal}\n"
        msg += f"   Current: {details['price']:,.2f}\n"
        msg += f"   RSI: {details['rsi']} | PCR: {details['pcr']}\n"
        msg += f"   Bull Votes: {details['bull_votes']}/8 | Bear: {details['bear_votes']}/8\n"
        if details.get('max_pain'):
            msg += f"   Max Pain Strike: {details['max_pain']:,.0f}\n"
        msg += "\n<b>📈 Key Levels</b>\n"
        msg += f"   EMA9: {details['ema9']:,.2f}\n"
        msg += f"   EMA21: {details['ema21']:,.2f}\n"
        msg += f"   EMA50: {details['ema50']:,.2f}\n"
        msg += f"   VWAP: {details['vwap']:,.2f}\n\n"
    else:
        msg += "⚠️ Historical data unavailable (Yahoo fallback)\n"
        try:
            ticker = yf.Ticker("^NSEI")
            data = ticker.history(period="1d")
            if not data.empty:
                msg += f"   NIFTY Last: {data['Close'].iloc[-1]:,.2f}\n"
        except:
            pass
        msg += "\n"

    if option_df is not None and not option_df.empty and details['price'] != 0:
        atm = option_df.iloc[(option_df['strike'] - details['price']).abs().argsort()[:1]]
        msg += "<b>🏛️ OPTION CHAIN SUMMARY</b>\n"
        msg += f"   ATM Strike: {atm['strike'].values[0]:,.0f}\n"
        msg += f"   CE OI: {atm['ce_oi'].values[0]:,.0f} | PE OI: {atm['pe_oi'].values[0]:,.0f}\n"
        msg += f"   CE LTP: ₹{atm['ce_ltp'].values[0]:.2f} | PE LTP: ₹{atm['pe_ltp'].values[0]:.2f}\n"
        msg += f"   CE IV: {atm['ce_iv'].values[0]:.1f}% | PE IV: {atm['pe_iv'].values[0]:.1f}%\n"
        msg += f"   PCR: {atm['pcr'].values[0]:.2f}\n\n"

    # Recommendation (signal is guaranteed to exist)
    if "STRONG BUY" in signal or "WEAK BUY" in signal:
        msg += "<b>💡 RECOMMENDATION</b>\n✅ BUY CALL near support\n"
        if details['price'] != 0:
            msg += f"🎯 Target: {details['price']*1.01:,.2f} | 🛑 SL: {details['price']*0.995:,.2f}\n"
    elif "STRONG SELL" in signal or "WEAK SELL" in signal:
        msg += "<b>💡 RECOMMENDATION</b>\n✅ BUY PUT near resistance\n"
        if details['price'] != 0:
            msg += f"🎯 Target: {details['price']*0.99:,.2f} | 🛑 SL: {details['price']*1.005:,.2f}\n"
    else:
        msg += "<b>💡 RECOMMENDATION</b>\n⏳ WAIT. Monitor RSI/PCR.\n"

    msg += "\n<code>⚠️ Educational only. Trade at your own risk.</code>\n"
    msg += "\n#Nifty #BankNifty #OptionChain #SignalHQ"
    return msg

def main():
    print(f"[{datetime.now()}] Starting...")
    try:
        msg = create_pro_message()
        send_telegram(msg)
        print("✅ Sent")
    except Exception as e:
        err = f"❌ Error: {str(e)}"
        print(err)
        send_telegram(err)

if __name__ == "__main__":
    while True:
        main()
        time.sleep(15 * 60)
