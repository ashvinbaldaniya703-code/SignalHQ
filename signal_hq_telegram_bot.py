import os
import requests
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

# ========== YOUR API KEYS (DIRECTLY INSERTED) ==========
TELEGRAM_BOT_TOKEN = "8381016190:AAED0OqTzGEeiiJRet7udcGVxCPOpCGPk5o"
TELEGRAM_CHAT_ID = "711929429"

# Dhan Credentials
DHAN_CLIENT_ID = "1110607169"
DHAN_ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzc2MTMyODU4LCJpYXQiOjE3NzYwNDY0NTgsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTEwNjA3MTY5In0.4BgYc_CDu85o7mquXQ9LfrCpzMH9nEVjXGljg0k8clAxCvy9y7kBesClG3iz_0mWHOzCDWnDoGDnfykS4MlR3Q"

# =======================================================

# Initialize Dhan
from dhanhq import dhanhq
dhan = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
print("✅ Dhan API initialized with your token")

def send_telegram(text):
    """Send message to Telegram bot"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Telegram error: {r.text}")
    except Exception as e:
        print(f"Telegram send failed: {e}")

def get_nifty_option_chain():
    """Fetch NIFTY Option Chain from Dhan API"""
    try:
        underlying_security_id = "13"  # NIFTY security ID
        option_chain = dhan.option_chain(
            underlying_security_id=underlying_security_id,
            expiry_code="NEAREST"
        )
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

def calculate_max_pain(option_chain_df):
    """Calculate Max Pain (simplified)"""
    if option_chain_df is None or option_chain_df.empty:
        return None
    strikes = option_chain_df['strike'].values
    pain_values = []
    for strike in strikes:
        total_pain = 0
        for _, row in option_chain_df.iterrows():
            ce_pain = max(strike - row['strike'], 0) * row['ce_oi']
            pe_pain = max(row['strike'] - strike, 0) * row['pe_oi']
            total_pain += ce_pain + pe_pain
        pain_values.append(total_pain)
    max_pain_idx = np.argmin(pain_values)
    return strikes[max_pain_idx]

def get_historical_data(symbol, exchange_segment, instrument_type, days=30):
    """Get historical OHLC data from Dhan"""
    try:
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        historical = dhan.historical_daily_data(
            symbol=symbol,
            exchange_segment=exchange_segment,
            instrument_type=instrument_type,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d")
        )
        return historical
    except Exception as e:
        print(f"Historical data error: {e}")
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
    """Get GIFT NIFTY from Yahoo Finance (pre-market indicator)"""
    try:
        ticker = yf.Ticker("NIFTY1!")
        data = ticker.history(period="2d")
        if len(data) >= 2:
            last = data['Close'].iloc[-1]
            prev = data['Close'].iloc[-2]
            change = last - prev
            pct = (change / prev) * 100
            return {"price": round(last, 2), "change": round(change, 2), "pct": round(pct, 2)}
    except Exception as e:
        print(f"Gift Nifty error: {e}")
    return None

def generate_signal(name, price_data, option_chain=None):
    """Generate BUY/SELL/WAIT signal based on 8 indicators"""
    if price_data is None or len(price_data) < 30:
        return "WAIT", {}
    close_series = price_data['close']
    rsi_val = calculate_rsi(close_series)
    macd_val, macd_sig = calculate_macd(close_series)
    current_price = close_series.iloc[-1]
    ema9 = close_series.ewm(span=9).mean().iloc[-1]
    ema21 = close_series.ewm(span=21).mean().iloc[-1]
    ema50 = close_series.ewm(span=50).mean().iloc[-1]
    vwap = (price_data['volume'] * price_data['close']).sum() / price_data['volume'].sum()
    pcr = option_chain['pcr'].mean() if option_chain is not None and 'pcr' in option_chain else 1.0
    max_pain = calculate_max_pain(option_chain) if option_chain is not None else None

    bull_votes = 0
    bear_votes = 0
    if rsi_val < 35:
        bull_votes += 1
    elif rsi_val > 70:
        bear_votes += 1
    if macd_val > macd_sig:
        bull_votes += 1
    else:
        bear_votes += 1
    if current_price > ema9:
        bull_votes += 1
    else:
        bear_votes += 1
    if current_price > ema21:
        bull_votes += 1
    else:
        bear_votes += 1
    if current_price > ema50:
        bull_votes += 1
    else:
        bear_votes += 1
    if current_price > vwap:
        bull_votes += 1
    else:
        bear_votes += 1
    if pcr > 1.3:
        bull_votes += 1
    elif pcr < 0.7:
        bear_votes += 1
    if max_pain:
        if current_price > max_pain:
            bear_votes += 1
        elif current_price < max_pain:
            bull_votes += 1

    if bull_votes >= 6:
        signal = "🔴 STRONG BUY (CALL)"
    elif bull_votes >= 5:
        signal = "🟡 WEAK BUY (CALL)"
    elif bear_votes >= 6:
        signal = "🔴 STRONG SELL (PUT)"
    elif bear_votes >= 5:
        signal = "🟡 WEAK SELL (PUT)"
    else:
        signal = "⚪ WAIT"

    details = {
        "price": current_price,
        "rsi": round(rsi_val, 1),
        "macd": round(macd_val, 2),
        "macd_signal": round(macd_sig, 2),
        "ema9": round(ema9, 2),
        "ema21": round(ema21, 2),
        "ema50": round(ema50, 2),
        "vwap": round(vwap, 2),
        "pcr": round(pcr, 2),
        "max_pain": max_pain,
        "bull_votes": bull_votes,
        "bear_votes": bear_votes,
    }
    return signal, details

def create_pro_message():
    msg = "<b>📊 SIGNALHQ PRO (Dhan + Telegram)</b>\n"
    msg += f"🕒 {datetime.now().strftime('%d-%m-%Y %I:%M %p')} IST\n\n"
    
    gift = get_gift_nifty()
    if gift:
        dir_emoji = "📈" if gift["change"] > 0 else "📉"
        msg += f"<b>🎁 GIFT NIFTY (Pre-market)</b> {dir_emoji}\n"
        msg += f"Price: {gift['price']}  |  Change: {gift['change']:+.2f} ({gift['pct']:+.2f}%)\n\n"
    
    option_chain = get_nifty_option_chain()
    hist_data = get_historical_data("NIFTY", "NSE", "INDEX")
    
    if hist_data and len(hist_data) > 0:
        price_df = pd.DataFrame(hist_data)
        price_df['close'] = price_df['closePrice']
        price_df['volume'] = price_df['volume']
        signal, details = generate_signal("NIFTY", price_df, option_chain)
        
        msg += f"<b>🎯 NIFTY SIGNAL:</b> {signal}\n"
        msg += f"   Current: {details['price']:,.2f}\n"
        msg += f"   RSI: {details['rsi']} | PCR: {details['pcr']}\n"
        msg += f"   Bull Votes: {details['bull_votes']}/8 | Bear Votes: {details['bear_votes']}/8\n"
        if details['max_pain']:
            msg += f"   Max Pain Strike: {details['max_pain']:,.0f}\n"
        msg += "\n<b>📈 Key Levels</b>\n"
        msg += f"   EMA9: {details['ema9']:,.2f}\n"
        msg += f"   EMA21: {details['ema21']:,.2f}\n"
        msg += f"   EMA50: {details['ema50']:,.2f}\n"
        msg += f"   VWAP: {details['vwap']:,.2f}\n\n"
    else:
        msg += "⚠️ NIFTY historical data unavailable (using fallback)\n"
        try:
            ticker = yf.Ticker("^NSEI")
            data = ticker.history(period="1d")
            if not data.empty:
                last = data['Close'].iloc[-1]
                msg += f"   NIFTY Last (Yahoo): {last:,.2f}\n"
        except:
            pass
        msg += "\n"
    
    if option_chain is not None and not option_chain.empty and 'price' in details:
        atm_row = option_chain.iloc[(option_chain['strike'] - details['price']).abs().argsort()[:1]]
        msg += "<b>🏛️ OPTION CHAIN SUMMARY</b>\n"
        msg += f"   ATM Strike: {atm_row['strike'].values[0]:,.0f}\n"
        msg += f"   CE OI: {atm_row['ce_oi'].values[0]:,.0f} | PE OI: {atm_row['pe_oi'].values[0]:,.0f}\n"
        msg += f"   CE LTP: ₹{atm_row['ce_ltp'].values[0]:.2f} | PE LTP: ₹{atm_row['pe_ltp'].values[0]:.2f}\n"
        msg += f"   CE IV: {atm_row['ce_iv'].values[0]:.1f}% | PE IV: {atm_row['pe_iv'].values[0]:.1f}%\n"
        msg += f"   PCR: {atm_row['pcr'].values[0]:.2f}\n\n"
    
    if 'signal' in locals() and signal.startswith("STRONG BUY") or signal.startswith("WEAK BUY"):
        msg += "<b>💡 RECOMMENDATION</b>\n✅ Consider BUY CALL options near support\n"
        msg += f"🎯 Target: {details['price']*1.01:,.2f} | 🛑 SL: {details['price']*0.995:,.2f}\n"
    elif 'signal' in locals() and (signal.startswith("STRONG SELL") or signal.startswith("WEAK SELL")):
        msg += "<b>💡 RECOMMENDATION</b>\n✅ Consider BUY PUT options near resistance\n"
        msg += f"🎯 Target: {details['price']*0.99:,.2f} | 🛑 SL: {details['price']*1.005:,.2f}\n"
    else:
        msg += "<b>💡 RECOMMENDATION</b>\n⏳ WAIT - No clear direction. Monitor RSI/PCR extremes.\n"
    
    msg += "\n<code>⚠️ Educational purpose only. Trade at your own risk.</code>\n"
    msg += "\n#Nifty #BankNifty #OptionChain #SignalHQ"
    return msg

def main():
    print(f"[{datetime.now()}] Fetching market data via Dhan API...")
    try:
        message = create_pro_message()
        send_telegram(message)
        print(f"[{datetime.now()}] ✅ Message sent to Telegram")
    except Exception as e:
        error_msg = f"❌ Error: {str(e)}"
        print(error_msg)
        send_telegram(error_msg)

if __name__ == "__main__":
    while True:
        main()
        time.sleep(15 * 60)  # every 15 minutes