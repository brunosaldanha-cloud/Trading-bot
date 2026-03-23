import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import json
import os
from datetime import datetime
from itertools import product

TELEGRAM_TOKEN = "8174540151:AAGQXOT3Wu7oxCoPQ5X5f51mI5TduRCsVCw"
TELEGRAM_CHAT_ID = "1095651243"

# ══════════════════════════════════════════
# TICKERS - Cripto, Ações, ETFs, Commodities
# ══════════════════════════════════════════
SYMBOLS = [
    # Cripto
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    # Ações Tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA",
    # ETFs
    "SPY", "QQQ", "GLD", "TLT", "VXX",
    # Commodities
    "GC=F", "SI=F", "CL=F",
]

# ══════════════════════════════════════════
# TIMEFRAMES
# ══════════════════════════════════════════
TIMEFRAMES = [
    {"period": "1y",  "interval": "1d",  "name": "Diário"},
    {"period": "6mo", "interval": "1h",  "name": "1 Hora"},
    {"period": "1mo", "interval": "15m", "name": "15 Min"},
]

# ══════════════════════════════════════════
# FICHEIRO PARA GUARDAR APRENDIZAGEM
# ══════════════════════════════════════════
MEMORY_FILE = "bot_memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {"tested": {}, "best": [], "iterations": 0}

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

# ══════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=10)
    except:
        pass

# ══════════════════════════════════════════
# DOWNLOAD DE DADOS
# ══════════════════════════════════════════
def get_data(symbol, period, interval):
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df is None or len(df) < 50:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df
    except:
        return None

# ══════════════════════════════════════════
# INDICADORES TÉCNICOS
# ══════════════════════════════════════════
def add_indicators(df):
    df = df.copy()
    close = df["Close"]

    # EMAs múltiplas
    for span in [8, 13, 21, 34, 55, 89, 200]:
        df[f"ema{span}"] = close.ewm(span=span).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss))

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Bollinger Bands
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bb_upper"] = ma20 + 2 * std20
    df["bb_lower"] = ma20 - 2 * std20
    df["bb_pos"] = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])

    # ATR (volatilidade)
    high_low = df["High"] - df["Low"]
    df["atr"] = high_low.rolling(14).mean()

    # Volume trend
    df["vol_ma"] = df["Volume"].rolling(20).mean()
    df["vol_ratio"] = df["Volume"] / df["vol_ma"]

    # Momentum
    df["mom10"] = close.pct_change(10)
    df["mom20"] = close.pct_change(20)

    # Stochastic
    low14 = df["Low"].rolling(14).min()
    high14 = df["High"].rolling(14).max()
    df["stoch"] = 100 * (close - low14) / (high14 - low14)

    return df

# ══════════════════════════════════════════
# ESTRATÉGIAS
# ══════════════════════════════════════════
def strategy_ema_cross(df, fast=9, slow=21):
    sig = pd.Series(0, index=df.index)
    sig[df[f"ema{fast}"] > df[f"ema{slow}"]] = 1
    sig[df[f"ema{fast}"] < df[f"ema{slow}"]] = -1
    return sig

def strategy_rsi_bands(df, oversold=30, overbought=70):
    sig = pd.Series(0, index=df.index)
    sig[df["rsi"] < oversold] = 1
    sig[df["rsi"] > overbought] = -1
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    return sig

def strategy_macd(df):
    sig = pd.Series(0, index=df.index)
    sig[df["macd"] > df["macd_signal"]] = 1
    sig[df["macd"] < df["macd_signal"]] = -1
    return sig

def strategy_bollinger(df):
    sig = pd.Series(0, index=df.index)
    sig[df["bb_pos"] < 0.1] = 1
    sig[df["bb_pos"] > 0.9] = -1
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    return sig

def strategy_momentum(df, period=20):
    sig = pd.Series(0, index=df.index)
    mom = df[f"mom{period}"]
    sig[mom > 0.02] = 1
    sig[mom < -0.02] = -1
    return sig

def strategy_combined(df):
    # Combina múltiplos sinais
    s1 = strategy_ema_cross(df, 8, 21)
    s2 = strategy_macd(df)
    s3 = strategy_rsi_bands(df)
    combined = s1 + s2 + s3
    sig = pd.Series(0, index=df.index)
    sig[combined >= 2] = 1
    sig[combined <= -2] = -1
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    return sig

def strategy_volume_breakout(df):
    sig = pd.Series(0, index=df.index)
    high_vol = df["vol_ratio"] > 1.5
    sig[(high_vol) & (df["macd_hist"] > 0)] = 1
    sig[(high_vol) & (df["macd_hist"] < 0)] = -1
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    return sig

def strategy_stoch_rsi(df):
    sig = pd.Series(0, index=df.index)
    sig[(df["stoch"] < 20) & (df["rsi"] < 40)] = 1
    sig[(df["stoch"] > 80) & (df["rsi"] > 60)] = -1
    sig = sig.replace(0, np.nan).ffill().fillna(0)
    return sig

