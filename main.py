import os
import time
import logging
from typing import Optional, List
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import pandas_ta as ta
import requests
import openai
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import sqlite3

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot_trading.log"), logging.StreamHandler()],
)


class TradingBot:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        openai_api_key: str,
        cryptocompare_api_key: str,
        symbols: List[str],
        interval: str = Client.KLINE_INTERVAL_15MINUTE,
        rsi_length: int = 14,
    ):
        """
        Inicializa o TradingBot com as credenciais da API Binance, OpenAI e CryptoCompare, e parâmetros de negociação.
        """
        self.client = Client(api_key=api_key, api_secret=api_secret)
        self.symbols = symbols
        self.interval = interval
        self.rsi_length = rsi_length
        openai.api_key = openai_api_key  # Configurar a chave da OpenAI
        self.sentimento_mercado = "Neutro"  # Inicializar o sentimento do mercado
        self.symbol_to_name = {
            "BTCUSDT": "BTC",
            "ETHUSDT": "ETH",
            "SOLUSDT": "SOL",
            "PENDLEUSDT": "PENDLE",
            "AVAXUSDT": "AVAX",
            "DOGEUSDT": "DOGE",
            "JUPUSDT": "JUP",
            "PEPEUSDT": "PEPE",
        }
        self.cryptocompare_api_key = (
            cryptocompare_api_key  # Armazenar a chave da API CryptoCompare
        )

        # Inicializar conexão com o banco de dados SQLite
        self.conn = sqlite3.connect("trades.db")
        self.cursor = self.conn.cursor()
        self.criar_tabela_transacoes()

    def criar_tabela_transacoes(self):
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS transacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora TEXT,
                simbolo TEXT,
                tipo TEXT,
                quantidade REAL,
                preco REAL,
                valor_total REAL
            )
        """
        )
        self.conn.commit()

    def obter_dados_mercado(
        self, symbol: str, limit: int = 1000
    ) -> Optional[pd.DataFrame]:
        try:
            klines = self.client.get_klines(
                symbol=symbol, interval=self.interval, limit=limit
            )

        except BinanceAPIException as e:
            logging.error(f"[{symbol}] Erro na API Binance: {e.message}")
            return None
        except BinanceRequestException as e:
            logging.error(f"[{symbol}] Erro de requisição à Binance: {e.message}")
            return None
        except Exception as e:
            logging.error(f"[{symbol}] Erro ao obter dados de mercado: {e}")
            return None

        # Converter para DataFrame
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

        # Converter o timestamp para datetime e os valores de 'close' para float
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close"] = df["close"].astype(float)

        # Ordenar os dados por timestamp em ordem crescente
        df = df.sort_values("timestamp").reset_index(drop=True)

        return df

    def calcular_indicadores(self, df: pd.DataFrame) -> pd.DataFrame:
        df["RSI"] = ta.rsi(df["close"], length=self.rsi_length)
        df["SMA50"] = ta.sma(df["close"], length=50)
        df["SMA200"] = ta.sma(df["close"], length=200)

        macd = ta.macd(df["close"])
        df["MACD"] = macd["MACD_12_26_9"]
        df["MACD_signal"] = macd["MACDs_12_26_9"]

        return df

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
        stake_quantidade = self.ajustar_quantidade(symbol, stake_quantidade)

        return stake_quantidade

    def ajustar_quantidade(self, symbol: str, quantidade: float) -> float:
        """
        Ajusta a quantidade para atender ao passo mínimo de quantidade da Binance.

        :param symbol: Símbolo de negociação.
        :param quantidade: Quantidade inicial.
        :return: Quantidade ajustada.
        """
        info = self.client.get_symbol_info(symbol)
        step_size = float(
            next(filter(lambda f: f["filterType"] == "LOT_SIZE", info["filters"]))[
                "stepSize"
            ]
        )
        quantidade_ajustada = quantidade - (quantidade % step_size)
        return float("{:.8f}".format(quantidade_ajustada))

    def executar_ordem_compra(
        self, symbol: str, stop_loss_percent: float, take_profit_percent: float
    ):
        """
        Executa uma ordem de compra com stop loss e take profit.

        :param symbol: Par de negociação (ex: 'BTCUSDT').
        :param stop_loss_percent: Percentual para o preço de stop loss em relação ao preço de compra.
        :param take_profit_percent: Percentual para o preço de take profit em relação ao preço de compra.
        """
        try:
            # Calcular a stake baseada no risco de 1%
            stake = self.calcular_stake(symbol)
            if stake == 0.0:
                logging.error(
                    f"Stake calculada é zero para {symbol}. Operação abortada."
                )
                return

            # Executar a ordem de compra a mercado
            ordem_compra = self.client.order_market_buy(symbol=symbol, quantity=stake)
            logging.info(f"Ordem de compra executada para {symbol}: {ordem_compra}")

            # Obter o preço de compra
            preco_compra = float(ordem_compra["fills"][0]["price"])
            quantidade = float(ordem_compra["executedQty"])

            # Calcular o valor total da operação
            valor_total = preco_compra * quantidade

            # Registrar a transação no banco de dados
            self.registrar_transacao(
                data_hora=time.strftime("%Y-%m-%d %H:%M:%S"),
                simbolo=symbol,
                tipo="COMPRA",
                quantidade=quantidade,
                preco=preco_compra,
                valor_total=valor_total,
            )

            # Calcular Stop Loss e Take Profit
            stop_loss = preco_compra * (1 - stop_loss_percent / 100)
            take_profit = preco_compra * (1 + take_profit_percent / 100)

            # Ajustar preços para atender às restrições de tick size
            stop_loss = self.ajustar_preco(symbol, stop_loss)
            take_profit = self.ajustar_preco(symbol, take_profit)

            # Configurar ordens de Stop Loss e Take Profit
            ordem_stop_loss = self.client.create_order(
                symbol=symbol,
                side="SELL",
                type="STOP_LOSS_LIMIT",
                quantity=stake,
                price=f"{stop_loss}",
                stopPrice=f"{stop_loss * 0.99}",
                timeInForce="GTC",
            )
            logging.info(f"Ordem de Stop Loss configurada: {ordem_stop_loss}")

            ordem_take_profit = self.client.create_order(
                symbol=symbol,
                side="SELL",
                type="TAKE_PROFIT_LIMIT",
                quantity=stake,
                price=f"{take_profit}",
                stopPrice=f"{take_profit * 0.99}",
                timeInForce="GTC",
            )
            logging.info(f"Ordem de Take Profit configurada: {ordem_take_profit}")

        except BinanceAPIException as e:
            logging.error(f"Erro ao executar ordem de compra para {symbol}: {e}")

    def executar_ordem_venda(
        self, symbol: str, stop_loss_percent: float, take_profit_percent: float
    ):
        """
        Executa uma ordem de venda com stop loss e take profit.

        :param symbol: Par de negociação (ex: 'BTCUSDT').
        :param stop_loss_percent: Percentual para o preço de stop loss em relação ao preço de venda.
        :param take_profit_percent: Percentual para o preço de take profit em relação ao preço de venda.
        """
        try:
            # Calcular a stake baseada no risco de 1%
            stake = self.calcular_stake(symbol)
            if stake == 0.0:
                logging.error(
                    f"Stake calculada é zero para {symbol}. Operação abortada."
                )
                return

            # Executar a ordem de venda a mercado
            ordem_venda = self.client.order_market_sell(symbol=symbol, quantity=stake)
            logging.info(f"Ordem de venda executada para {symbol}: {ordem_venda}")

            # Obter o preço de venda
            preco_venda = float(ordem_venda["fills"][0]["price"])
            quantidade = float(ordem_venda["executedQty"])

            # Calcular o valor total da operação
            valor_total = preco_venda * quantidade

            # Registrar a transação no banco de dados
            self.registrar_transacao(
                data_hora=time.strftime("%Y-%m-%d %H:%M:%S"),
                simbolo=symbol,
                tipo="VENDA",
                quantidade=quantidade,
                preco=preco_venda,
                valor_total=valor_total,
            )

            # Calcular Stop Loss e Take Profit
            stop_loss = preco_venda * (1 + stop_loss_percent / 100)
            take_profit = preco_venda * (1 - take_profit_percent / 100)

            # Ajustar preços para atender às restrições de tick size
            stop_loss = self.ajustar_preco(symbol, stop_loss)
            take_profit = self.ajustar_preco(symbol, take_profit)

            # Configurar ordens de Stop Loss e Take Profit
            ordem_stop_loss = self.client.create_order(
                symbol=symbol,
                side="BUY",
                type="STOP_LOSS_LIMIT",
                quantity=stake,
                price=f"{stop_loss}",
                stopPrice=f"{stop_loss * 1.01}",
                timeInForce="GTC",
            )
            logging.info(f"Ordem de Stop Loss configurada: {ordem_stop_loss}")

            ordem_take_profit = self.client.create_order(
                symbol=symbol,
                side="BUY",
                type="TAKE_PROFIT_LIMIT",
                quantity=stake,
                price=f"{take_profit}",
                stopPrice=f"{take_profit * 1.01}",
                timeInForce="GTC",
            )
            logging.info(f"Ordem de Take Profit configurada: {ordem_take_profit}")

        except BinanceAPIException as e:
            logging.error(f"Erro ao executar ordem de venda para {symbol}: {e}")

    def registrar_transacao(
        self,
        data_hora: str,
        simbolo: str,
        tipo: str,
        quantidade: float,
        preco: float,
        valor_total: float,
    ):
        self.cursor.execute(
            """
            INSERT INTO transacoes (data_hora, simbolo, tipo, quantidade, preco, valor_total)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (data_hora, simbolo, tipo, quantidade, preco, valor_total),
        )
        self.conn.commit()
        logging.info(
            f"Transação registrada: {tipo} de {quantidade} {simbolo} a {preco} USDT (Total: {valor_total} USDT)"
        )

    def analisar_sentimento(self, symbol: str) -> str:
        # Obter o símbolo da moeda a partir do mapeamento
        coin_symbol = self.symbol_to_name.get(symbol, None)
        if not coin_symbol:
            logging.error(
                f"[{symbol}] Símbolo da moeda não encontrado para o símbolo fornecido."
            )
            return "Neutro"

        # Coletar notícias usando a CryptoCompare API
        try:
            # Definir o endpoint de notícias da CryptoCompare
            url = "https://min-api.cryptocompare.com/data/v2/news/"

            # Configurar os parâmetros da requisição
            params = {
                "categories": coin_symbol,
                "lang": "EN",
                "api_key": self.cryptocompare_api_key,
            }

            response = requests.get(url, params=params)
            if response.status_code != 200:
                logging.error(
                    f"[{symbol}] Erro ao obter notícias. Status code: {response.status_code}"
                )
                return "Neutro"

            data = response.json()
            articles = data.get("Data", [])
            if not articles:
                logging.info(f"[{symbol}] Nenhum artigo de notícias encontrado.")
                return "Neutro"

            # Concatenar os títulos dos últimos artigos de notícias
            textos = " ".join([article["title"] for article in articles[:5]])

            # Usar o GPT para analisar o sentimento
            prompt = f"Analise o seguinte texto e determine o sentimento geral sobre {coin_symbol} responda somente positivo, negativo ou neutro, conforme sua análise quanto a essa criptomoeda:\n\n{textos}"
            resposta = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                n=1,
                stop=None,
                temperature=0.5,
            )
            sentimento = resposta.choices[0].message.content.strip()
            return sentimento

        except Exception as e:
            logging.error(f"[{symbol}] Erro ao analisar o sentimento: {e}")
            return "Neutro"

    def analise_mercado_completa(self, symbol: str, df: pd.DataFrame):
        coin_symbol = self.symbol_to_name.get(symbol, None)
        # Definir o endpoint de notícias da CryptoCompare
        url = "https://min-api.cryptocompare.com/data/v2/news/"

        # Configurar os parâmetros da requisição
        params = {
            "categories": coin_symbol,
            "lang": "EN",
            "api_key": self.cryptocompare_api_key,
        }

        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(
                f"[{symbol}] Erro ao obter notícias. Status code: {response.status_code}"
            )
            return "Neutro"

        data = response.json()
        articles = data.get("Data", [])

        prompt = f"O RSI é {df['RSI'].iloc[-1]}, SMA50 é {df['SMA50'].iloc[-1]} e SMA200 é {df['SMA200'].iloc[-1]} para {coin_symbol}. Com base nos seguintes artigos de notícias, responda somente está com tendencia de ALTA, BAIXA ou ESTAVEL?\n\n"
        # Concatenar os títulos das notícias
        prompt += " ".join([article["title"] for article in articles[:5]])

        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
        )

        return response.choices[0].message.content.strip()

    def estrategia_trading(
        self, df: pd.DataFrame, sentimento: str, sentimento_completo: str
    ) -> str:
        # Obter os valores atuais dos indicadores
        ultimo_rsi = df["RSI"].iloc[-1]
        sma50_atual = df["SMA50"].iloc[-1]
        sma200_atual = df["SMA200"].iloc[-1]

        # Verificar se os valores necessários não são NaN
        if any(
            [
                np.isnan(ultimo_rsi),
                np.isnan(sma50_atual),
                np.isnan(sma200_atual),
            ]
        ):
            logging.debug("Indicadores com valores NaN detectados.")
            return "Dados insuficientes"

        # Verificar condições para 'Comprar'
        if (
            ultimo_rsi < 30
            and sma50_atual > sma200_atual
            and sentimento.lower() == "positivo"
            and sentimento_completo.lower() == "alta"
        ):
            return "Comprar"

        # Verificar condições para 'Vender'
        elif (
            ultimo_rsi > 70
            and sma50_atual < sma200_atual
            and sentimento.lower() == "negativo"
            and sentimento_completo.lower() == "baixa"
        ):
            return "Vender"

        else:
            return "Esperar"

    def executar_trading(self):
        """
        Loop principal para executar o bot de trading.
        """

        try:
            while True:
                for symbol in self.symbols:

                    sentimento = self.analisar_sentimento(symbol)
                    df = self.obter_dados_mercado(symbol=symbol, limit=1000)
                    if df is not None:
                        # Verificar e remover valores nulos (NaN)
                        if df["close"].isnull().values.any():
                            logging.warning(
                                f"[{symbol}] Dados contêm valores nulos. Limpando dados..."
                            )
                            df = df.dropna(subset=["close"])

                        # Verificar se ainda temos dados suficientes após remover os NaN
                        tamanho_minimo = 200  # Para calcular SMA200
                        if len(df) < tamanho_minimo:
                            logging.warning(
                                f"[{symbol}] Dados insuficientes para calcular indicadores. Aguardando..."
                            )
                            continue

                        # Calcular indicadores técnicos
                        df = self.calcular_indicadores(df)

                        # Verificar se os indicadores foram calculados corretamente
                        if not any(
                            [
                                np.isnan(df["RSI"].iloc[-1]),
                                np.isnan(df["SMA50"].iloc[-1]),
                                np.isnan(df["SMA200"].iloc[-1]),
                            ]
                        ):
                            sentimento_completo = self.analise_mercado_completa(
                                symbol, df
                            )
                            acao = self.estrategia_trading(
                                df, sentimento, sentimento_completo
                            )
                            ultimo_rsi = df["RSI"].iloc[-1]

                            if acao == "Comprar":
                                self.executar_ordem_compra(
                                    symbol,
                                    stop_loss_percent=1.0,
                                    take_profit_percent=2.0,
                                )
                            elif acao == "Vender":
                                self.executar_ordem_venda(
                                    symbol,
                                    stop_loss_percent=1.0,
                                    take_profit_percent=2.0,
                                )

                            logging.info(
                                f"[{symbol}] Ação sugerida: {acao} | RSI: {ultimo_rsi:.2f}"
                            )

                            # Aqui você pode adicionar a lógica para executar a ação sugerida
                            # Exemplo: self.executar_ordem(symbol, acao)

                        else:
                            logging.warning(
                                f"[{symbol}] Não foi possível calcular os indicadores."
                            )
                    else:
                        logging.error(f"[{symbol}] Falha ao obter dados de mercado.")

                pass
                time.sleep(600)

        except KeyboardInterrupt:
            logging.info("Bot interrompido pelo usuário.")
            self.fechar_conexao()
        except Exception as e:
            logging.error(f"Erro inesperado: {e}")
            self.fechar_conexao()

    def fechar_conexao(self):
        self.conn.close()
        logging.info("Conexão com o banco de dados fechada.")


if __name__ == "__main__":
    # Obter as chaves de API das variáveis de ambiente
    binance_api_key = os.getenv("BINANCE_API_KEY")
    binance_secret_key = os.getenv("BINANCE_SECRET_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    cryptocompare_api_key = os.getenv("CRYPTOCOMPARE_API_KEY")

    if not binance_api_key or not binance_secret_key:
        logging.error("Chaves de API da Binance não encontradas.")
        exit(1)

    if not openai_api_key:
        logging.error("Chave de API da OpenAI não encontrada.")
        exit(1)

    if not cryptocompare_api_key:
        logging.error("Chave de API da CryptoCompare não encontrada.")
        exit(1)

    # Definir a lista de símbolos desejados
    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "PENDLEUSDT",
        "AVAXUSDT",
        "DOGEUSDT",
        "JUPUSDT",
        "PEPEUSDT",
    ]  # Adicione os símbolos que você deseja monitorar

    # Criar uma instância do TradingBot
    bot = TradingBot(
        api_key=binance_api_key,
        api_secret=binance_secret_key,
        openai_api_key=openai_api_key,
        cryptocompare_api_key=cryptocompare_api_key,
        symbols=symbols,
    )

    # Iniciar o bot
    bot.executar_trading()
