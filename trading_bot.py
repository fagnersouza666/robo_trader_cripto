import logging
import os
import re
import time
import traceback
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, Optional, Tuple

from binance.client import Client
from binance.exceptions import BinanceAPIException

from data_handler import DataHandler
from database_manager import DatabaseManager
from indicator_calculator import IndicatorCalculator
from sentiment_analyzer import SentimentAnalyzer
from telegram_notifier import TelegramNotifier
from trade_executor import TradeExecutor

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(
        self,
        binance_api_key: str,
        binance_secret_key: str,
        openai_api_key: str,
        cryptocompare_api_key: str,
        symbols: Dict[str, str],
        casas_decimais: Dict[str, int],
        min_notional: Dict[str, float],
        interval: str = Client.KLINE_INTERVAL_15MINUTE,
    ) -> None:
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
        self.telegram_notifier = TelegramNotifier(telegram_token, telegram_chat_id)
        self.symbols = symbols
        self.casas_decimais = casas_decimais
        self.min_notional = min_notional

    def calcular_stake(self, symbol: str, risco_percentual: float = 1.0) -> str:
        """
        Calcula o valor da stake com base no risco definido (porcentagem do saldo), verificando o notional mínimo.
        """
        saldo_base = self.client.get_asset_balance(asset="USDT")
        saldo_disponivel = float(saldo_base["free"])

        # Calcular a stake como porcentagem do saldo
        stake_valor = (risco_percentual / 100) * saldo_disponivel

        # Obter o preço atual do ativo
        ticker = self.client.get_symbol_ticker(symbol=symbol)
        preco_ativo = float(ticker["price"])

        # Quantidade de criptomoeda a comprar com base na stake
        stake_quantidade = stake_valor / preco_ativo

        return self.ajustar_quantidade(symbol, stake_quantidade, preco_ativo)

    def calcular_preco_medio_e_quantidade_banco(
        self, symbol: str
    ) -> Tuple[float, float, float]:
        """
        Calcula o preço médio de compra e a quantidade total acumulada para uma moeda.
        """
        transacoes = self.database_manager.obter_transacoes(symbol, tipo="COMPRA")
        valor_total_compras = 0.0
        quantidade_total = 0.0
        taxas_total = 0.0

        for transacao in transacoes:
            quantidade = transacao["quantidade"]
            preco = transacao["preco"]
            taxa = transacao["taxa"]
            quantidade_total += quantidade
            valor_total_compras += quantidade * preco
            taxas_total += taxa

        if quantidade_total == 0.0:
            return 0.0, 0.0, 0.0  # Sem compras registradas

        preco_medio = valor_total_compras / quantidade_total
        return preco_medio, quantidade_total, taxas_total

    def ajustar_quantidade(
        self, symbol: str, quantidade: float, preco_ativo: float
    ) -> str:
        """
        Ajusta a quantidade para atender ao passo mínimo de quantidade da Binance.
        """
        try:
            info = self.client.get_symbol_info(symbol)
            if not info:
                raise ValueError(f"Informações do símbolo {symbol} não encontradas.")

            filters = {f["filterType"]: f for f in info["filters"]}

            # Filtro de tamanho de lote (quantidade mínima, máxima e incrementos)
            lot_size = filters.get("LOT_SIZE")
            if not lot_size:
                raise ValueError(f"Filtro LOT_SIZE não encontrado para {symbol}.")

            min_qty = Decimal(lot_size["minQty"])
            max_qty = Decimal(lot_size["maxQty"])
            step_size = Decimal(lot_size["stepSize"])

            # Criar quantizador baseado no step_size
            step_size_exponent = step_size.as_tuple().exponent
            number_of_decimals = (
                abs(step_size_exponent) if step_size_exponent < 0 else 0
            )
            quantizer = Decimal(f"1e{step_size_exponent}")

            # Filtro de valor notional mínimo
            notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")
            min_notional = (
                Decimal(notional_filter["minNotional"])
                if notional_filter
                else Decimal("10")
            )

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

            # Verificar se a quantidade ajustada atende ao min_quantity
            if quantidade_ajustada < min_quantity:
                quantidade_ajustada = min_quantity.quantize(
                    quantizer, rounding=ROUND_UP
                )

            # Certificar-se de que a quantidade ajustada não excede a quantidade máxima
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
            logger.error(f"Erro ao ajustar quantidade para {symbol}: {e}")
            raise

    def executar_estrategia(self) -> None:
        for key, value in self.symbols.items():
            try:
                # Obter dados de mercado
                df = self.data_handler.obter_dados_mercado(key)
                if df.empty:
                    continue

                # Calcular indicadores
                df = self.indicator_calculator.calcular_indicadores(df)

                acao, _ = self.estrategia_venda_reversao(df, key)

                # Analisar sentimento
                sentimento = self.sentiment_analyzer.analisar_sentimento(value)

                if acao == "Esperar":
                    # Determinar ação de trading (comprar, vender, ou esperar)
                    acao = self.estrategia_trading(df, sentimento)

                # Executar ação e registrar a operação no banco de dados
                stake = self.calcular_stake(key)
                if not stake:
                    logger.error(f"Stake não foi calculado para {key}.")
                    continue  # Pula para o próximo símbolo se stake for None

                if acao == "Comprar":
                    self.comprar(key, stake)

                elif acao in ("Vender", "VenderParcial"):
                    self.vender(key, value, acao, stake)

            except Exception as e:
                logger.error(f"Erro inesperado no símbolo {key}: {e}")
                logger.debug(traceback.format_exc())

        self.database_manager.fechar_conexao()

    def vender(self, symbol: str, reason: str, action: str, stake: str) -> None:
        """
        Executa a venda de um ativo, atualiza o banco de dados e notifica via Telegram.

        :param symbol: Símbolo do ativo a ser vendido.
        :param reason: Razão ou descrição da venda.
        :param action: Tipo de ação ("Vender" ou "VenderParcial").
        :param stake: Quantidade a ser vendida.
        """
        logger.info(f"Ação: {action} para {symbol}")

        try:
            # Obter preço médio e quantidade total de compras
            preco_medio_compra, quantidade_total, taxas_total_compras = (
                self.calcular_preco_medio_e_quantidade_banco(symbol)
            )

            logger.info(
                f"Preço médio de compra: {preco_medio_compra}, Quantidade total: {quantidade_total}, "
                f"Taxas totais: {taxas_total_compras}, símbolo: {symbol}"
            )

            if quantidade_total == 0:
                logger.warning(f"Quantidade total para venda de {symbol} é zero.")
                return

            # Ajusta a quantidade para garantir que o valor notional seja suficiente
            quantidade_total_ajustada = self._ajustar_quantidade_para_notional(
                symbol, quantidade_total
            )

            if quantidade_total_ajustada <= 0:
                logger.error(
                    f"Quantidade ajustada para {symbol} é zero ou negativa. Operação de venda cancelada."
                )
                return

            # Executar a venda de toda a quantidade acumulada
            resultado = self.trade_executor.executar_ordem(
                symbol=symbol,
                quantidade=str(quantidade_total_ajustada),
                ordem_tipo="sell",
                venda_parcial=(action == "VenderParcial"),
            )

            if not resultado:
                logger.error(f"Falha ao executar a ordem de venda para {symbol}.")
                return

            preco_venda_real, taxa = resultado

            valor_total = quantidade_total_ajustada * preco_venda_real
            self.registrar_e_notificar_operacao(
                symbol=symbol,
                tipo_operacao="VENDA",
                quantidade=quantidade_total_ajustada,
                preco=preco_venda_real,
                valor_total=valor_total,
                taxa=taxa,
                vendido=1,
            )

            # Atualizar transações de compra como vendidas
            self.database_manager.atualizar_compras(symbol)

            # Calcular ganhos
            ganho_total, porcentagem_ganho = self._calcular_ganhos(
                quantidade_total_ajustada,
                preco_medio_compra,
                preco_venda_real,
                taxas_total_compras,
                taxa,
            )

            # Registrar ganhos no banco de dados
            data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.database_manager.registrar_ganhos(
                data_hora,
                symbol,
                preco_medio_compra * quantidade_total_ajustada,
                valor_total,
                taxas_total_compras + taxa,
                ganho_total,
                porcentagem_ganho,
                taxa,
            )

            # Atualizar o resumo financeiro geral
            self._atualizar_resumo_financeiro()

            logger.info(
                f"Venda registrada para {symbol}: Ganho de {ganho_total:.2f} USDT, porcentagem de {porcentagem_ganho:.2f}%"
            )

        except Exception as e:
            logger.error(f"Erro ao executar venda para {symbol}: {e}")
            logger.debug(traceback.format_exc())

    def _ajustar_quantidade_para_notional(
        self, symbol: str, quantidade: float, min_notional_padrao: float = 10.0
    ) -> float:
        """
        Ajusta a quantidade para garantir que o valor notional atenda ao mínimo permitido pela lista manual.
        """
        try:
            logger.info(f"Ajustando quantidade para notional para {symbol}...")

            # Obter o preço atual do ativo
            preco_atual = float(self.client.get_symbol_ticker(symbol=symbol)["price"])

            # Obter o valor mínimo de notional da lista manual ou usar o valor padrão
            min_notional = self.min_notional.get(symbol, min_notional_padrao)
            logger.info(f"Valor notional mínimo para {symbol}: {min_notional}")

            # Calcula o valor notional atual com a quantidade fornecida
            notional = preco_atual * quantidade
            logger.info(f"Valor notional atual para {symbol}: {notional}")

            # Se o notional for menor que o permitido, ajustar a quantidade
            if notional < min_notional:
                logger.warning(
                    f"Valor notional ({notional}) é menor que o mínimo permitido ({min_notional}) para {symbol}. "
                    f"Ajustando a quantidade..."
                )

                # Ajustar a quantidade mínima necessária para atender ao notional mínimo
                quantidade_ajustada = min_notional / preco_atual
                logger.info(f"Quantidade ajustada para {symbol}: {quantidade_ajustada}")

                saldo_disponivel = self.verificar_saldo_moedas(
                    symbol.replace("USDT", "")
                )
                if quantidade_ajustada > saldo_disponivel:
                    logger.error(
                        f"Saldo disponível ({saldo_disponivel}) é insuficiente para atingir o valor mínimo de notional ({min_notional})."
                    )
                    return 0.0  # Não executa a ordem se o saldo for insuficiente

                return quantidade_ajustada

            # Se o notional inicial já for suficiente, retorna a quantidade original
            return quantidade

        except Exception as e:
            logger.error(f"Erro ao ajustar quantidade para notional em {symbol}: {e}")
            logger.debug(traceback.format_exc())
            return 0.0

    def verificar_saldo_moedas(self, moeda: str) -> float:
        """
        Verifica o saldo disponível de uma moeda específica.
        """
        try:
            logger.info(f"Verificando saldo disponível em {moeda}...")

            # Obter todas as informações de conta (incluindo saldo) via API da Binance
            conta = self.client.get_account()

            # Procurar o saldo da moeda especificada
            for asset in conta["balances"]:
                if asset["asset"] == moeda:
                    saldo_disponivel = float(asset["free"])
                    logger.info(f"Saldo disponível em {moeda}: {saldo_disponivel}")
                    return saldo_disponivel

            # Se a moeda não for encontrada, retorna 0
            logger.warning(f"Saldo para a moeda {moeda} não encontrado.")
            return 0.0

        except Exception as e:
            logger.error(f"Erro ao verificar o saldo para a moeda {moeda}: {e}")
            logger.debug(traceback.format_exc())
            return 0.0

    def _calcular_ganhos(
        self,
        quantidade: float,
        preco_medio_compra: float,
        preco_venda: float,
        taxas_compras: float,
        taxa_venda: float,
    ) -> Tuple[float, float]:
        """
        Calcula o ganho total e a porcentagem de ganho.

        :param quantidade: Quantidade vendida.
        :param preco_medio_compra: Preço médio de compra.
        :param preco_venda: Preço de venda.
        :param taxas_compras: Total de taxas das compras.
        :param taxa_venda: Taxa da venda.
        :return: Tuple contendo o ganho total e a porcentagem de ganho.
        """
        valor_total_compras = preco_medio_compra * quantidade
        valor_total_vendas = preco_venda * quantidade
        ganho_total = (
            valor_total_vendas - valor_total_compras - taxas_compras - taxa_venda
        )

        porcentagem_ganho = (
            (ganho_total / valor_total_compras) * 100 if valor_total_compras else 0.0
        )

        return ganho_total, porcentagem_ganho

    def _atualizar_resumo_financeiro(self) -> None:
        """
        Atualiza o resumo financeiro geral no banco de dados.
        """
        valor_inicial = self.database_manager.obter_valor_inicial()
        valor_atual = self.database_manager.obter_valor_atual()
        porcentagem_geral = (
            ((valor_atual - valor_inicial) / valor_inicial) * 100
            if valor_inicial
            else 0.0
        )
        self.database_manager.atualizar_resumo_financeiro(
            valor_inicial, valor_atual, porcentagem_geral
        )

    def comprar(self, key: str, stake: str) -> Optional[float]:
        logger.info(f"Executando compra para {key}")
        resultado = self.trade_executor.executar_ordem(
            symbol=key, quantidade=stake, ordem_tipo="buy", venda_parcial=False
        )

        if not resultado:
            logger.error(f"Falha ao executar a ordem de compra para {key}.")
            return None

        preco_compra, taxa = resultado
        logger.info(f"Preço de compra: {preco_compra}, Taxa: {taxa}")

        valor_total = float(stake) * preco_compra
        self.registrar_e_notificar_operacao(
            symbol=key,
            tipo_operacao="COMPRA",
            quantidade=float(stake),
            preco=preco_compra,
            valor_total=valor_total,
            taxa=taxa,
            vendido=0,
        )

        return preco_compra

    def estrategia_venda_reversao(self, df, symbol):
        """
        Estratégia para detectar reversão de mercado e vender.
        """
        try:
            indicadores = self.obter_indicadores(df)
            if indicadores is None:
                return "Esperar", 0.0

            rsi = indicadores["rsi"]
            rsi_anterior = indicadores["rsi_anterior"]
            momentum = indicadores["momentum"]
            ultimo_preco = indicadores["ultimo_preco"]
            bb_upper = indicadores["bb_upper"]
            volume_atual = indicadores["volume_atual"]
            volume_medio = indicadores["volume_medio"]

            # Venda parcial se RSI estiver sobrecomprado e volume acima da média
            if rsi > 70 and volume_atual > volume_medio * 1.2:
                return "VenderParcial", ultimo_preco

            # Venda total se RSI mostrar divergência negativa e momentum cair
            if rsi < rsi_anterior and momentum < 0:
                return "VenderTotal", ultimo_preco

            # Venda se o preço tocar a banda superior de Bollinger
            if ultimo_preco > bb_upper:
                return "VenderTotal", ultimo_preco

            return "Esperar", 0.0

        except Exception as e:
            logger.error(f"Erro na estratégia de venda reversão para {symbol}: {e}")
            logger.debug(traceback.format_exc())
            return "Esperar", 0.0

    def estrategia_trading(self, df: Any, sentimento: str) -> str:
        try:
            indicadores = self.obter_indicadores(df)
            if indicadores is None:
                return "Esperar"

            rsi = indicadores["rsi"]
            rsi_anterior = indicadores["rsi_anterior"]
            sma50 = indicadores["sma50"]
            sma200 = indicadores["sma200"]
            vwap = indicadores["vwap"]
            ultimo_preco = indicadores["ultimo_preco"]
            preco_anterior = indicadores["preco_anterior"]
            bb_upper = indicadores["bb_upper"]
            bb_lower = indicadores["bb_lower"]
            momentum = indicadores["momentum"]
            volume_atual = indicadores["volume_atual"]
            volume_medio = indicadores["volume_medio"]

            # Identificando níveis de suporte e resistência
            resistencia = bb_upper if ultimo_preco < bb_upper else vwap
            suporte = bb_lower if ultimo_preco > bb_lower else vwap

            if ultimo_preco > vwap and volume_atual > volume_medio * 1.5:
                return "Comprar"
            elif ultimo_preco < vwap and volume_atual > volume_medio * 1.5:
                return "Vender"

            sentimento = sentimento.lower()
            positivo = "positivo" in sentimento
            negativo = "negativo" in sentimento

            if sentimento == "neutro":
                if rsi < 35 and sma50 > sma200:
                    return "Comprar"
                elif rsi > 70 and sma50 < sma200:
                    return "Vender"
                elif rsi < 35 and ultimo_preco > vwap:
                    return "Comprar"
                elif rsi > 70 and ultimo_preco < vwap:
                    return "Vender"
                elif ultimo_preco > vwap and ultimo_preco < bb_upper:
                    return "Comprar"
                elif ultimo_preco < vwap and ultimo_preco > bb_lower:
                    return "Vender"
                elif ultimo_preco > vwap and momentum > 0:
                    return "Comprar"
                elif ultimo_preco < vwap and momentum < 0:
                    return "Vender"
                elif ultimo_preco > resistencia:
                    return "Comprar"
                elif ultimo_preco < suporte:
                    return "Vender"
                elif ultimo_preco < preco_anterior and rsi > rsi_anterior:
                    return "Comprar"
                elif ultimo_preco > preco_anterior and rsi < rsi_anterior:
                    return "Vender"
            else:
                if rsi < 35 and sma50 > sma200 and positivo:
                    return "Comprar"
                elif rsi > 70 and sma50 < sma200 and negativo:
                    return "Vender"
                elif rsi < 35 and ultimo_preco > vwap and positivo:
                    return "Comprar"
                elif rsi > 70 and ultimo_preco < vwap and negativo:
                    return "Vender"
                elif ultimo_preco > vwap and ultimo_preco < bb_upper and positivo:
                    return "Comprar"
                elif ultimo_preco < vwap and ultimo_preco > bb_lower and negativo:
                    return "Vender"
                elif ultimo_preco > vwap and momentum > 0 and positivo:
                    return "Comprar"
                elif ultimo_preco < vwap and momentum < 0 and negativo:
                    return "Vender"
                elif ultimo_preco > resistencia and positivo:
                    return "Comprar"
                elif ultimo_preco < suporte and negativo:
                    return "Vender"
                elif ultimo_preco < preco_anterior and rsi > rsi_anterior:
                    return "Comprar"
                elif ultimo_preco > preco_anterior and rsi < rsi_anterior:
                    return "Vender"

            return "Esperar"

        except Exception as e:
            logger.error(f"Erro na estratégia de trading: {e}")
            logger.debug(traceback.format_exc())
            return "Esperar"

    def registrar_e_notificar_operacao(
        self,
        symbol: str,
        tipo_operacao: str,
        quantidade: float,
        preco: float,
        valor_total: float,
        taxa: float,
        vendido: int,
    ) -> None:
        """
        Registra a operação no banco de dados e envia notificação via Telegram.
        """
        quantidade_str = f"{quantidade:.8f}"

        # Registrar a operação no banco de dados
        data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.database_manager.registrar_transacao(
            data_hora=data_hora,
            simbolo=symbol,
            tipo=tipo_operacao,
            quantidade=float(quantidade_str),
            preco=preco,
            valor_total=valor_total,
            taxa=taxa,
            vendido=vendido,
        )

        # Enviar notificação para o Telegram
        self.telegram_notifier.notificar(
            tipo=tipo_operacao,
            symbol=symbol,
            quantidade=quantidade_str,
            preco=preco,
            valor_total=valor_total,
        )

        # Logar a operação
        logger.info(
            f"{tipo_operacao} de {quantidade_str} {symbol} a {preco} USDT (Total: {valor_total} USDT)"
        )

    def executar_estrategia_compra(self) -> None:
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

                # Determinar se deve comprar
                acao = self.estrategia_trading(df, sentimento)

                if acao == "Comprar":
                    stake = self.calcular_stake(key)
                    if not stake:
                        logger.error(f"Stake não foi calculado para {key}.")
                        continue

                    # Executar compra
                    preco_compra = self.comprar(key, stake)
                    if preco_compra is not None:
                        logger.info(f"Compra executada para {key}: {preco_compra}")

            except Exception as e:
                logger.error(f"Erro inesperado no símbolo {key}: {e}")
                logger.debug(traceback.format_exc())

        self.database_manager.fechar_conexao()

    def executar_estrategia_venda(self) -> None:
        for key, value in self.symbols.items():
            try:
                # Obter dados de mercado
                df = self.data_handler.obter_dados_mercado(key)
                if df.empty:
                    continue

                # Calcular indicadores
                df = self.indicator_calculator.calcular_indicadores(df)

                # Obter o stop-loss atual do banco de dados
                stop_loss_atual, preco_maximo = self.database_manager.obter_stop_loss(
                    key
                )

                # Atualizar o preço máximo e stop-loss dinâmico
                preco_atual = df["close"].iloc[-1]

                if preco_maximo is None:
                    preco_maximo = preco_atual
                    stop_loss_atual = preco_maximo * 0.97

                if preco_atual > preco_maximo:
                    preco_maximo = preco_atual
                    stop_loss_atual = preco_maximo * 0.97

                # Se o preço atual cair abaixo do stop-loss, vender a posição
                if preco_atual <= stop_loss_atual:
                    logger.info(
                        f"Executando venda devido ao stop-loss atingido para {key}"
                    )
                    self.vender(key, value, "Vender", str(preco_atual))

                # Atualizar o stop-loss no banco de dados
                self.database_manager.salvar_stop_loss(
                    key, stop_loss_atual, preco_maximo
                )

            except Exception as e:
                logger.error(f"Erro inesperado no símbolo {key}: {e}")
                logger.debug(traceback.format_exc())

        self.database_manager.fechar_conexao()

    def obter_indicadores(self, df):
        """
        Calcula e retorna os indicadores técnicos necessários.
        """
        try:
            # Verificar se o DataFrame tem dados suficientes
            if len(df) < 2:
                logger.warning("Dados insuficientes para calcular indicadores.")
                return None

            indicadores = {
                "rsi": df["RSI"].iloc[-1],
                "rsi_anterior": df["RSI"].iloc[-2],
                "momentum": df["Momentum"].iloc[-1],
                "ultimo_preco": df["close"].iloc[-1],
                "bb_upper": df["BB_upper"].iloc[-1],
                "bb_lower": df["BB_lower"].iloc[-1],
                "volume_atual": df["Volume"].iloc[-1],
                "volume_medio": df["Volume"].mean(),
                "sma50": df["SMA50"].iloc[-1] if "SMA50" in df.columns else None,
                "sma200": df["SMA200"].iloc[-1] if "SMA200" in df.columns else None,
                "vwap": df["VWAP"].iloc[-1],
                "preco_anterior": df["close"].iloc[-2],
            }
            return indicadores
        except Exception as e:
            logger.error(f"Erro ao obter indicadores: {e}")
            logger.debug(traceback.format_exc())
            return None

    def obter_dados_mercado(self, df):
        """
        Obtém dados de mercado necessários para estratégias.
        """
        indicadores = self.obter_indicadores(df)
        if indicadores is None:
            return None

        rsi = indicadores["rsi"]
        rsi_anterior = indicadores["rsi_anterior"]
        momentum = indicadores["momentum"]
        ultimo_preco = indicadores["ultimo_preco"]
        bb_upper = indicadores["bb_upper"]
        volume_atual = indicadores["volume_atual"]
        volume_medio = indicadores["volume_medio"]

        return (
            rsi,
            rsi_anterior,
            momentum,
            ultimo_preco,
            bb_upper,
            volume_atual,
            volume_medio,
        )
