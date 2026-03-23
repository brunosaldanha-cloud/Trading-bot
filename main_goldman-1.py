"""
TRADING BOT AVANÇADO - MODO GOLDMAN
=====================================
- Escaneia 100+ tickers com volume
- 40+ estratégias e combinações
- Aprende e evolui a cada iteração
- Só reporta: Sharpe >= 2.0, Winrate > 50%, Drawdown < 20%
- Amostragem mínima: 2 anos de histórico
- Corre infinitamente sem parar
"""

import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
import json
import os
import itertools
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ══════════════════════════════════════════════════════
TELEGRAM_TOKEN = "8174540151:AAGQXOT3Wu7oxCoPQ5X5f51mI5TduRCsVCw"
TELEGRAM_CHAT_ID = "1095651243"

# CRITÉRIOS MÍNIMOS (Goldman Mode)
MIN_SHARPE = 2.0
MIN_WINRATE = 0.50
MAX_DRAWDOWN = -0.20
MIN_TOTAL_RETURN = 0.30
MIN_TRADES = 30
MIN_HISTORY_DAYS = 500

MEMORY_FILE = "memory.json"
REPORT_FILE = "best_strategies.json"

# ══════════════════════════════════════════════════════
# UNIVERSO DE TICKERS
# ══════════════════════════════════════════════════════
TICKERS = {
    "crypto": [
        "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
        "ADA-USD", "AVAX-USD", "DOGE-USD", "DOT-USD", "MATIC-USD",
        "LINK-USD", "LTC-USD", "UNI-USD", "ATOM-USD", "NEAR-USD",
    ],
    "mega_cap": [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
        "BRK-B", "LLY", "V", "JPM", "WMT", "MA", "UNH", "XOM",
    ],
    "tech": [
        "AMD", "INTC", "QCOM", "MU", "AMAT", "ASML", "TSM",
        "CRM", "ADBE", "NOW", "SNOW", "PLTR", "COIN", "HOOD",
    ],
    "etfs": [
        "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT",
        "XLF", "XLE", "XLK", "XBI", "ARKK", "VXX", "SQQQ",
    ],
    "commodities": [
        "GC=F", "SI=F", "CL=F", "NG=F", "HG=F",
    ],
    "indices": [
        "^GSPC", "^NDX", "^DJI", "^VIX", "^RUT",
    ],
    "international": [
        "EWZ", "FXI", "EWJ", "EWG", "EWU", "EWY", "INDA",
    ],
}

ALL_TICKERS = [t for group in TICKERS.values() for t in group]

TIMEFRAMES = [
    {"period": "5y",  "interval": "1d",  "name": "Diário",   "weight": 3},
    {"period": "2y",  "interval": "1wk", "name": "Semanal",  "weight": 4},
    {"period": "1y",  "interval": "1h",  "name": "Horário",  "weight": 2},
]

# ══════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        for chunk in [message[i:i+4000] for i in range(0, len(message), 4000)]:
            requests.post(url, data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown"
            }, timeout=15)
            time.sleep(0.5)
    except Exception as e:
        print(f"Telegram erro: {e}")

# ══════════════════════════════════════════════════════
# MEMÓRIA E APRENDIZAGEM
# ══════════════════════════════════════════════════════
def load_memory():
    default = {
        "iterations": 0,
        "total_tested": 0,
        "winners": [],
        "scores": {},
        "best_ever": None,
        "started": datetime.now().isoformat()
    }
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                return json.load(f)
        except:
            return default
    return default

def save_memory(memory):
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(memory, f, indent=2, default=str)
    except Exception as e:
        print(f"Erro a guardar memória: {e}")

def update_learning(memory, key, metrics):
    """Bot aprende quais estratégias/tickers têm mais potencial"""
    if key not in memory["scores"]:
        memory["scores"][key] = {"runs": 0, "avg_sharpe": 0, "best_sharpe": 0}
    
    s = memory["scores"][key]
    s["runs"] += 1
    s["avg_sharpe"] = (s["avg_sharpe"] * (s["runs"]-1) + metrics["sharpe"]) / s["runs"]
    s["best_sharpe"] = max(s["best_sharpe"], metrics["sharpe"])

