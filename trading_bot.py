import logging
from binance.client import Client
from data_handler import DataHandler
from indicator_calculator import IndicatorCalculator
from sentiment_analyzer import SentimentAnalyzer
from trade_executor import TradeExecutor
from database_manager import DatabaseManager
from telegram_notifier import TelegramNotifier
import datetime
import os
import math
from decimal import Decimal
import traceback

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(
        self,
        binance_api_key,
        binance_secret_key,
        openai_api_key,
        cryptocompare_api_key,
        symbols,
        interval=Client.KLINE_INTERVAL_15MINUTE,
    ):
        self.client = Client(api_key=binance_api_key, api_secret=binance_secret_key)
        self.data_handler = DataHandler(self.client, interval)
        self.indicator_calculator = IndicatorCalculator()
        self.sentiment_analyzer = SentimentAnalyzer(
            openai_api_key, cryptocompare_api_key
        )
        self.trade_executor = TradeExecutor(self.client)
        self.database_manager = DatabaseManager()
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.notificador_telegram = TelegramNotifier(telegram_token, telegram_chat_id)
        self.symbols = symbols

    def calcular_stake(self, symbol: str, risco_percentual: float = 1.0) -> float:
        """
        Calcula o valor da stake com base no risco definido (1% do saldo).

        :param symbol: Par de negociação (ex: 'BTCUSDT').
        :param risco_percentual: Percentual de risco em relação ao saldo disponível.
        :return: Quantidade de criptomoeda a ser comprada ou vendida.
        """
        # Obter o saldo da moeda de base (exemplo, saldo em USDT)
        saldo_base = self.client.get_asset_balance(asset="USDT")
        saldo_disponivel = float(saldo_base["free"])

        # Calcular a stake como 1% do saldo
        stake_valor = (risco_percentual / 100) * saldo_disponivel

        # Obter o preço atual do ativo
        ticker = self.client.get_symbol_ticker(symbol=symbol)

        preco_ativo = float(ticker["price"])

        # Quantidade de criptomoeda a comprar/vender com base na stake
        stake_quantidade = stake_valor / preco_ativo

        return self.ajustar_quantidade(symbol, stake_quantidade, preco_ativo)

    def ajustar_quantidade(
        self, symbol: str, quantidade: float, preco_ativo: float
    ) -> float:
        """
        Ajusta a quantidade para atender ao passo mínimo de quantidade da Binance.

        :param symbol: Símbolo de negociação.
        :param quantidade: Quantidade inicial.
        :return: Quantidade ajustada.
        """
        info = self.client.get_symbol_info(symbol)

        filters = {f["filterType"]: f for f in info["filters"]}

        # Filtro de tamanho de lote (quantidade mínima, máxima e incrementos)
        lot_size = filters["LOT_SIZE"]
        min_qty = float(lot_size["minQty"])
        max_qty = float(lot_size["maxQty"])
        step_size = float(lot_size["stepSize"])

        # Filtro de valor notional mínimo (valor mínimo em USDT que você precisa gastar)
        notional = filters["NOTIONAL"]
        min_notional = float(notional["minNotional"])

        # Calcule a quantidade mínima necessária para atender ao min_notional
        min_quantity = max(min_qty, min_notional / preco_ativo)

        # Ajuste a quantidade mínima ao step_size apropriado
        step_size_decimal = "{0:.8f}".format(step_size).rstrip("0")
        precision = (
            len(step_size_decimal.split(".")[1]) if "." in step_size_decimal else 0
        )

        min_quantity = round(min_quantity, precision)

        quantidade_ajustada = quantidade - (quantidade % step_size)

        if quantidade_ajustada < min_quantity:
            quantidade_ajustada = Decimal(min_quantity)

        retorno = Decimal("{:.8f}".format(quantidade_ajustada))

        return retorno

    def executar_trading(self):

        for key, value in self.symbols.items():
            try:
                # Obter dados de mercado
                df = self.data_handler.obter_dados_mercado(key)
                if df.empty:
                    continue

                # Calcular indicadores
                df = self.indicator_calculator.calcular_indicadores(df)

                # Analisar sentimento
                sentimento = self.sentiment_analyzer.analisar_sentimento(value)

                # Determinar ação de trading (comprar, vender, ou esperar)
                acao = self.estrategia_trading(df, sentimento)

                # Executar ação e registrar a operação no banco de dados
                stake = self.calcular_stake(key)

                if acao == "Comprar":
                    preco_compra = self.trade_executor.executar_ordem(
                        key, stake, "buy", 1.0, 2.0
                    )

                    valor_total = float(stake) * preco_compra
                    self.registrar_e_notificar_operacao(
                        key, "COMPRA", float(stake), preco_compra, valor_total
                    )
                elif acao == "Vender":
                    preco_venda = self.trade_executor.executar_ordem(
                        key, stake, "sell", 1.0, 2.0
                    )
                    valor_total = float(stake) * preco_venda
                    self.registrar_e_notificar_operacao(
                        key, "VENDA", float(stake), preco_venda, valor_total
                    )
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Erro inesperado no símbolo {key}: {e}")

    def estrategia_trading(self, df, sentimento):
        rsi = df["RSI"].iloc[-1]
        sma50 = df["SMA50"].iloc[-1]
        sma200 = df["SMA200"].iloc[-1]
        vwap = df["VWAP"].iloc[-1]
        ultimo_preco = df["close"].iloc[-1]
        bb_upper = df["BB_upper"].iloc[-1]
        bb_lower = df["BB_lower"].iloc[-1]

        if rsi < 35 and sma50 > sma200 and sentimento == "positivo":
            return "Comprar"
        elif rsi > 70 and sma50 < sma200 and sentimento == "negativo":
            return "Vender"

        # Ajuste da lógica para incluir o VWAP na estratégia de day trade
        elif rsi < 35 and ultimo_preco > vwap and sentimento == "positivo":
            return "Comprar"
        elif rsi > 70 and ultimo_preco < vwap and sentimento == "negativo":
            return "Vender"

        # Estratégia combinando VWAP e Bandas de Bollinger
        elif (
            ultimo_preco > vwap and ultimo_preco < bb_upper and sentimento == "positivo"
        ):
            return "Comprar"
        elif (
            ultimo_preco < vwap and ultimo_preco > bb_lower and sentimento == "negativo"
        ):
            return "Vender"

        return "Esperar"

    def registrar_e_notificar_operacao(
        self, symbol, tipo_operacao, quantidade, preco, valor_total
    ):

        quantidade = f"{quantidade:.8f}"

        # Registrar a operação no banco de dados
        data_hora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.database_manager.registrar_transacao(
            data_hora=data_hora,
            simbolo=symbol,
            tipo=tipo_operacao,
            quantidade=quantidade,
            preco=preco,
            valor_total=valor_total,
        )

        # Enviar notificação para o Telegram
        self.notificador_telegram.notificar(
            tipo=tipo_operacao,
            symbol=symbol,
            quantidade=quantidade,
            preco=preco,
            valor_total=valor_total,
        )

        # Logar a operação
        logger.info(
            f"{tipo_operacao} de {quantidade} {symbol} a {preco} USDT (Total: {valor_total} USDT)"
        )
