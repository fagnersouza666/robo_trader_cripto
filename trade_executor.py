import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
import traceback

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(self, client: Client):
        self.client = client

    def executar_compra(
        self, symbol: str, quantidade: float, stop_loss: float, take_profit: float
    ):
        try:
            ordem = self.client.order_market_buy(symbol=symbol, quantity=quantidade)
            logger.info(f"Ordem de compra executada: {ordem}")
            preco_compra = float(ordem["fills"][0]["price"])
            self._configurar_stop_loss(symbol, quantidade, preco_compra, stop_loss)
            return preco_compra
        except BinanceAPIException as e:
            logger.error(f"Erro ao executar compra: {e}")
            return None

    def executar_venda(self, symbol: str, quantidade: float):
        try:
            ordem = self.client.order_market_sell(symbol=symbol, quantity=quantidade)
            logger.info(f"Ordem de venda executada: {ordem}")
            return float(ordem["fills"][0]["price"])
        except BinanceAPIException as e:
            logger.error(f"Erro ao executar venda: {e}")
            return None

    def _get_lot_size_and_min_notional(self, symbol: str):
        """Obtém o tamanho mínimo, máximo e incremento do lote e o valor mínimo de notional para o símbolo."""
        exchange_info = self.client.get_exchange_info()
        lot_size = None
        min_notional = None

        for s in exchange_info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:

                    if f["filterType"] == "LOT_SIZE":
                        lot_size = {
                            "min_qty": float(f["minQty"]),
                            "max_qty": float(f["maxQty"]),
                            "step_size": float(f["stepSize"]),
                        }
                    if f["filterType"] == "NOTIONAL":
                        min_notional = float(f["minNotional"])

                # Verifica se obteve tanto o LOT_SIZE quanto o MIN_NOTIONAL
                if lot_size is None:
                    raise ValueError(f"LOT_SIZE não encontrado para o símbolo {symbol}")
                if min_notional is None:
                    logger.warning(
                        f"MIN_NOTIONAL não encontrado para o símbolo {symbol}, definindo valor padrão."
                    )
                    min_notional = 0  # Ou outro valor padrão que faça sentido

                return lot_size, min_notional

        raise ValueError(
            f"Não foi possível encontrar informações para o símbolo: {symbol}"
        )

    def _ajustar_quantidade_venda(self, symbol: str, quantidade: float):
        """
        Ajusta a quantidade para atender ao step size do símbolo.
        """
        try:
            logging.info(f"quantidade antes: {quantidade}")

            # Obtém as informações de trading do símbolo
            info = self.client.get_symbol_info(symbol)
            if not info:
                raise ValueError(f"Informações do símbolo {symbol} não encontradas.")

            # Obtém o filtro de tamanho de lote (LOT_SIZE)
            filters = {f["filterType"]: f for f in info["filters"]}
            lot_size = filters.get("LOT_SIZE")

            if not lot_size:
                raise ValueError(
                    f"Filtro LOT_SIZE não encontrado para o símbolo {symbol}."
                )

            # Step size
            step_size = float(lot_size["stepSize"])

            # Ajuste a quantidade com base no step size
            quantidade_ajustada = round(quantidade // step_size * step_size, 8)

            # Formatar a quantidade para garantir que não tenha mais casas decimais que o necessário
            quantidade_ajustada_str = (
                "{:0.8f}".format(quantidade_ajustada).rstrip("0").rstrip(".")
            )

            logging.info(f"quantidade ajustada: {quantidade_ajustada_str}")

            return float(quantidade_ajustada_str)

        except Exception as e:
            logger.error(f"Erro ao ajustar quantidade para {symbol}: {e}")
            return 0

    def _ajustar_quantidade(self, quantidade: float, step_size: float):
        """Ajusta a quantidade para o incremento permitido pelo filtro."""
        quantidade = float(quantidade)
        step_size = float(step_size)

        # Calcula a quantidade ajustada
        quantidade_ajustada = round(quantidade - (quantidade % step_size), 8)

        # A Binance espera um formato específico para a quantidade, asseguramos isso aqui
        quantidade_ajustada_str = (
            "{:0.8f}".format(quantidade_ajustada).rstrip("0").rstrip(".")
        )

        return quantidade_ajustada_str

    def verificar_saldo(self, symbol="USDT"):
        logging.info(f"Verificando saldo disponível em {symbol}...")
        saldo_base = self.client.get_asset_balance(asset=symbol)
        saldo_disponivel = float(saldo_base["free"])

        logger.info(f"Saldo disponível em USDT: {saldo_disponivel}")
        return saldo_disponivel

    def verificar_saldo_moedas(self, symbol):
        try:
            logging.info(f"Verificando saldo disponível em {symbol}...")

            # Obtém todas as informações da conta, incluindo saldos de todos os ativos
            conta = self.client.get_account()

            # Filtra a lista de saldos para encontrar o ativo específico (symbol)
            for asset in conta["balances"]:
                if asset["asset"] == symbol:
                    saldo_disponivel = float(asset["free"])
                    logger.info(f"Saldo disponível em {symbol}: {saldo_disponivel}")
                    return saldo_disponivel

            logger.error(f"Ativo {symbol} não encontrado na conta.")
            return 0

        except Exception as e:
            logger.error(f"Erro ao verificar saldo de {symbol}: {e}")
            return 0

    def executar_ordem(
        self,
        symbol: str,
        quantidade: float,
        ordem_tipo: str,
        venda_parcial: bool = False,
        moeda_venda: str = None,
    ):

        # Obtém as restrições de LOT_SIZE e MIN_NOTIONAL para o par
        lot_size, min_notional = self._get_lot_size_and_min_notional(symbol)

        if ordem_tipo == "buy":
            # Verifica e ajusta a quantidade de acordo com o step_size
            quantidade_ajustada_str = self._ajustar_quantidade(
                quantidade, lot_size["step_size"]
            )

            # Calcula o valor da ordem (preço * quantidade)
            preco_atual = float(self.client.get_symbol_ticker(symbol=symbol)["price"])
            quantidade_ajustada = float(quantidade_ajustada_str)
            notional = preco_atual * quantidade_ajustada

            # Verifica se o valor (notional) está acima do mínimo exigido
            if notional < min_notional:
                logger.error(
                    f"Valor da ordem ({notional}) é menor que o valor mínimo permitido ({min_notional}) para {symbol}."
                )

                # Forçar a quantidade ajustada para garantir que o notional seja maior que o mínimo
                quantidade_ajustada = (
                    min_notional / preco_atual
                ) * 1.2  # Adiciona uma margem de 20%

                quantidade_ajustada_str = "{:f}".format(quantidade_ajustada)
                quantidade_ajustada_str = self._ajustar_quantidade(
                    quantidade_ajustada_str, lot_size["step_size"]
                )

                # Recalcular o notional após o ajuste de quantidade
                notional = preco_atual * float(quantidade_ajustada_str)

                if notional < min_notional:
                    logger.error(
                        f"Mesmo após ajuste, o valor ({notional}) é menor que o mínimo exigido ({min_notional}) para {symbol}."
                    )
                    return None

            # Verifique se a quantidade ajustada está acima de minQty
            if float(quantidade_ajustada_str) < lot_size["min_qty"]:
                logger.error(
                    f"Quantidade ajustada ({quantidade_ajustada_str}) está abaixo do tamanho mínimo de lote permitido ({lot_size['min_qty']}) para {symbol}."
                )
                quantidade_ajustada_str = "{:0.8f}".format(lot_size["min_qty"])
                logger.info(
                    f"Quantidade ajustada para o mínimo de lote permitido: {quantidade_ajustada_str}"
                )

            saldo_disponivel = self.verificar_saldo("USDT")

            # Se o notional ajustado for maior que o saldo disponível, ajuste a quantidade novamente
            if notional > saldo_disponivel:
                # Ajustar a quantidade com base no saldo disponível
                quantidade_ajustada = saldo_disponivel / preco_atual * 1.001
                quantidade_ajustada_str = self._ajustar_quantidade(
                    quantidade_ajustada, lot_size["step_size"]
                )
                notional = preco_atual * float(quantidade_ajustada_str)

                logger.info(
                    f"Quantidade ajustada para o saldo disponível: {quantidade_ajustada_str}, Notional: {notional}"
                )

            # Verificar se o notional após o ajuste ainda é inferior ao mínimo permitido
            if notional < min_notional:
                logger.error(
                    f"Saldo insuficiente para executar a ordem. Notional ({notional}) é menor que o mínimo permitido ({min_notional})."
                )
                return None

            # Execução da ordem após as verificações

            resultado = self._executar_ordem_buy(symbol, quantidade_ajustada_str, 2, 4)

            logger.info(f"Resultado da execução da ordem de compra: {resultado}")

            return resultado

        elif ordem_tipo == "sell":

            preco_atual = float(self.client.get_symbol_ticker(symbol=symbol)["price"])

            # Se for uma venda parcial, ajusta a quantidade para 50%
            if venda_parcial:
                quantidade = quantidade * 0.5

            quantidade_maxima = self.verificar_saldo_moedas(moeda_venda)

            if quantidade_maxima == 0:
                quantidade_maxima = quantidade

            if quantidade > quantidade_maxima:
                quantidade = quantidade_maxima

            logging.info(f"Quantidade1: {quantidade}")

            quantidade = self._ajustar_quantidade_venda(symbol, quantidade)

            logging.info(f"Quantidade2: {quantidade}")

            quantidade = "{:f}".format(quantidade)

            logging.info(f"Quantidade3: {quantidade}")

            retorno = self._executar_ordem_sell(symbol, quantidade, 0, 0)

            logger.info(f"Resultado da execução da ordem de venda: {retorno}")

            return retorno

        else:
            logger.error(f"Tipo de ordem inválido: {ordem_tipo}")
            return None

    def _executar_ordem_buy(
        self,
        symbol: str,
        quantidade: float,
        stop_loss_percent: float,
        take_profit_percent: float,
    ):
        try:

            print(
                f"Executando ordem de compra para {symbol} com quantidade {quantidade}"
            )
            # Executa a ordem de compra no mercado
            ordem_compra = self.client.order_market_buy(
                symbol=symbol, quantity=quantidade
            )
            logger.info(f"Ordem de compra executada para {symbol}: {ordem_compra}")

            # Obtém o preço de compra
            preco_compra = float(ordem_compra["fills"][0]["price"])
            taxaM = float(ordem_compra["fills"][0]["commission"])

            taxa = taxaM * preco_compra
            # Configura stop loss e take profit
            self._configurar_stop_loss(
                symbol, quantidade, preco_compra, stop_loss_percent
            )

            return preco_compra, taxa

        except BinanceAPIException as e:
            logger.error(f"Erro ao executar ordem de compra: {e}")
            traceback.print_exc()
            return None

    def _executar_ordem_sell(
        self,
        symbol: str,
        quantidade: float,
        stop_loss_percent: float,
        take_profit_percent: float,
    ):
        try:

            logging.info(
                f"Executando ordem de venda para {symbol} com quantidade {quantidade}"
            )

            # Executa a ordem de venda no mercado
            ordem_venda = self.client.order_market_sell(
                symbol=symbol, quantity=quantidade
            )
            logger.info(f"Ordem de venda executada para {symbol}: {ordem_venda}")

            # Obtém o preço de venda
            preco_venda = float(ordem_venda["fills"][0]["price"])

            taxaM = float(preco_venda["fills"][0]["commission"])
            taxa = taxaM * preco_venda

            if taxa is None:
                taxa = 0.0

            return preco_venda, taxa

        except BinanceAPIException as e:
            logger.error(f"Erro ao executar ordem de venda: {e}")
            return None

    def _configurar_stop_loss(
        self, symbol: str, quantidade: float, preco: float, stop_loss_percent: float
    ):
        saldo_disponivel = self.verificar_saldo(
            "USDT"
        )  # Verifique o saldo disponível em USDT

        # Calcular os preços de Stop Loss e Take Profit
        stop_loss_price = round(preco * (1 - stop_loss_percent / 100), 2)

        try:
            # Ajustar a quantidade com o step_size correto
            lot_size, _ = self._get_lot_size_and_min_notional(symbol)
            quantidade_ajustada_str = self._ajustar_quantidade(
                quantidade, lot_size["step_size"]
            )

            # Verifique se há saldo suficiente para configurar a ordem de Stop Loss
            if saldo_disponivel < (float(quantidade_ajustada_str) * stop_loss_price):
                logger.error(
                    f"Saldo insuficiente para configurar o Stop Loss para {symbol}. Saldo disponível: {saldo_disponivel}, necessário: {float(quantidade_ajustada_str) * stop_loss_price}"
                )
                return None

            # Cria a ordem de Stop Loss com a quantidade ajustada
            ordem_stop_loss = self.client.create_order(
                symbol=symbol,
                side="SELL",
                type="STOP_LOSS_LIMIT",
                quantity=quantidade_ajustada_str,  # Usar a quantidade ajustada
                price=stop_loss_price,
                stopPrice=stop_loss_price,
                timeInForce="GTC",
            )
            logger.info(
                f"Ordem de Stop Loss configurada para {symbol} ao preço: {stop_loss_price}"
            )

        except BinanceAPIException as e:
            logger.error(f"Erro ao configurar Stop Loss e Take Profit: {e}")
