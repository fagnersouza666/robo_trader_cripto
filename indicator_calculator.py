import pandas as pd
import pandas_ta as ta


class IndicatorCalculator:
    def __init__(self, rsi_length: int = 7, momentum_length: int = 10):
        self.rsi_length = rsi_length
        self.momentum_length = momentum_length

    def calcular_indicadores(
        self, df: pd.DataFrame, indicadores: dict = None
    ) -> pd.DataFrame:
        if indicadores is None:
            indicadores = {
                "RSI": True,
                "SMA50": True,
                "SMA200": True,
                "VWAP": True,
                "BollingerBands": True,
                "Momentum": True,
                "Volume": True,
                "EM1": True,
                "EMA2": True,
            }

        # Certifique-se de que o índice é um DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index("timestamp")

        if indicadores.get("RSI"):
            df["RSI"] = ta.rsi(df["close"], length=self.rsi_length)
        if indicadores.get("SMA50"):
            df["SMA50"] = ta.sma(df["close"], length=50)
        if indicadores.get("SMA200"):
            df["SMA200"] = ta.sma(df["close"], length=200)
        if indicadores.get("VWAP"):
            # Cálculo do VWAP utilizando o pandas_ta
            df["VWAP"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])

        if indicadores.get("BollingerBands"):
            # Cálculo das Bandas de Bollinger
            bbands = ta.bbands(df["close"], length=20, std=2)
            df["BB_upper"] = bbands["BBU_20_2.0"]
            df["BB_lower"] = bbands["BBL_20_2.0"]

        if indicadores.get("Momentum"):
            df["Momentum"] = ta.mom(df["close"], length=self.momentum_length)

        if indicadores.get("Volume"):
            df["Volume"] = df["volume"].rolling(window=10).mean()  # Média do volume

        # Cálculo das EMAs
        df["EMA1"] = ta.ema(df["close"], length=9)
        df["EMA2"] = ta.ema(df["close"], length=21)
        df["CLOSE_PRICE"] = df["close"][-1]

        return df