# ══════════════════════════════════════════
# MÉTRICAS DE PERFORMANCE
# ══════════════════════════════════════════
def backtest(signal, df):
    ret = df["Close"].pct_change()
    strat_ret = signal.shift(1) * ret
    strat_ret = strat_ret.dropna()

    if len(strat_ret) < 30:
        return None

    total = (1 + strat_ret).prod() - 1
    sharpe = strat_ret.mean() / strat_ret.std() * np.sqrt(252) if strat_ret.std() > 0 else 0
    cum = (1 + strat_ret).cumprod()
    max_dd = ((cum - cum.cummax()) / cum.cummax()).min()
    winrate = (strat_ret > 0).sum() / len(strat_ret)
    trades = (signal.diff() != 0).sum()
    avg_ret = strat_ret[strat_ret != 0].mean() if len(strat_ret[strat_ret != 0]) > 0 else 0

    return {
        "total": round(float(total), 4),
        "sharpe": round(float(sharpe), 3),
        "max_dd": round(float(max_dd), 4),
        "winrate": round(float(winrate), 3),
        "trades": int(trades),
        "avg_ret": round(float(avg_ret), 5),
    }

def is_profitable(m):
    return (
        m["sharpe"] > 1.2 and
        m["max_dd"] > -0.20 and
        m["total"] > 0.20 and
        m["winrate"] > 0.50 and
        m["trades"] > 10
    )

# ══════════════════════════════════════════
# ESTRATÉGIAS COM PARÂMETROS VARIÁVEIS
# ══════════════════════════════════════════
def get_all_strategies(df):
    strategies = []

    # EMA Cross com diferentes combinações
    ema_pairs = [(8,21),(8,34),(13,34),(13,55),(21,55),(21,89),(34,89)]
    for fast, slow in ema_pairs:
        try:
            sig = strategy_ema_cross(df, fast, slow)
            strategies.append((f"EMA {fast}/{slow}", sig))
        except: pass

    # RSI com diferentes bandas
    for oversold, overbought in [(25,75),(30,70),(35,65)]:
        try:
            sig = strategy_rsi_bands(df, oversold, overbought)
            strategies.append((f"RSI {oversold}/{overbought}", sig))
        except: pass

    # Restantes
    for name, func in [
        ("MACD", strategy_macd),
        ("Bollinger", strategy_bollinger),
        ("Combinada", strategy_combined),
        ("Volume Breakout", strategy_volume_breakout),
        ("Stoch+RSI", strategy_stoch_rsi),
        ("Momentum 10", lambda d: strategy_momentum(d, 10)),
        ("Momentum 20", lambda d: strategy_momentum(d, 20)),
    ]:
        try:
            sig = func(df)
            strategies.append((name, sig))
        except: pass

    return strategies

# ══════════════════════════════════════════
# LOOP PRINCIPAL
# ══════════════════════════════════════════
def main():
    print("Robô avançado iniciado!")
    send_telegram(
        "🤖 *Robô de Trading Avançado Iniciado!*\n\n"
        f"📊 A analisar {len(SYMBOLS)} ativos\n"
        f"⏱ Em {len(TIMEFRAMES)} timeframes\n"
        f"🧠 Com 20+ estratégias diferentes\n\n"
        "Vou avisar-te quando encontrar algo lucrativo! 💰"
    )

    memory = load_memory()
    iteration = memory.get("iterations", 0)

    while True:
        iteration += 1
        memory["iterations"] = iteration
        print(f"\n{'='*50}")
        print(f"Iteração #{iteration} — {datetime.now().strftime('%H:%M %d/%m/%Y')}")
        print(f"{'='*50}")

        found = []
        tested_count = 0

        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                print(f"  Analisando {symbol} [{tf['name']}]...")
                df = get_data(symbol, tf["period"], tf["interval"])
                if df is None:
                    continue

                df = add_indicators(df)
                strategies = get_all_strategies(df)

                for strat_name, signal in strategies:
                    key = f"{symbol}_{tf['name']}_{strat_name}"
                    tested_count += 1

                    m = backtest(signal, df)
                    if m is None:
                        continue

                    # Guarda na memória para aprender
                    memory["tested"][key] = m

                    if is_profitable(m):
                        found.append({
                            "symbol": symbol,
                            "timeframe": tf["name"],
                            "strategy": strat_name,
                            "metrics": m
                        })
                        print(f"  ✅ LUCRATIVO: {symbol} {strat_name} [{tf['name']}]")

        # Guarda memória
        save_memory(memory)

        # Envia resultados
        if found:
            # Ordena por Sharpe
            found.sort(key=lambda x: x["metrics"]["sharpe"], reverse=True)

            msg = f"🚨 *ESTRATÉGIAS LUCRATIVAS ENCONTRADAS!*\n"
            msg += f"_(Iteração #{iteration})_\n\n"

            for r in found[:5]:  # Top 5
                m = r["metrics"]
                msg += f"*{r['symbol']}* — {r['strategy']}\n"
                msg += f"⏱ Timeframe: {r['timeframe']}\n"
                msg += f"📈 Retorno: {m['total']:.1%}\n"
                msg += f"⚡ Sharpe: {m['sharpe']:.2f}\n"
                msg += f"📉 Drawdown: {m['max_dd']:.1%}\n"
                msg += f"🎯 Win Rate: {m['winrate']:.1%}\n"
                msg += f"🔄 Trades: {m['trades']}\n\n"

            send_telegram(msg)
        else:
            msg = (
                f"🔍 *Iteração #{iteration} concluída*\n"
                f"Testei {tested_count} combinações.\n"
                f"Nada lucrativo ainda. A continuar a aprender... 🧠"
            )
            send_telegram(msg)
            print(f"  Testadas {tested_count} combinações. Nada lucrativo.")

        print(f"\nPróxima análise em 4 horas...")
        time.sleep(14400)

if __name__ == "__main__":
    main()
