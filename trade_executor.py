import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from decimal import Decimal

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(self, client: Client):
        self.client = client

    def executar_ordem(
        self,
        symbol: str,
        quantidade: float,
        ordem_tipo: str,
        stop_loss_percent: float,
        take_profit_percent: float,
    ):

        if ordem_tipo == "buy":
            return self._executar_ordem_buy(
                symbol, quantidade, stop_loss_percent, take_profit_percent
            )
        elif ordem_tipo == "sell":
            return self._executar_ordem_sell(
                symbol, quantidade, stop_loss_percent, take_profit_percent
            )
        else:
            logger.error(f"Tipo de ordem inválido: {ordem_tipo}")

    def _executar_ordem_buy(
        self,
        symbol: str,
        quantidade: float,
        stop_loss_percent: float,
        take_profit_percent: float,
    ):
        try:
            print(symbol, quantidade)
            ordem_compra = self.client.order_market_buy(
                symbol=symbol, quantity=quantidade
            )

            logger.info(f"Ordem de compra executada para {symbol}: {ordem_compra}")
            self._configurar_ordem_limite(
                ordem_compra, stop_loss_percent, take_profit_percent
            )

            return float(ordem_compra["fills"][0]["price"])

        except BinanceAPIException as e:
            logger.error(f"Erro ao executar ordem de compra: {e}")

    def _executar_ordem_sell(
        self,
        symbol: str,
        quantidade: float,
        stop_loss_percent: float,
        take_profit_percent: float,
    ):
        try:
            ordem_venda = self.client.order_market_sell(
                symbol=symbol, quantity=quantidade
            )
            logger.info(f"Ordem de venda executada para {symbol}: {ordem_venda}")
            self._configurar_ordem_limite(
                ordem_venda, stop_loss_percent, take_profit_percent
            )

            return float(ordem_venda["fills"][0]["price"])

        except BinanceAPIException as e:
            logger.error(f"Erro ao executar ordem de venda: {e}")

    def _configurar_ordem_limite(
        self, ordem, stop_loss_percent: float, take_profit_percent: float
    ):
        preco = float(ordem["fills"][0]["price"])
        stop_loss_price = preco * (1 - stop_loss_percent / 100)
        take_profit_price = preco * (1 + take_profit_percent / 100)
        logger.info(
            f"Stop loss configurado para: {stop_loss_price} | Take profit: {take_profit_price}"
        )
