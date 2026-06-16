import os
from dotenv import load_dotenv
from openai import OpenAI
import json

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Configurações
API_KEY = os.getenv("API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
debug = os.getenv("DEBUG")

print(API_KEY)
print(OPENAI_MODEL)
print(debug)

SIMULATED_LEADS = [
    {
        "name": "CARLOS ALBERTO DE SOUZA",
        "title": "Gerente de Compras",
        "company_size": "Mais de 500 funcionários",
        "challenges": "Preciso gerar leads qualificados sem perder tempo com curiosos.",

