import os
import logging
import ast
from trading_bot import TradingBot
from dotenv import load_dotenv
from datetime import datetime, timedelta
import numpy as np

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    handlers=[
        logging.FileHandler("bot_stop.log", mode="a"),
        logging.StreamHandler(),
    ],
)

# Ajusta o nível de logging das bibliotecas HTTP para WARNING
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


# Ajusta o nível de logging das bibliotecas HTTP para WARNING
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Caminho para o arquivo que armazenará o timestamp da última execução
TIMESTAMP_FILE = "ultima_execucao_stoploss.txt"


def ler_ultimo_timestamp():
    """
    Lê o timestamp da última execução a partir de um arquivo.
    Retorna None se o arquivo não existir.
    """
    if not os.path.exists(TIMESTAMP_FILE):
        return None
    with open(TIMESTAMP_FILE, "r") as f:
        timestamp_str = f.read().strip()
        if timestamp_str:
            return datetime.fromisoformat(timestamp_str)
    return None


def salvar_timestamp_atual():
    """
    Salva o timestamp atual no arquivo de controle.
    """
    with open(TIMESTAMP_FILE, "w") as f:
        f.write(datetime.now().isoformat())


def calcular_volatilidade(df, periodos=14):
    """
    Calcula a volatilidade com base no desvio padrão dos preços de fechamento.
    """
    return np.std(df["close"].tail(periodos))


def ajustar_intervalo_por_volatilidade(volatilidade):
    """
    Ajusta o intervalo de atualização baseado na volatilidade.
    """
    if volatilidade < 0.005:  # Baixa volatilidade
        return 30  # Intervalo de 30 minutos
    elif volatilidade < 0.01:  # Volatilidade moderada
        return 15  # Intervalo de 15 minutos
    else:  # Alta volatilidade
        return 5  # Intervalo de 5 minutos


def passou_tempo_suficiente(intervalo_minutos: int) -> bool:
    """
    Verifica se já passou o tempo suficiente desde a última execução.
    Retorna True se já passou o intervalo necessário, False caso contrário.
    """
    ultimo_timestamp = ler_ultimo_timestamp()

    if ultimo_timestamp is None:
        # Se não houver registro anterior, é a primeira execução
        return True

    # Calcula o tempo que passou desde a última execução
    tempo_atual = datetime.now()
    tempo_diferenca = tempo_atual - ultimo_timestamp

    # Verifica se a diferença de tempo é maior ou igual ao intervalo necessário
    return tempo_diferenca >= timedelta(minutes=intervalo_minutos)


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

    # Pega o primeiro par de negociação do dicionário SYMBOLS
    symbol = list(symbols.keys())[0]  # Isso deve resultar em "BTCUSDT"
    logging.info(f"Obtendo dados de mercado para o símbolo: {symbol}")
    df = bot.data_handler_compra.obter_dados_mercado(symbol)

    if not df.empty:
        # Calcula a volatilidade
        volatilidade = calcular_volatilidade(df)

        # Ajusta o intervalo de tempo baseado na volatilidade
        intervalo_minutos = ajustar_intervalo_por_volatilidade(volatilidade)

        # Verifica se já passou tempo suficiente desde a última execução
        if passou_tempo_suficiente(intervalo_minutos):
            logging.info(
                f"Volatilidade atual: {volatilidade:.4f}, Intervalo de atualização: {intervalo_minutos} minutos"
            )
            logging.info("Tempo suficiente passado, executando o código...")

            # Executa apenas a estratégia de compra
            bot.atualiza_stoploss()

            # Atualiza o timestamp de execução
            salvar_timestamp_atual()
