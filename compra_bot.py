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