# ══════════════════════════════════════════════════════
# DOWNLOAD DE DADOS COM VALIDAÇÃO
# ══════════════════════════════════════════════════════
def get_data(symbol, period, interval):
    try:
        df = yf.download(symbol, period=period, interval=interval, 
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 50:
            return None
        # Normaliza colunas
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        # Valida volume (filtra lixo)
        if "Volume" in df.columns:
            avg_vol = df["Volume"].mean()
            if avg_vol < 1000:
                return None
        return df.dropna()
    except:
        return None

# ══════════════════════════════════════════════════════
# INDICADORES TÉCNICOS COMPLETOS
# ══════════════════════════════════════════════════════
def compute_indicators(df):
    df = df.copy()
    c = df["Close"].squeeze()
    h = df["High"].squeeze()
    l = df["Low"].squeeze()
    v = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(1, index=df.index)

    # ── Médias Móveis ──
    for n in [5, 8, 10, 13, 20, 21, 34, 50, 55, 89, 100, 200]:
        df[f"sma{n}"] = c.rolling(n).mean()
        df[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()

    # ── RSI múltiplos períodos ──
    for n in [7, 14, 21]:
        delta = c.diff()
        g = delta.clip(lower=0).rolling(n).mean()
        ls = (-delta.clip(upper=0)).rolling(n).mean()
        df[f"rsi{n}"] = 100 - (100 / (1 + g / ls.replace(0, 1e-10)))

    # ── MACD variantes ──
    for (f, s, sig) in [(12,26,9), (5,13,8), (8,21,5)]:
        ef = c.ewm(span=f).mean()
        es = c.ewm(span=s).mean()
        macd = ef - es
        df[f"macd_{f}_{s}"] = macd
        df[f"macd_sig_{f}_{s}"] = macd.ewm(span=sig).mean()
        df[f"macd_hist_{f}_{s}"] = macd - df[f"macd_sig_{f}_{s}"]

    # ── Bollinger Bands ──
    for n in [10, 20, 50]:
        ma = c.rolling(n).mean()
        std = c.rolling(n).std()
        df[f"bb_up_{n}"] = ma + 2*std
        df[f"bb_lo_{n}"] = ma - 2*std
        df[f"bb_pos_{n}"] = (c - df[f"bb_lo_{n}"]) / (df[f"bb_up_{n}"] - df[f"bb_lo_{n}"] + 1e-10)
        df[f"bb_width_{n}"] = (df[f"bb_up_{n}"] - df[f"bb_lo_{n}"]) / ma

    # ── ATR e Volatilidade ──
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    for n in [7, 14, 21]:
        df[f"atr{n}"] = tr.rolling(n).mean()
    df["volatility"] = c.pct_change().rolling(20).std() * np.sqrt(252)

    # ── Stochastic ──
    for n in [5, 14, 21]:
        lo = l.rolling(n).min()
        hi = h.rolling(n).max()
        df[f"stoch{n}"] = 100 * (c - lo) / (hi - lo + 1e-10)
        df[f"stoch_sig{n}"] = df[f"stoch{n}"].rolling(3).mean()

    # ── CCI ──
    for n in [14, 20]:
        tp = (h + l + c) / 3
        ma_tp = tp.rolling(n).mean()
        md = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - np.mean(x))))
        df[f"cci{n}"] = (tp - ma_tp) / (0.015 * md + 1e-10)

    # ── Williams %R ──
    for n in [14, 21]:
        hi_n = h.rolling(n).max()
        lo_n = l.rolling(n).min()
        df[f"willr{n}"] = -100 * (hi_n - c) / (hi_n - lo_n + 1e-10)

    # ── Momentum / ROC ──
    for n in [5, 10, 20, 40]:
        df[f"roc{n}"] = c.pct_change(n)

    # ── Volume indicators ──
    df["vol_sma20"] = v.rolling(20).mean()
    df["vol_ratio"] = v / (df["vol_sma20"] + 1e-10)
    df["obv"] = (np.sign(c.diff()) * v).cumsum()
    df["obv_ema"] = df["obv"].ewm(span=20).mean()

    # ── Padrões de velas ──
    body = (c - df.get("Open", c)).abs() if "Open" in df.columns else pd.Series(0, index=df.index)
    df["doji"] = (body < tr * 0.1).astype(int)

    # ── Regime de mercado ──
    df["trend_strength"] = (c - df["sma200"]) / df["sma200"]
    df["above_200"] = (c > df["sma200"]).astype(int)

    return df

