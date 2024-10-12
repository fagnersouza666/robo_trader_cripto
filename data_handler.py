import logging
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

logger = logging.getLogger(__name__)


class DataHandler:
    def __init__(self, client: Client, interval: str):
        self.client = client
        self.interval = interval

    def obter_dados_mercado(self, symbol: str, limit: int = 1000) -> pd.DataFrame:
        try:
            return self._processar_dados(symbol, limit)
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"[{symbol}] Erro na API da Binance: {e}")
        except Exception as e:
            logger.error(f"[{symbol}] Erro inesperado: {e}")
        return pd.DataFrame()

    def _processar_dados(self, symbol: str, limit: int) -> pd.DataFrame:
        klines = self.client.get_klines(
            symbol=symbol, interval=self.interval, limit=limit
        )

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
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        # Ordenar por timestamp para garantir que os dados estejam em ordem cronológica
        df = df.sort_values(by="timestamp").reset_index(drop=True)

        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)

        return df.sort_values("timestamp").reset_index(drop=True)

    # Função para obter os dados de preços da Binance
    def get_price_data(
        self,
        symbol,
        interval="1m",
        limit=100,
    ):
        klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
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
