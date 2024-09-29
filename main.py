import os
import logging
import ast
from trading_bot import TradingBot
from dotenv import load_dotenv

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
    # Carregar variáveis de ambiente
    load_dotenv()

    # Obter as chaves de API das variáveis de ambiente
    binance_api_key = os.getenv("BINANCE_API_KEY")
    binance_secret_key = os.getenv("BINANCE_SECRET_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    cryptocompare_api_key = os.getenv("CRYPTOCOMPARE_API_KEY")
    symbols = os.getenv("SYMBOLS")
    casas_decimais = os.getenv("CASAS_DECIMAIS")
    min_notional = os.getenv("MIN_NOTIONAL")

    if not binance_api_key or not binance_secret_key:
        logging.error("Chaves de API da Binance não encontradas.")
        exit(1)

    if not openai_api_key:
        logging.error("Chave de API da OpenAI não encontrada.")
        exit(1)

    if not cryptocompare_api_key:
        logging.error("Chave de API da CryptoCompare não encontrada.")
        exit(1)

    # Criar uma instância do TradingBot
    bot = TradingBot(
        binance_api_key=binance_api_key,
        binance_secret_key=binance_secret_key,
        openai_api_key=openai_api_key,
        cryptocompare_api_key=cryptocompare_api_key,
        symbols=ast.literal_eval(symbols),
        casas_decimais=ast.literal_eval(casas_decimais),
        min_notional=ast.literal_eval(min_notional),
    )

    # Iniciar o bot
    bot.executar_estrategia()
