import os
import logging
import ast
from trading_bot import TradingBot
from dotenv import load_dotenv
from binance.client import Client
import time

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    handlers=[
        logging.FileHandler("bot_trading.log", mode="a"),
        logging.StreamHandler(),
    ],
)

# Ajusta o nível de logging das bibliotecas HTTP para WARNING
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


if __name__ == "__main__":
    load_dotenv()

    # Configurações de API e símbolos
    binance_api_key = os.getenv("BINANCE_API_KEY")
    binance_secret_key = os.getenv("BINANCE_SECRET_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    cryptocompare_api_key = os.getenv("CRYPTOCOMPARE_API_KEY")
    symbols = ast.literal_eval(os.getenv("SYMBOLS"))
    casas_decimais = ast.literal_eval(os.getenv("CASAS_DECIMAIS"))
    min_notional = ast.literal_eval(os.getenv("MIN_NOTIONAL"))

    # Inicializar o bot de compra
    bot = TradingBot(
        binance_api_key=binance_api_key,
        binance_secret_key=binance_secret_key,
        openai_api_key=openai_api_key,
        cryptocompare_api_key=cryptocompare_api_key,
        symbols=symbols,
        casas_decimais=casas_decimais,
        min_notional=min_notional,
    )

    # Executa apenas a estratégia de compra
    bot.executar_estrategia_compra()

    def vender(self, key, value, acao, stake):
        logging.info(f"Executando {acao} para {key}")

        # Obter preço médio e quantidade total de compras
        preco_medio_compra, quantidade_total, taxas_total_compras = (
            self.calcular_preco_medio_e_quantidade_banco(key)
        )

        # Obter quantidade restante de vendas
        quantidade_restante = self.database_manager.obter_quantidade_restante(key)

        if quantidade_restante is None:
            quantidade_restante = quantidade_total

        if quantidade_restante == 0:
            logging.warning(f"Quantidade total para venda de {key} é zero.")
            return

        # Vender 25% da quantidade restante
        quantidade_venda_parcial = quantidade_restante * 0.25
        quantidade_ajustada = self._ajustar_quantidade_para_notional(
            key, quantidade_venda_parcial
        )

        if quantidade_ajustada <= 0:
            logging.error(
                f"Quantidade ajustada para {key} é insuficiente. Operação de venda parcial cancelada."
            )
            return

        # Executar a venda parcial
        resultado = self.trade_executor.executar_ordem(
            key, quantidade_ajustada, "sell", venda_parcial=True, moeda_venda=value
        )

        if resultado is None:
            logging.error(f"Falha ao executar a ordem de venda para {key}.")
        else:
            preco_venda_real, taxa = resultado
            quantidade_restante -= (
                quantidade_ajustada  # Atualiza a quantidade total restante
            )

            # Atualizar a quantidade restante no banco de dados
            self.database_manager.atualizar_quantidade_restante(
                key, quantidade_restante
            )

            # Notificar a venda parcial
            self.registrar_e_notificar_operacao(
                key,
                "VENDA PARCIAL",
                float(quantidade_ajustada),
                preco_venda_real,
                float(quantidade_ajustada) * preco_venda_real,
                taxa,
                1,
            )

        time.sleep(10)  # Intervalo entre vendas parciais
