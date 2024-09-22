# telegram_notifier_refatorado.py
import logging
import requests
import os

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def enviar_mensagem(self, mensagem: str, parse_mode: str = "Markdown"):
        payload = {"chat_id": self.chat_id, "text": mensagem, "parse_mode": parse_mode}

        try:
            response = requests.post(self.api_url, data=payload)
            response.raise_for_status()
            logger.info("Mensagem enviada com sucesso para o Telegram.")
        except requests.RequestException as e:
            logger.error(f"Erro ao enviar mensagem para o Telegram: {e}")

    def notificar(
        self,
        tipo: str,
        symbol: str,
        quantidade: float,
        preco: float,
        valor_total: float,
    ):
        if tipo not in ["COMPRA", "VENDA"]:
            raise ValueError("Tipo de transação inválido.")

        icone = "🟢" if tipo == "COMPRA" else "🔴"
        mensagem = (
            f"*{tipo}*\n"
            f"{icone} *Símbolo:* {symbol}\n"
            f"📈 *Quantidade:* {quantidade}\n"
            f"💵 *Preço:* {preco} USDT\n"
            f"💰 *Valor Total:* {valor_total} USDT"
        )
        self.enviar_mensagem(mensagem)