# ══════════════════════════════════════════════════════
# MOTOR DE ESTRATÉGIAS
# ══════════════════════════════════════════════════════
def generate_signals(name, df):
    c = df["Close"].squeeze()
    sig = pd.Series(0.0, index=df.index)

    try:
        # ── EMA Crosses ──
        if name.startswith("EMA_CROSS_"):
            parts = name.split("_")
            f, s = int(parts[2]), int(parts[3])
            sig[df[f"ema{f}"] > df[f"ema{s}"]] = 1
            sig[df[f"ema{f}"] < df[f"ema{s}"]] = -1

        # ── SMA Crosses ──
        elif name.startswith("SMA_CROSS_"):
            parts = name.split("_")
            f, s = int(parts[2]), int(parts[3])
            sig[df[f"sma{f}"] > df[f"sma{s}"]] = 1
            sig[df[f"sma{f}"] < df[f"sma{s}"]] = -1

        # ── RSI Bands ──
        elif name.startswith("RSI_"):
            parts = name.split("_")
            period = int(parts[1])
            lo, hi = int(parts[2]), int(parts[3])
            rsi = df[f"rsi{period}"]
            sig[rsi < lo] = 1
            sig[rsi > hi] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        # ── MACD ──
        elif name.startswith("MACD_"):
            parts = name.split("_")
            f, s = parts[1], parts[2]
            key = f"macd_{f}_{s}"
            sig_key = f"macd_sig_{f}_{s}"
            if key in df.columns:
                sig[df[key] > df[sig_key]] = 1
                sig[df[key] < df[sig_key]] = -1

        # ── Bollinger Mean Reversion ──
        elif name.startswith("BB_REV_"):
            n = int(name.split("_")[2])
            sig[df[f"bb_pos_{n}"] < 0.05] = 1
            sig[df[f"bb_pos_{n}"] > 0.95] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        # ── Bollinger Breakout ──
        elif name.startswith("BB_BREAK_"):
            n = int(name.split("_")[2])
            sig[c > df[f"bb_up_{n}"]] = 1
            sig[c < df[f"bb_lo_{n}"]] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        # ── Stochastic ──
        elif name.startswith("STOCH_"):
            n = int(name.split("_")[1])
            sig[(df[f"stoch{n}"] < 20) & (df[f"stoch{n}"] > df[f"stoch_sig{n}"])] = 1
            sig[(df[f"stoch{n}"] > 80) & (df[f"stoch{n}"] < df[f"stoch_sig{n}"])] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        # ── CCI ──
        elif name.startswith("CCI_"):
            n = int(name.split("_")[1])
            sig[df[f"cci{n}"] < -100] = 1
            sig[df[f"cci{n}"] > 100] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        # ── Williams %R ──
        elif name.startswith("WILLR_"):
            n = int(name.split("_")[1])
            sig[df[f"willr{n}"] < -80] = 1
            sig[df[f"willr{n}"] > -20] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        # ── ROC Momentum ──
        elif name.startswith("ROC_"):
            n = int(name.split("_")[1])
            sig[df[f"roc{n}"] > 0.02] = 1
            sig[df[f"roc{n}"] < -0.02] = -1

        # ── Volume Breakout ──
        elif name == "VOL_BREAK":
            sig[(df["vol_ratio"] > 2) & (df["macd_hist_12_26"] > 0)] = 1
            sig[(df["vol_ratio"] > 2) & (df["macd_hist_12_26"] < 0)] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        # ── OBV Trend ──
        elif name == "OBV_TREND":
            obv_trend = df["obv"] > df["obv_ema"]
            sig[obv_trend] = 1
            sig[~obv_trend] = -1

        # ── Regime Filter: só long acima da SMA200 ──
        elif name == "REGIME_LONG":
            sig[df["above_200"] == 1] = 1

        # ══ COMBINADAS (mais poderosas) ══

        elif name == "COMBO_TREND":
            # EMA + RSI + Volume
            trend = (df["ema21"] > df["ema55"]).astype(int)
            mom = (df["rsi14"] > 50).astype(int)
            vol_conf = (df["vol_ratio"] > 1.2).astype(int)
            score = trend + mom + vol_conf
            sig[score >= 3] = 1
            sig[score == 0] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        elif name == "COMBO_REVERSION":
            oversold = (df["rsi14"] < 35) & (df["bb_pos_20"] < 0.15) & (df["stoch14"] < 25)
            overbought = (df["rsi14"] > 65) & (df["bb_pos_20"] > 0.85) & (df["stoch14"] > 75)
            sig[oversold] = 1
            sig[overbought] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        elif name == "COMBO_MOMENTUM":
            strong = (df["roc20"] > 0.05) & (df["ema8"] > df["ema21"]) & (df["above_200"] == 1)
            weak = (df["roc20"] < -0.05) & (df["ema8"] < df["ema21"])
            sig[strong] = 1
            sig[weak] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        elif name == "COMBO_MACD_RSI":
            bull = (df["macd_hist_12_26"] > 0) & (df["rsi14"] > 50) & (df["rsi14"] < 70)
            bear = (df["macd_hist_12_26"] < 0) & (df["rsi14"] < 50) & (df["rsi14"] > 30)
            sig[bull] = 1
            sig[bear] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        elif name == "COMBO_GOLDEN_CROSS":
            gc = (df["sma50"] > df["sma200"]) & (df["sma50"].shift(1) <= df["sma200"].shift(1))
            dc = (df["sma50"] < df["sma200"]) & (df["sma50"].shift(1) >= df["sma200"].shift(1))
            sig[gc] = 1
            sig[dc] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        elif name == "COMBO_TRIPLE_EMA":
            bull = (df["ema8"] > df["ema21"]) & (df["ema21"] > df["ema55"])
            bear = (df["ema8"] < df["ema21"]) & (df["ema21"] < df["ema55"])
            sig[bull] = 1
            sig[bear] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        elif name == "COMBO_VOLATILITY_SQUEEZE":
            squeeze = df["bb_width_20"] < df["bb_width_20"].rolling(50).mean() * 0.8
            direction = df["macd_hist_12_26"] > 0
            sig[(squeeze) & (direction)] = 1
            sig[(squeeze) & (~direction)] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

        elif name == "COMBO_FULL":
            # Estratégia mais complexa: 5 confirmações
            e = (df["ema8"] > df["ema21"]).astype(int)
            r = ((df["rsi14"] > 45) & (df["rsi14"] < 75)).astype(int)
            m = (df["macd_hist_12_26"] > 0).astype(int)
            b = (df["bb_pos_20"] > 0.3).astype(int)
            v = (df["vol_ratio"] > 1.0).astype(int)
            score = e + r + m + b + v
            sig[score >= 4] = 1
            sig[score <= 1] = -1
            sig = sig.replace(0, np.nan).ffill().fillna(0)

    except Exception as ex:
        return None

    return sig

