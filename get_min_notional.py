from binance.client import Client
import os
from decimal import Decimal
import ast

# Configurar as chaves da API da Binance (substitua ou use dotenv para carregar essas variáveis de ambiente)
API_KEY = os.getenv("BINANCE_API_KEY", "YOUR_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY", "YOUR_SECRET_KEY")

# Inicializa o cliente da Binance
client = Client(api_key=API_KEY, api_secret=API_SECRET)


def obter_notional_minimo_para_moedas(client, moedas):
    """
    Obtém o valor mínimo de notional permitido para cada moeda da lista de moedas fornecida.

    :param client: Cliente da API Binance
    :param moedas: Lista de símbolos das moedas (ex: ["BTCUSDT", "ETHUSDT"])
    :return: Dicionário com o valor mínimo de notional para cada moeda
    """
    notional_minimo = {}
    exchange_info = client.get_exchange_info()

    for symbol_info in exchange_info["symbols"]:
        symbol = symbol_info["symbol"]
        if symbol in moedas:
            for filtro in symbol_info["filters"]:
                if filtro["filterType"] == "NOTIONAL":
                    # Obter o valor mínimo de notional
                    min_notional = float(filtro["minNotional"])
                    notional_minimo[symbol] = min_notional

    return notional_minimo


simbols = ast.literal_eval(os.getenv("SYMBOLS"))
moedas = ""

for key, value in simbols.items():
    moedas += key + ","

# Remover a última vírgula da variável moedas
moedas = moedas.rstrip(",")


# Converter a string em uma lista
moedas = moedas.split(",")

# Remover espaços em branco extras, se houver
moedas = [moeda.strip() for moeda in moedas]

print(f"Lista de moedas: {moedas}")

# Executar a função
notional_minimo_por_moeda = obter_notional_minimo_para_moedas(client, moedas)

# Exibir o resultado
for moeda, notional in notional_minimo_por_moeda.items():
    print(f"Moeda: {moeda}, Mínimo de Notional: {notional} USDT")

# Salvar o resultado em um arquivo (opcional)
with open("notional_minimo_moedas.txt", "w") as f:
    for moeda, notional in notional_minimo_por_moeda.items():
        f.write(f"Moeda: {moeda}, Mínimo de Notional: {notional} USDT\n")
