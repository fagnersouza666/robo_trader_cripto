# Exemplo de script Python para descobrir o número de casas decimais permitido para uma série de moedas usando a API da Binance

from binance.client import Client
import os
from decimal import Decimal
import ast

# Configurar as chaves da API da Binance (você pode usar dotenv para carregar essas variáveis de ambiente)
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")

# Inicializa o cliente da Binance
client = Client(api_key=API_KEY, api_secret=API_SECRET)


def obter_casas_decimais_para_moedas(client, moedas):
    """
    Obtém o número de casas decimais permitido para cada moeda da lista de moedas fornecida.

    :param client: Cliente da API Binance
    :param moedas: Lista de símbolos das moedas (ex: ["BTCUSDT", "ETHUSDT"])
    :return: Dicionário com o número de casas decimais para cada moeda
    """
    casas_decimais = {}
    exchange_info = client.get_exchange_info()

    for symbol_info in exchange_info["symbols"]:
        symbol = symbol_info["symbol"]
        if symbol in moedas:
            for filtro in symbol_info["filters"]:
                if filtro["filterType"] == "LOT_SIZE":
                    # Calcula o número de casas decimais com base no stepSize
                    step_size = float(filtro["stepSize"])
                    casas_decimais[symbol] = abs(
                        Decimal(str(step_size)).as_tuple().exponent
                    )

    return casas_decimais


# Lista de moedas que você quer descobrir o número de casas decimais
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
casas_decimais_por_moeda = obter_casas_decimais_para_moedas(client, moedas)

# Exibir o resultado
for moeda, casas_decimais in casas_decimais_por_moeda.items():
    print(f"Moeda: {moeda}, Casas Decimais: {casas_decimais}")

# Salvar o resultado em um arquivo (opcional)
with open("casas_decimais_moedas.txt", "w") as f:
    for moeda, casas_decimais in casas_decimais_por_moeda.items():
        f.write(f"Moeda: {moeda}, Casas Decimais: {casas_decimais}\n")