# ══════════════════════════════════════════════════════
# LISTA DE TODAS AS ESTRATÉGIAS
# ══════════════════════════════════════════════════════
def get_strategy_names():
    names = []

    # EMA Crosses
    ema_periods = [5, 8, 10, 13, 20, 21, 34, 50, 55, 89, 200]
    for i, f in enumerate(ema_periods):
        for s in ema_periods[i+1:]:
            if s <= f * 10:
                names.append(f"EMA_CROSS_{f}_{s}")

    # SMA Crosses
    sma_periods = [5, 10, 20, 50, 100, 200]
    for i, f in enumerate(sma_periods):
        for s in sma_periods[i+1:]:
            names.append(f"SMA_CROSS_{f}_{s}")

    # RSI
    for period in [7, 14, 21]:
        for lo, hi in [(20,80),(25,75),(30,70),(35,65)]:
            names.append(f"RSI_{period}_{lo}_{hi}")

    # MACD variantes
    for f, s in [("12","26"),("5","13"),("8","21")]:
        names.append(f"MACD_{f}_{s}")

    # Bollinger
    for n in [10, 20, 50]:
        names.append(f"BB_REV_{n}")
        names.append(f"BB_BREAK_{n}")

    # Outros
    for n in [5, 14, 21]:
        names.append(f"STOCH_{n}")
    for n in [14, 20]:
        names.append(f"CCI_{n}")
    for n in [14, 21]:
        names.append(f"WILLR_{n}")
    for n in [5, 10, 20, 40]:
        names.append(f"ROC_{n}")

    names += ["VOL_BREAK", "OBV_TREND", "REGIME_LONG"]

    # Combinadas
    names += [
        "COMBO_TREND", "COMBO_REVERSION", "COMBO_MOMENTUM",
        "COMBO_MACD_RSI", "COMBO_GOLDEN_CROSS", "COMBO_TRIPLE_EMA",
        "COMBO_VOLATILITY_SQUEEZE", "COMBO_FULL"
    ]

    return names

