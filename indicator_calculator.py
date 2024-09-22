import pandas as pd
import pandas_ta as ta


class IndicatorCalculator:
    def __init__(self, rsi_length: int = 14):
        self.rsi_length = rsi_length

    def calcular_indicadores(
        self, df: pd.DataFrame, indicadores: dict = None
    ) -> pd.DataFrame:
        if indicadores is None:
            indicadores = {"RSI": True, "SMA50": True, "SMA200": True, "VWAP": True}

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

        return df
