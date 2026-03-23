import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime

TELEGRAM_TOKEN = "8174540151:AAGQXOT3Wu7oxCoPQ5X5f51mI5TduRCsVCw"
TELEGRAM_CHAT_ID = "1095651243"

SYMBOLS = ["BTC-USD", "ETH-USD", "AAPL", "MSFT", "SPY"]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})

def get_data(symbol):
    try:
        return yf.download(symbol, period="2y", interval="1d", progress=False)
    except:
        return None

def strategy_ema(df):
    df = df.copy()
    df["fast"] = df["Close"].ewm(span=9).mean()
    df["slow"] = df["Close"].ewm(span=21).mean()
    df["signal"] = np.where(df["fast"] > df["slow"], 1, -1)
    df["ret"] = df["Close"].pct_change()
    df["strat"] = df["signal"].shift(1) * df["ret"]
    return df["strat"]

def strategy_rsi(df):
    df = df.copy()
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + gain / loss))
    sig = pd.Series(0, index=df.index)
    sig[rsi < 30] = 1
    sig[rsi > 70] = -1
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    df["ret"] = df["Close"].pct_change()
    return sig.shift(1) * df["ret"]

def strategy_bollinger(df):
    df = df.copy()
    ma = df["Close"].rolling(20).mean()
    std = df["Close"].rolling(20).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    sig = pd.Series(0, index=df.index)
    sig[df["Close"] < lower] = 1
    sig[df["Close"] > upper] = -1
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    df["ret"] = df["Close"].pct_change()
    return sig.shift(1) * df["ret"]

def metrics(returns):
    r = returns.dropna()
    if len(r) < 30:
        return None
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    total = (1 + r).prod() - 1
    cum = (1 + r).cumprod()
    dd = ((cum - cum.cummax()) / cum.cummax()).min()
    winrate = (r > 0).sum() / len(r)
    return {"sharpe": sharpe, "total": total, "dd": dd, "winrate": winrate}

def is_good(m):
    return m["sharpe"] > 1.0 and m["dd"] > -0.25 and m["total"] > 0.15

def main():
    print("Robô iniciado!")
    send_telegram("Robô de trading iniciado! Vou avisar-te quando encontrar algo lucrativo.")

    strategies = {
        "EMA Cross": strategy_ema,
        "RSI": strategy_rsi,
        "Bollinger": strategy_bollinger
    }

    while True:
        print(f"\nAnálise: {datetime.now().strftime('%H:%M %d/%m/%Y')}")
        found = []

        for symbol in SYMBOLS:
            df = get_data(symbol)
            if df is None or len(df) < 100:
                continue
            for name, func in strategies.items():
                try:
                    m = metrics(func(df))
                    if m and is_good(m):
                        found.append((symbol, name, m))
                        print(f"LUCRATIVO: {symbol} {name}")
                except:
                    pass

        if found:
            msg = "ESTRATÉGIAS LUCRATIVAS ENCONTRADAS!\n\n"
            for symbol, name, m in found:
                msg += f"{symbol} — {name}\n"
                msg += f"  Retorno: {m['total']:.1%}\n"
                msg += f"  Sharpe: {m['sharpe']:.2f}\n"
                msg += f"  Drawdown: {m['dd']:.1%}\n"
                msg += f"  Win Rate: {m['winrate']:.1%}\n\n"
            send_telegram(msg)
        else:
            send_telegram("Análise feita. Nada lucrativo ainda. Continuo a monitorizar...")

        print("Próxima análise em 6 horas...")
        time.sleep(21600)

if __name__ == "__main__":
    main()
