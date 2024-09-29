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

    def enviar_mensagem(
        self, mensagem: str, parse_mode: str = "Markdown", tentativas=5
    ):
        payload = {"chat_id": self.chat_id, "text": mensagem, "parse_mode": parse_mode}

        for i in range(tentativas):
            try:
                response = requests.post(self.api_url, data=payload)
                response.raise_for_status()
                logger.info("Mensagem enviada com sucesso para o Telegram.")
                break
            except requests.ConnectionError as e:
                logger.error(
                    f"Erro de conexão ao enviar mensagem para o Telegram: {e}. Tentando novamente ({i+1}/{tentativas})"
                )
                if i == tentativas - 1:
                    logger.error(
                        "Falha definitiva no envio da mensagem após várias tentativas."
                    )
            except requests.Timeout as e:
                logger.error(
                    f"Tempo de espera excedido para o Telegram: {e}. Tentando novamente ({i+1}/{tentativas})"
                )
            except requests.RequestException as e:
                logger.error(f"Erro ao enviar mensagem para o Telegram: {e}")
                break  # Não tenta novamente para outros tipos de erros

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
