import logging
from binance.client import Client
from data_handler import DataHandler
from indicator_calculator import IndicatorCalculator
from sentiment_analyzer import SentimentAnalyzer
from trade_executor import TradeExecutor
from database_manager import DatabaseManager
from telegram_notifier import TelegramNotifier
from datetime import datetime
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
        casas_decimais,
        min_notional,
        interval=Client.KLINE_INTERVAL_15MINUTE,
    ):
        self.client = Client(api_key=binance_api_key, api_secret=binance_secret_key)
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
        self.casas_decimais = casas_decimais
        self.min_notional = min_notional

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

    def calcular_preco_medio_e_quantidade_banco(self, symbol):
        """
        Calcula o preço médio de compra e a quantidade total acumulada para uma moeda.
        """
        transacoes = self.database_manager.obter_transacoes(symbol, tipo="COMPRA")
        valor_total_compras = 0
        quantidade_total = 0
        taxas_total = 0

        for transacao in transacoes:
            quantidade_total += transacao["quantidade"]
            valor_total_compras += transacao["quantidade"] * transacao["preco"]
            taxas_total += transacao["taxa"]

        if quantidade_total == 0:
            return 0, 0, 0  # Sem compras registradas

        preco_medio = valor_total_compras / quantidade_total
        return preco_medio, quantidade_total, taxas_total

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

            return quantidade_ajustada_str

        except Exception as e:
            logging.error(f"Erro ao ajustar quantidade para {symbol}: {e}")
            raise

    def executar_estrategia(self):

        for key, value in self.symbols.items():
            try:
                # Obter dados de mercado
                df = self.data_handler.obter_dados_mercado(key)
                if df.empty:
                    continue

                # Calcular indicadores
                df = self.indicator_calculator.calcular_indicadores(df)

                acao, preco_venda = self.estrategia_venda_reversao(df, key)

                # Analisar sentimento
                sentimento = self.sentiment_analyzer.analisar_sentimento(value)

                if acao == "Esperar":
                    # Determinar ação de trading (comprar, vender, ou esperar)
                    acao = self.estrategia_trading(df, sentimento)

                # Executar ação e registrar a operação no banco de dados
                stake = self.calcular_stake(key)
                if stake is None:
                    logger.error(f"Stake não foi calculado para {key}.")
                    continue  # Pula para o próximo símbolo se stake for None

                if acao == "Comprar":
                    preco_compra = self.comprar(key, stake)

                elif acao == "Vender" or acao == "VenderParcial":
                    self.vender(key, value, acao, stake)

            except Exception as e:
                traceback.print_exc()
                logger.error(f"Erro inesperado no símbolo  {key}: {e}")

        self.database_manager.fechar_conexao()

    def vender(self, key, value, acao, stake):
        logging.info(f"{acao}")

        # Obter preço médio e quantidade total de compras
        preco_medio_compra, quantidade_total, taxas_total_compras = (
            self.calcular_preco_medio_e_quantidade_banco(key)
        )

        logging.info(
            f"Preço médio de compra: {preco_medio_compra}, Quantidade total: {quantidade_total}, Taxas totais: {taxas_total_compras}, moeda: {key}"
        )

        if quantidade_total == 0:
            logger.warning(f"Quantidade total para venda de {key} é zero.")
            return

        logger.info(f"Executando {acao} para {key}")

        if quantidade_total != 0:

            # Ajusta a quantidade para garantir que o valor notional seja suficiente
            quantidade_total = self._ajustar_quantidade_para_notional(
                key, quantidade_total
            )

            if quantidade_total <= 0:
                logger.error(
                    f"Quantidade ajustada para {key} é zero ou negativa. Operação de venda cancelada."
                )
                return

            # Executar a venda de toda a quantidade acumulada
            resultado = self.trade_executor.executar_ordem(
                key,
                quantidade_total,
                "sell",
                "VenderParcial" == acao,
                value,
            )

            if resultado is None:
                logger.error(f"Falha ao executar a ordem de venda para {key}.")
            else:
                preco_venda_real, taxa = resultado

                valor_total = float(stake) * preco_venda_real
                self.registrar_e_notificar_operacao(
                    key,
                    "VENDA",
                    float(stake),
                    preco_venda_real,
                    valor_total,
                    taxa,
                    1,
                )
                self.database_manager.atualizar_compras(key)

                valor_total_vendas = quantidade_total * preco_venda_real
                valor_total_compras = quantidade_total * preco_medio_compra
                ganho_total = (
                    valor_total_vendas - valor_total_compras - taxas_total_compras
                )

                # Calcular porcentagem de ganho
                porcentagem_ganho = (ganho_total / valor_total_compras) * 100

                # Registrar no banco de dados
                data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.database_manager.registrar_ganhos(
                    data_hora,
                    key,
                    valor_total_compras,
                    valor_total_vendas,
                    taxas_total_compras,
                    ganho_total,
                    porcentagem_ganho,
                    taxa,
                )

                # Atualizar o resumo financeiro geral
                valor_inicial = self.database_manager.obter_valor_inicial()
                valor_atual = (
                    self.database_manager.obter_valor_total_atual()
                )  # soma de todas as moedas
                porcentagem_geral = (
                    (valor_atual - valor_inicial) / valor_inicial
                ) * 100
                self.database_manager.atualizar_resumo_financeiro(
                    valor_inicial, valor_atual, porcentagem_geral
                )

                logger.info(
                    f"Venda registrada para {key}: Ganho de {ganho_total} USDT, porcentagem de {porcentagem_ganho:.2f}%"
                )

    def _ajustar_quantidade_para_notional(
        self, symbol: str, quantidade: float, min_notional_padrao: float = 10.0
    ):
        """
        Ajusta a quantidade para garantir que o valor notional atenda ao mínimo permitido pela lista manual.
        Se a quantidade fornecida for menor que o notional mínimo, ajusta a quantidade com base no valor do dicionário MIN_NOTIONAL.
        """
        try:
            logger.info(f"Ajustando quantidade para notional para {symbol}...")

            # Obter o preço atual do ativo
            preco_atual = float(self.client.get_symbol_ticker(symbol=symbol)["price"])

            # Obter o valor mínimo de notional da lista manual ou usar o valor padrão
            min_notional = self.min_notional.get(symbol, min_notional_padrao)
            logging.info(f"Valor notional mínimo para {symbol}: {min_notional}")

            # Calcula o valor notional atual com a quantidade fornecida
            notional = preco_atual * quantidade
            logging.info(f"2 - Valor notional atual para {symbol}: {notional}")

            # Se o notional for menor que o permitido, ajustar a quantidade
            if notional < min_notional:
                logger.warning(
                    f"Valor notional ({notional}) é menor que o mínimo permitido ({min_notional}) para {symbol}. "
                    f"Ajustando a quantidade..."
                )

                # Ajustar a quantidade mínima necessária para atender ao notional mínimo
                quantidade_ajustada = min_notional / preco_atual

                logging.info(
                    f"Quantidade ajustada para {symbol}: {quantidade_ajustada}"
                )

                return quantidade_ajustada

            # Se o notional inicial já for suficiente, retorna a quantidade original
            return quantidade

        except Exception as e:
            logger.error(f"Erro ao ajustar quantidade para notional em {symbol}: {e}")
            return 0

    def comprar(self, key, stake):
        logging.info("Comprar")
        resultado = self.trade_executor.executar_ordem(key, stake, "buy", False)

        if resultado is None:
            logger.error(f"Falha ao executar a ordem para {key}.")
            return None
        else:
            preco_compra, taxa = resultado
            logger.info(f"Preço de compra: {preco_compra}, Taxa: {taxa}")

            valor_total = float(stake) * preco_compra
            self.registrar_e_notificar_operacao(
                key,
                "COMPRA",
                float(stake),
                preco_compra,
                valor_total,
                taxa,
                0,
            )

        return preco_compra

    def estrategia_venda_reversao(self, df, symbol):
        """
        Estratégia para detectar reversão de mercado e vender.
        Utiliza RSI, Momentum, Bandas de Bollinger e Volume.
        Faz a venda de todo o valor acumulado da moeda.
        """
        try:
            rsi = df["RSI"].iloc[-1]
            rsi_anterior = df["RSI"].iloc[-2]
            momentum = df["Momentum"].iloc[-1]
            ultimo_preco = df["close"].iloc[-1]
            preco_anterior = df["close"].iloc[-2]
            bb_upper = df["BB_upper"].iloc[-1]
            volume_atual = df["Volume"].iloc[-1]
            volume_medio = df["Volume"].mean()

            # Venda parcial se RSI estiver sobrecomprado e volume acima da média
            if rsi > 70 and volume_atual > volume_medio * 1.2:
                return "VenderParcial", ultimo_preco

            # Venda total se RSI mostrar divergência negativa e momentum cair
            if rsi < df["RSI"].iloc[-2] and momentum < 0:
                return "VenderTotal", ultimo_preco

            # Venda se o preço tocar a banda superior de Bollinger
            if ultimo_preco > bb_upper:
                return "VenderTotal", ultimo_preco

            return "Esperar", 0.0

        except Exception as e:
            return "Esperar", 0.0

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
        volume_atual = df["Volume"].iloc[-1]
        volume_medio = df["Volume"].mean()

        # Identificando níveis de suporte e resistência
        resistencia = bb_upper if ultimo_preco < bb_upper else vwap
        suporte = bb_lower if ultimo_preco > bb_lower else vwap

        volume_medio = df["Volume"].mean()

        # Estratégia com base no VWAP e Volume
        if ultimo_preco > vwap and volume_atual > volume_medio * 1.5:
            return "Comprar"
        elif ultimo_preco < vwap and volume_atual > volume_medio * 1.5:
            return "Vender"
        else:
            if sentimento == "Neutro":
                if rsi < 35 and sma50 > sma200:
                    return "Comprar"
                elif rsi > 70 and sma50 < sma200:
                    return "Vender"

                # Ajuste da lógica para incluir o VWAP na estratégia de day trade
                elif rsi < 35 and ultimo_preco > vwap:
                    return "Comprar"
                elif rsi > 70 and ultimo_preco < vwap:
                    return "Vender"

                # Estratégia combinando VWAP e Bandas de Bollinger
                elif ultimo_preco > vwap and ultimo_preco < bb_upper:
                    return "Comprar"
                elif ultimo_preco < vwap and ultimo_preco > bb_lower:
                    return "Vender"

                # Critério principal: VWAP e Momentum
                elif ultimo_preco > vwap and momentum > 0:
                    return "Comprar"
                elif ultimo_preco < vwap and momentum < 0:
                    return "Vender"

                # Estratégia de breakout baseada no rompimento dos níveis de suporte e resistência
                elif ultimo_preco > resistencia:
                    return "Comprar"
                elif ultimo_preco < suporte:
                    return "Vender"

                # Divergência de alta (preço menor, RSI maior)
                elif ultimo_preco < preco_anterior and rsi > rsi_anterior:
                    return "Comprar"

                # Divergência de baixa (preço maior, RSI menor)
                elif ultimo_preco > preco_anterior and rsi < rsi_anterior:
                    return "Vender"
            else:
                if rsi < 35 and sma50 > sma200 and "positivo" in sentimento.lower():
                    return "Comprar"
                elif rsi > 70 and sma50 < sma200 and "negativo" in sentimento.lower():
                    return "Vender"

                # Ajuste da lógica para incluir o VWAP na estratégia de day trade
                elif (
                    rsi < 35
                    and ultimo_preco > vwap
                    and "positivo" in sentimento.lower()
                ):
                    return "Comprar"
                elif (
                    rsi > 70
                    and ultimo_preco < vwap
                    and "negativo" in sentimento.lower()
                ):
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
                elif (
                    ultimo_preco > vwap
                    and momentum > 0
                    and "positivo" in sentimento.lower()
                ):
                    return "Comprar"
                elif (
                    ultimo_preco < vwap
                    and momentum < 0
                    and "negativo" in sentimento.lower()
                ):
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
        self, symbol, tipo_operacao, quantidade, preco, valor_total, taxa, vendido
    ):

        quantidade = f"{quantidade:.8f}"

        # Registrar a operação no banco de dados
        data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.database_manager.registrar_transacao(
            data_hora=data_hora,
            simbolo=symbol,
            tipo=tipo_operacao,
            quantidade=quantidade,
            preco=preco,
            valor_total=valor_total,
            taxa=taxa,
            vendido=vendido,
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
