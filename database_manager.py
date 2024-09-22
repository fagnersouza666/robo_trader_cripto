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
                    valor_total REAL
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
    ):
        with self.conn:
            self.cursor.execute(
                """
                INSERT INTO transacoes (data_hora, simbolo, tipo, quantidade, preco, valor_total)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (data_hora, simbolo, tipo, quantidade, preco, valor_total),
            )
            logger.info(
                f"Transação registrada: {tipo} de {quantidade} {simbolo} a {preco} USDT"
            )

    def fechar_conexao(self):
        self.conn.close()
        logger.info("Conexão com o banco de dados fechada.")
