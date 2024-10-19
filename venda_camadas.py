import logging
from binance.client import Client

logger = logging.getLogger(__name__)


class VendaExecutorCamadas:
    def __init__(self, client: Client, db_manager):
        self.client = client
        self.db_manager = db_manager

    def executar_venda_camadas(self, symbol: str, quantidade_total: float):
        """
        Executa uma venda em camadas (30%, 40%, 30%).
        """
        try:
            # Dividir a quantidade total em camadas
            venda_inicial = quantidade_total * 0.30
            venda_intermediaria = quantidade_total * 0.40
            venda_final = quantidade_total * 0.30

            # Executar as vendas parciais
            self.executar_venda(symbol, venda_inicial)
            self.executar_venda(symbol, venda_intermediaria)

            # Configurar trailing stop para a venda final
            self.configurar_trailing_stop(symbol, venda_final)

        except Exception as e:
            logger.error(f"Erro ao executar venda em camadas para {symbol}: {e}")

    def executar_venda(self, symbol: str, quantidade: float):
        """
        Executa uma venda de uma parte da posição no mercado.
        """
        try:
            ordem = self.client.order_market_sell(
                symbol=symbol, quantity=quantidade, recvWindow=60000
            )
            preco_venda = float(ordem["fills"][0]["price"])
            taxa = float(ordem["fills"][0]["commission"])

            # Registra a transação no banco
            self.db_manager.registrar_transacao(
                simbolo=symbol,
                tipo="VENDA",
                quantidade=quantidade,
                preco=preco_venda,
                valor_total=preco_venda * quantidade,
                taxa=taxa,
                indicador_uso="Venda Camadas",  # Indicador que identifica o tipo de venda
                contexto_operacao="Venda parcial por camadas",
                risco_assumido=0.3,  # Exemplo
            )

            logger.info(f"Venda de {quantidade} {symbol} executada a {preco_venda}.")
            return preco_venda, taxa
        except Exception as e:
            logger.error(f"Erro ao executar venda de {symbol}: {e}")

    def configurar_trailing_stop(
        self, symbol: str, quantidade: float, trailing_stop_percent: float = 2.0
    ):
        """
        Configura um trailing stop para a última parte da venda.
        """
        try:
            # Obter o preço atual do ativo
            preco_atual = float(self.client.get_symbol_ticker(symbol=symbol)["price"])

            # Calcular o preço do stop loss baseado no percentual de trailing stop
            stop_loss_price = round(preco_atual * (1 - trailing_stop_percent / 100), 2)

            # Criar a ordem de stop loss
            ordem_stop_loss = self.client.create_order(
                symbol=symbol,
                side="SELL",
                type="STOP_LOSS_LIMIT",
                quantity=quantidade,
                price=str(stop_loss_price),
                stopPrice=str(stop_loss_price),
                timeInForce="GTC",
                recvWindow=60000,
            )

            logger.info(f"Trailing stop configurado para {symbol} a {stop_loss_price}.")
        except Exception as e:
            logger.error(f"Erro ao configurar trailing stop para {symbol}: {e}")