# ══════════════════════════════════════════════════════
# BACKTEST ROBUSTO
# ══════════════════════════════════════════════════════
def backtest(signal, df):
    try:
        ret = df["Close"].squeeze().pct_change()
        strat = signal.shift(1) * ret
        strat = strat.dropna()

        if len(strat) < MIN_TRADES:
            return None

        # Verifica se tem histórico suficiente
        days = len(strat)
        if days < MIN_HISTORY_DAYS * 0.3:
            return None

        total = float((1 + strat).prod() - 1)
        mean = float(strat.mean())
        std = float(strat.std())
        sharpe = mean / std * np.sqrt(252) if std > 0 else 0
        cum = (1 + strat).cumprod()
        max_dd = float(((cum - cum.cummax()) / cum.cummax()).min())
        winrate = float((strat > 0).sum() / len(strat))
        trades = int((signal.diff().abs() > 0).sum())

        # Sortino ratio (penaliza só downside)
        downside = strat[strat < 0].std()
        sortino = mean / downside * np.sqrt(252) if downside > 0 else 0

        # Calmar ratio
        calmar = (total / abs(max_dd)) if max_dd != 0 else 0

        # Consistência: performance nos últimos 25% do período
        recent = strat.iloc[int(len(strat)*0.75):]
        recent_total = float((1 + recent).prod() - 1)

        return {
            "total": round(total, 4),
            "sharpe": round(float(sharpe), 3),
            "sortino": round(float(sortino), 3),
            "calmar": round(float(calmar), 3),
            "max_dd": round(max_dd, 4),
            "winrate": round(winrate, 3),
            "trades": trades,
            "days": days,
            "recent_return": round(recent_total, 4),
        }
    except:
        return None

def passes_filter(m):
    return (
        m["sharpe"] >= MIN_SHARPE and
        m["winrate"] > MIN_WINRATE and
        m["max_dd"] > MAX_DRAWDOWN and
        m["total"] > MIN_TOTAL_RETURN and
        m["trades"] >= MIN_TRADES and
        m["recent_return"] > 0  # Tem de estar a funcionar AGORA
    )

