import logging
import requests
import openai

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    def __init__(self, openai_api_key: str, cryptocompare_api_key: str):
        openai.api_key = openai_api_key
        self.cryptocompare_api_key = cryptocompare_api_key

    def analisar_sentimento(self, symbol: str) -> str:
        try:
            noticias = self._coletar_noticias(symbol)
            return self._analisar_texto_noticias(noticias, symbol)
        except Exception as e:
            logger.error(f"[{symbol}] Erro ao analisar sentimento: {e}")
            return "Neutro"

    def _coletar_noticias(self, symbol: str) -> list:
        params = {
            "categories": symbol,
            "lang": "EN",
            "api_key": self.cryptocompare_api_key,
        }
        response = requests.get(
            "https://min-api.cryptocompare.com/data/v2/news/", params=params
        )
        response.raise_for_status()
        return response.json().get("Data", [])

    def _analisar_texto_noticias(self, artigos: list, symbol: str) -> str:
        if not artigos:
            return "Neutro"

        textos = " ".join([artigo["title"] for artigo in artigos[:5]])
        prompt = f"Analise o seguinte texto e determine o sentimento geral sobre {symbol}. E responda somente: Positivo, Negativo ou Neutro, conforme sua análise quanto a essa criptomoeda. Textos: {textos}"
        resposta = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            n=1,
            stop=None,
            temperature=0.5,
        )

        return resposta.choices[0].message.content.strip()
