import pandas as pd
import pandas_ta as ta


class IndicatorCalculator:
    def __init__(self, rsi_length: int = 14):
        self.rsi_length = rsi_length

    def calcular_indicadores(
        self, df: pd.DataFrame, indicadores: dict = None
    ) -> pd.DataFrame:
        if indicadores is None:
            indicadores = {"RSI": True, "SMA50": True, "SMA200": True, "MACD": True}

        if indicadores.get("RSI"):
            df["RSI"] = ta.rsi(df["close"], length=self.rsi_length)
        if indicadores.get("SMA50"):
            df["SMA50"] = ta.sma(df["close"], length=50)
        if indicadores.get("SMA200"):
            df["SMA200"] = ta.sma(df["close"], length=200)
        if indicadores.get("MACD"):
            macd = ta.macd(df["close"])
            df["MACD"] = macd["MACD_12_26_9"]
            df["MACD_signal"] = macd["MACDs_12_26_9"]

        return df
