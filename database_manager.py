import logging
import sqlite3
from decimal import Decimal

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_name: str = "trades.db"):
        self.db_name = db_name
        self._conectar()

    def _conectar(self):
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()
        self.criar_tabela_transacoes()
        self.criar_tabela_ganhos()
        self.criar_tabela_resumo()
        self.criar_tabela_stop_loss()

    def criar_tabela_transacoes(self):
        with self.conn:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS transacoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_hora TEXT,
                    simbolo TEXT,
                    tipo TEXT,
                    quantidade REAL,
                    preco REAL,
                    valor_total REAL,
                    taxa REAL,
                    vendido INTEGER DEFAULT 0
                )
            """
            )

    def criar_tabela_ganhos(self):
        with self.conn:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ganhos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_hora TEXT, 
                    simbolo TEXT, 
                    valor_compras REAL, 
                    valor_vendas REAL, 
                    taxa_compra REAL, 
                    ganhos REAL, 
                    porcentagem REAL,
                    taxa_venda REAL
                )
            """
            )

    def criar_tabela_resumo(self):
        with self.conn:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS resumo_financeiro (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    valor_inicial REAL,
                    valor_atual REAL,
                    porcentagem_geral REAL
                )
            """
            )

    def registrar_transacao(
        self,
        data_hora: str,
        simbolo: str,
        tipo: str,
        quantidade: float,
        preco: float,
        valor_total: float,
        taxa: float,
        vendido,
    ):

        quantidade = Decimal(str(quantidade))
        preco = Decimal(str(preco))
        valor_total = Decimal(str(valor_total))
        taxa = Decimal(str(taxa))

        with self.conn:
            self.cursor.execute(
                """
                INSERT INTO transacoes (data_hora, simbolo, tipo, quantidade, preco, valor_total, taxa, vendido)
                VALUES (?, ?, ?, ?, ?, ?,?,?)
            """,
                (
                    data_hora,
                    simbolo,
                    tipo,
                    float(quantidade),
                    float(preco),
                    float(valor_total),
                    float(taxa),
                    vendido,
                ),
            )
            logger.info(
                f"Transação registrada: {tipo} de {quantidade} {simbolo} a {preco} USDT"
            )

    def fechar_conexao(self):
        self.conn.close()
        logger.info("Conexão com o banco de dados fechada.")

    def registrar_ganhos(
        self,
        data_hora,
        simbolo,
        valor_compras,
        valor_vendas,
        taxa_compra,
        ganhos,
        porcentagem,
        taxa_venda,
    ):

        valor_compras = Decimal(str(valor_compras))
        valor_vendas = Decimal(str(valor_vendas))
        taxa_compra = Decimal(str(taxa_compra))
        ganhos = Decimal(str(ganhos))
        porcentagem = Decimal(str(porcentagem))
        taxa_venda = Decimal(str(taxa_venda))

        """
        Registra os ganhos após uma venda.
        """
        query = """
        INSERT INTO ganhos (data_hora, simbolo, valor_compras, valor_vendas, taxa_compra, ganhos, porcentagem, taxa_venda)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.cursor.execute(
            query,
            (
                data_hora,
                simbolo,
                float(valor_compras),
                float(valor_vendas),
                float(taxa_compra),
                float(ganhos),
                float(porcentagem),
                float(taxa_venda),
            ),
        )
        self.conn.commit()

    def atualizar_resumo_financeiro(
        self, valor_inicial, valor_atual, porcentagem_geral
    ):

        valor_atual = Decimal(str(valor_atual))
        valor_inicial = Decimal(str(valor_inicial))
        porcentagem_geral = Decimal(str(porcentagem_geral))

        """
        Atualiza a tabela com o resumo financeiro geral.
        """
        query = """
        UPDATE resumo_financeiro
        SET valor_atual = ?, porcentagem_geral = ?
        WHERE valor_inicial = ?
        """
        self.cursor.execute(
            query, (float(valor_atual), float(porcentagem_geral), float(valor_inicial))
        )
        self.conn.commit()

    def atualizar_compras(self, moeda):
        query = """
        UPDATE transacoes
        SET vendido = 1
        WHERE simbolo = ? AND tipo = 'COMPRA'
        """
        self.cursor.execute(query, (moeda,))
        self.conn.commit()

    def obter_transacoes(self, simbolo: str, tipo: str = None):
        """
        Obtém todas as transações de um símbolo específico.
        O tipo de transação pode ser "COMPRA" ou "VENDA", se fornecido.
        """
        query = "SELECT * FROM transacoes WHERE simbolo = ? AND vendido = 0"
        params = [simbolo]

        if tipo:
            query += " AND tipo = ?"
            params.append(tipo)

        self.cursor.execute(query, params)
        transacoes = self.cursor.fetchall()

        # Transformar resultado em uma lista de dicionários para facilitar o acesso
        lista_transacoes = [
            {
                "data_hora": transacao[1],
                "simbolo": transacao[2],
                "tipo": transacao[3],
                "quantidade": transacao[4],
                "preco": transacao[5],
                "valor_total": transacao[6],
                "taxa": transacao[7],
            }
            for transacao in transacoes
        ]

        return lista_transacoes

    def obter_transacoes_totais(self, simbolo: str, tipo: str = None):
        """
        Obtém todas as transações de um símbolo específico.
        O tipo de transação pode ser "COMPRA" ou "VENDA", se fornecido.
        """
        query = "SELECT SUM(preco * quantidade) / SUM(quantidade) as preco_medio, sum(quantidade) as quantidade_total, sum(taxa) as taxa_total FROM transacoes WHERE simbolo = ? AND vendido = 0"
        params = [simbolo]

        if tipo:
            query += " AND tipo = ?"
            params.append(tipo)

        self.cursor.execute(query, params)
        transacoes = self.cursor.fetchone()

        if transacoes:
            return transacoes[0], transacoes[1], transacoes[2]

        return 0.0, 0.0, 0.0

    def criar_tabela_stop_loss(self):
        with self.conn:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS stop_loss (
                    simbolo TEXT PRIMARY KEY,
                    stop_loss REAL,
                    preco_maximo REAL
                )
                """
            )

    def salvar_stop_loss(self, simbolo: str, stop_loss: float, preco_maximo: float):

        stop_loss = Decimal(str(stop_loss))
        preco_maximo = Decimal(str(preco_maximo))

        with self.conn:
            self.cursor.execute(
                """
                INSERT OR REPLACE INTO stop_loss (simbolo, stop_loss, preco_maximo)
                VALUES (?, ?, ?)
                """,
                (simbolo, float(stop_loss), float(preco_maximo)),
            )

    def deleta_stop_loss(self, simbolo: str):
        with self.conn:
            self.cursor.execute(
                """
                DELETE FROM stop_loss WHERE simbolo = ?
                """,
                (simbolo,),
            )

    def obter_stop_loss(self, simbolo: str):
        self.cursor.execute(
            "SELECT stop_loss, preco_maximo FROM stop_loss WHERE simbolo = ?",
            (simbolo,),
        )
        resultado = self.cursor.fetchone()
        if resultado:
            return resultado[0], resultado[1]
        return None, None

    def obter_valor_inicial(self):
        self.cursor.execute("SELECT valor_inicial FROM resumo_financeiro")
        resultado = self.cursor.fetchone()
        if resultado:
            return resultado[0]
        return None

    def obter_valor_atual(self):
        self.cursor.execute("SELECT valor_atual FROM resumo_financeiro")
        resultado = self.cursor.fetchone()
        if resultado:
            return resultado[0]
        return None

    def obter_valor_atual_lucro(self):
        self.cursor.execute(
            "SELECT sum(ganhos) + sum(valor_compras) - sum(valor_vendas) FROM ganhos"
        )
        resultado = self.cursor.fetchone()
        if resultado:
            return resultado[0]
        return None
