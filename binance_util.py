import pandas as pd
import pandas_ta as ta
from binance.client import Client
import numpy as np
import time
from datetime import datetime, timedelta


# Função para obter os dados de preços da Binance
def get_price_data(
    symbol,
    interval="1m",
    limit=100,
):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(
        klines,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "ignore",
        ],
    )
    df["close"] = df["close"].astype(float)
    return df
