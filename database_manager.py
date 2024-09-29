import logging
import sqlite3

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
                    quantidade,
                    preco,
                    valor_total,
                    taxa,
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
                valor_compras,
                valor_vendas,
                taxa_compra,
                ganhos,
                porcentagem,
                taxa_venda,
            ),
        )
        self.conn.commit()

    def atualizar_resumo_financeiro(
        self, valor_inicial, valor_atual, porcentagem_geral
    ):
        """
        Atualiza a tabela com o resumo financeiro geral.
        """
        query = """
        UPDATE resumo_financeiro
        SET valor_atual = ?, porcentagem_geral = ?
        WHERE valor_inicial = ?
        """
        self.cursor.execute(query, (valor_atual, porcentagem_geral, valor_inicial))
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