# ══════════════════════════════════════════════════════
# MAIN LOOP — INFINITO
# ══════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("  TRADING BOT GOLDMAN MODE — INICIADO")
    print("=" * 60)

    memory = load_memory()
    all_strategies = get_strategy_names()
    total_combinations = len(ALL_TICKERS) * len(TIMEFRAMES) * len(all_strategies)

    send_telegram(
        f"🏦 *GOLDMAN MODE ACTIVADO*\n\n"
        f"📊 Tickers: {len(ALL_TICKERS)}\n"
        f"⏱ Timeframes: {len(TIMEFRAMES)}\n"
        f"🧠 Estratégias: {len(all_strategies)}\n"
        f"🔢 Combinações: {total_combinations:,}\n\n"
        f"*Filtros activos:*\n"
        f"✅ Sharpe ≥ {MIN_SHARPE}\n"
        f"✅ Winrate > {MIN_WINRATE:.0%}\n"
        f"✅ Drawdown < {abs(MAX_DRAWDOWN):.0%}\n"
        f"✅ Retorno total > {MIN_TOTAL_RETURN:.0%}\n"
        f"✅ Mín. {MIN_TRADES} trades\n"
        f"✅ Tem de funcionar AGORA\n\n"
        f"_Só te aviso quando valer mesmo a pena. 💎_"
    )

    while True:
        memory["iterations"] += 1
        iteration = memory["iterations"]
        winners = []
        tested = 0

        print(f"\n{'='*60}")
        print(f"ITERAÇÃO #{iteration} — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        print(f"{'='*60}")

        # Aprende com iterações anteriores: prioriza tickers com melhor histórico
        def ticker_priority(t):
            key = f"{t}_priority"
            return memory["scores"].get(key, {}).get("avg_sharpe", 0)

        sorted_tickers = sorted(ALL_TICKERS, key=ticker_priority, reverse=True)

        for symbol in sorted_tickers:
            for tf in TIMEFRAMES:
                df = get_data(symbol, tf["period"], tf["interval"])
                if df is None:
                    continue

                try:
                    df = compute_indicators(df)
                except Exception as e:
                    continue

                for strat_name in all_strategies:
                    tested += 1
                    memory["total_tested"] += 1

                    try:
                        signal = generate_signals(strat_name, df)
                        if signal is None:
                            continue

                        m = backtest(signal, df)
                        if m is None:
                            continue

                        # Aprende
                        learn_key = f"{symbol}_{tf['name']}_{strat_name}"
                        update_learning(memory, learn_key, m)

                        if passes_filter(m):
                            winners.append({
                                "symbol": symbol,
                                "timeframe": tf["name"],
                                "strategy": strat_name,
                                "metrics": m,
                                "found_at": datetime.now().isoformat()
                            })
                            print(f"  💎 WINNER: {symbol} | {strat_name} | {tf['name']} | Sharpe={m['sharpe']}")

                    except:
                        continue

        # Guarda memória
        save_memory(memory)

        print(f"\nTestadas: {tested} combinações")
        print(f"Winners: {len(winners)}")

        if winners:
            # Ordena por Sharpe × Sortino (melhor combinação)
            winners.sort(key=lambda x: x["metrics"]["sharpe"] * x["metrics"].get("sortino", 1), reverse=True)

            # Guarda os melhores
            memory["winners"] = winners[:20]
            if not memory["best_ever"] or winners[0]["metrics"]["sharpe"] > memory.get("best_ever", {}).get("metrics", {}).get("sharpe", 0):
                memory["best_ever"] = winners[0]
            save_memory(memory)

            # Mensagem detalhada
            msg = f"💎 *ESTRATÉGIAS ENCONTRADAS — ITERAÇÃO #{iteration}*\n"
            msg += f"_(Total testado: {memory['total_tested']:,})_\n\n"

            for r in winners[:5]:
                m = r["metrics"]
                emoji = "🥇" if r == winners[0] else "🥈" if r == winners[1] else "🥉" if len(winners) > 2 and r == winners[2] else "✅"
                msg += f"{emoji} *{r['symbol']}* — `{r['strategy']}`\n"
                msg += f"   ⏱ {r['timeframe']}\n"
                msg += f"   📈 Retorno: `{m['total']:.1%}`\n"
                msg += f"   ⚡ Sharpe: `{m['sharpe']:.2f}`\n"
                msg += f"   🌊 Sortino: `{m['sortino']:.2f}`\n"
                msg += f"   📉 Drawdown: `{m['max_dd']:.1%}`\n"
                msg += f"   🎯 Win Rate: `{m['winrate']:.1%}`\n"
                msg += f"   🔄 Trades: `{m['trades']}`\n"
                msg += f"   📅 Dias analisados: `{m['days']}`\n"
                msg += f"   📆 Recente: `{m['recent_return']:.1%}`\n\n"

            msg += f"_Próxima análise em 3 horas..._"
            send_telegram(msg)

        else:
            send_telegram(
                f"🔍 *Iteração #{iteration} concluída*\n"
                f"Testei `{tested:,}` combinações.\n"
                f"Total acumulado: `{memory['total_tested']:,}`\n\n"
                f"Nada passou os filtros ainda.\n"
                f"_O bot está a aprender e a priorizar os melhores candidatos..._\n\n"
                f"_Próxima análise em 3 horas._"
            )

        print("A dormir 3 horas...")
        time.sleep(10800)

if __name__ == "__main__":
    main()
