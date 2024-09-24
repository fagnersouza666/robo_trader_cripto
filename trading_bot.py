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
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import traceback
import re

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
        # self.client.API_URL = "https://api.binance.com/api/v3"
        # self.client.ping()
        self.client.time_sync = True
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
        Calcula o valor da stake com base no risco definido (1% do saldo), verificando o notional mínimo.
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
        try:
            info = self.client.get_symbol_info(symbol)
            if not info:
                raise ValueError(f"Informações do símbolo {symbol} não encontradas.")

            filters = {f["filterType"]: f for f in info["filters"]}

            # Filtro de tamanho de lote (quantidade mínima, máxima e incrementos)
            lot_size = filters["LOT_SIZE"]

            if not lot_size:
                raise ValueError(
                    f"Filtro LOT_SIZE não encontrado para o símbolo {symbol}."
                )

            min_qty = Decimal(lot_size["minQty"])
            max_qty = Decimal(lot_size["maxQty"])
            step_size = Decimal(lot_size["stepSize"])

            # Criar quantizador baseado no step_size
            step_size_exponent = step_size.as_tuple().exponent
            if step_size_exponent >= 0:
                number_of_decimals = 0
            else:
                number_of_decimals = abs(step_size_exponent)
            quantizer = Decimal("1e{}".format(step_size_exponent))

            # Filtro de valor notional mínimo (valor mínimo em USDT que você precisa gastar)
            notional_filter = filters.get("MIN_NOTIONAL") or filters["NOTIONAL"]

            if notional_filter:
                min_notional = Decimal(notional_filter["minNotional"])
            else:
                min_notional = Decimal(
                    "10"
                )  # Valor padrão ou ajuste conforme necessário

            # Converter preco_ativo para Decimal

            preco_ativo_decimal = Decimal(str(preco_ativo))

            # Calcule a quantidade mínima necessária para atender ao min_notional
            min_quantity = (min_notional / preco_ativo_decimal).quantize(
                quantizer, rounding=ROUND_UP
            )
            min_quantity = max(min_quantity, min_qty)

            # Converter quantidade para Decimal
            quantidade_decimal = Decimal(str(quantidade))

            # Ajuste a quantidade inicial para o step_size adequado
            quantidade_ajustada = (
                quantidade_decimal - (quantidade_decimal % step_size)
            ).quantize(quantizer, rounding=ROUND_DOWN)

            # Verifique se a quantidade ajustada atende ao min_quantity
            if quantidade_ajustada < min_quantity:
                quantidade_ajustada = min_quantity.quantize(
                    quantizer, rounding=ROUND_UP
                )

            # Certifique-se de que a quantidade ajustada não excede a quantidade máxima
            quantidade_ajustada = min(quantidade_ajustada, max_qty)

            # Formatar a quantidade ajustada como string com o número correto de decimais
            quantidade_ajustada_str = f"{quantidade_ajustada:.{number_of_decimals}f}"

            # Validar o formato da quantidade ajustada
            quantity_pattern = r"^([0-9]{1,20})(\.[0-9]{1,20})?$"
            if not re.match(quantity_pattern, quantidade_ajustada_str):
                raise ValueError(
                    f"Quantidade ajustada '{quantidade_ajustada_str}' não está no formato correto."
                )

            # Logging para depuração
            logging.debug(f"Symbol: {symbol}")
            logging.debug(f"Quantidade Inicial: {quantidade}")
            logging.debug(f"Preço Ativo: {preco_ativo}")
            logging.debug(f"Min Qty: {min_qty}")
            logging.debug(f"Max Qty: {max_qty}")
            logging.debug(f"Step Size: {step_size}")
            logging.debug(f"Min Notional: {min_notional}")
            logging.debug(f"Min Quantity: {min_quantity}")
            logging.debug(f"Quantidade Ajustada: {quantidade_ajustada_str}")

            return quantidade_ajustada_str

        except Exception as e:
            logging.error(f"Erro ao ajustar quantidade para {symbol}: {e}")
            raise

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
                if stake is None:
                    logger.error(f"Stake não foi calculado para {key}.")
                    continue  # Pula para o próximo símbolo se stake for None

                if acao == "Comprar":
                    preco_compra = self.trade_executor.executar_ordem(
                        key, stake, "buy", 1.0, 2.0
                    )

                    if preco_compra is None:
                        logger.error(f"Compra falhou para {key}.")
                        continue

                    valor_total = float(stake) * preco_compra
                    self.registrar_e_notificar_operacao(
                        key, "COMPRA", float(stake), preco_compra, valor_total
                    )
                elif acao == "Vender":
                    preco_venda = self.trade_executor.executar_ordem(
                        key, stake, "sell", 1.0, 2.0
                    )

                    if preco_venda is None:
                        logger.error(f"Venda falhou para {key}.")
                        continue

                    valor_total = float(stake) * preco_venda
                    self.registrar_e_notificar_operacao(
                        key, "VENDA", float(stake), preco_venda, valor_total
                    )
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Erro inesperado no símbolo {key}: {e}")

    def estrategia_trading(self, df, sentimento):
        rsi = df["RSI"].iloc[-1]
        rsi_anterior = df["RSI"].iloc[-2]
        sma50 = df["SMA50"].iloc[-1]
        sma200 = df["SMA200"].iloc[-1]
        vwap = df["VWAP"].iloc[-1]
        ultimo_preco = df["close"].iloc[-1]
        preco_anterior = df["close"].iloc[-2]
        bb_upper = df["BB_upper"].iloc[-1]
        bb_lower = df["BB_lower"].iloc[-1]
        momentum = df["Momentum"].iloc[-1]

        # Identificando níveis de suporte e resistência
        resistencia = bb_upper if ultimo_preco < bb_upper else vwap
        suporte = bb_lower if ultimo_preco > bb_lower else vwap

        if rsi < 35 and sma50 > sma200 and "positivo" in sentimento.lower():
            return "Comprar"
        elif rsi > 70 and sma50 < sma200 and "negativo" in sentimento.lower():
            return "Vender"

        # Ajuste da lógica para incluir o VWAP na estratégia de day trade
        elif rsi < 35 and ultimo_preco > vwap and "positivo" in sentimento.lower():
            return "Comprar"
        elif rsi > 70 and ultimo_preco < vwap and "negativo" in sentimento.lower():
            return "Vender"

        # Estratégia combinando VWAP e Bandas de Bollinger
        elif (
            ultimo_preco > vwap
            and ultimo_preco < bb_upper
            and "positivo" in sentimento.lower()
        ):
            return "Comprar"
        elif (
            ultimo_preco < vwap
            and ultimo_preco > bb_lower
            and "negativo" in sentimento.lower()
        ):
            return "Vender"

        # Critério principal: VWAP e Momentum
        elif ultimo_preco > vwap and momentum > 0 and "positivo" in sentimento.lower():
            return "Comprar"
        elif ultimo_preco < vwap and momentum < 0 and "negativo" in sentimento.lower():
            return "Vender"

        # Estratégia de breakout baseada no rompimento dos níveis de suporte e resistência
        elif ultimo_preco > resistencia and "positivo" in sentimento.lower():
            return "Comprar"
        elif ultimo_preco < suporte and "negativo" in sentimento.lower():
            return "Vender"

        # Divergência de alta (preço menor, RSI maior)
        elif ultimo_preco < preco_anterior and rsi > rsi_anterior:
            return "Comprar"

        # Divergência de baixa (preço maior, RSI menor)
        elif ultimo_preco > preco_anterior and rsi < rsi_anterior:
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
