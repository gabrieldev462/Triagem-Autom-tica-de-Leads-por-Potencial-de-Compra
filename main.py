high_priority_leads = []
"""Main do projeto Smart Lead Triage.

Suporte a dois provedores de LLM configuráveis via variáveis de ambiente:
- OpenAI (SDK) quando `PROVIDER=openai` (padrão)
- Grok/xAI via requisição HTTP quando `PROVIDER=grok`

Este arquivo faz a triagem de leads simulados, pede a classificação à IA e salva
os leads de alta prioridade em `high_priority_leads.json`.
"""

import os
import re
import json
from typing import Dict

import requests
from dotenv import load_dotenv

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# Load environment
load_dotenv()

# Config
API_KEY = os.getenv("API_KEY")
PROVIDER = os.getenv("PROVIDER", "openai").lower()
if PROVIDER == "grok":
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "openai/gpt-oss-20b")
else:
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GROK_API_KEY = os.getenv("GROK_API_KEY")
GROK_API_URL = os.getenv("GROK_API_URL", "https://api.groq.com/openai/v1/chat/completions")

openai_client = None
if PROVIDER == "openai":
    if not API_KEY:
        raise ValueError("API_KEY não encontrada. Defina API_KEY no .env para usar OpenAI.")
    if OpenAI is None:
        raise ImportError("openai SDK não encontrado. Instale com 'pip install openai'.")
    openai_client = OpenAI(api_key=API_KEY)


SIMULATED_LEADS = [
    {
        "name": "CARLOS ALBERTO DE SOUZA",
        "title": "Gerente de Compras",
        "company_size": "Mais de 500",
        "challenge": "Preciso gerar leads qualificados sem perder tempo com curiosos irrelevantes.",
    },
    {
        "name": "MARIA FERNANDA LIMA",
        "title": "Diretora de Marketing",
        "company_size": "101-500",
        "challenge": "Tenho dificuldade em identificar quais leads têm maior probabilidade de conversão.",
    },
    {
        "name": "JOÃO PEDRO ALMEIDA",
        "title": "CEO",
        "company_size": "1-50",
        "challenge": "Quero otimizar meu processo de vendas, mas não sei por onde começar.",
    },
    {
        "name": "ANA CAROLINA RODRIGUES",
        "title": "Coordenadora de Vendas",
        "company_size": "101-500",
        "challenge": "Preciso de uma maneira eficiente de priorizar meus leads para aumentar as taxas de conversão.",
    },
    {
        "name": "PEDRO HENRIQUE COSTA",
        "title": "Analista de Marketing",
        "company_size": "Mais de 500",
        "challenge": "Tenho dificuldade em segmentar meus leads de forma eficaz para campanhas direcionadas.",
    },
    {
        "name": "LARISSA MENDES SILVA",
        "title": "Gerente de Vendas",
        "company_size": "101-500",
        "challenge": "Quero melhorar a eficiência da minha equipe de vendas e identificar os leads mais promissores.",
    },
]


def extract_json(text: str) -> Dict[str, str]:
    # tenta extrair o primeiro objeto JSON do texto
    if not text:
        raise ValueError("Resposta vazia da API")

    m = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = text
    if m:
        candidate = m.group(0)

    # corrigir aspas simples
    candidate = candidate.strip()
    candidate = candidate.replace("\n", " ")
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # tentativa de limpeza: trocar aspas simples por duplas
        candidate2 = candidate.replace("'", '"')
        data = json.loads(candidate2)

    return {
        "prioridade": data.get("prioridade") or data.get("priority") or data.get("prioridade", "NÃO INFORMADO"),
        "pain_point": data.get("pain_point") or data.get("pain") or data.get("dor") or "NÃO INFORMADO",
        "reason": data.get("reason") or data.get("motivo") or "NÃO INFORMADO",
    }


def build_prompt(lead: Dict[str, str]) -> str:
    return (
        "Você é um gerente de vendas B2B. Analise o lead e classifique sua prioridade com base no cargo, tamanho da empresa e urgência do desafio. "
        "Responda APENAS com JSON válido contendo as chaves: prioridade (Alta, Média, Baixa), pain_point (uma frase curta) e reason (explicação curta)." + "\n\n"
        f"Nome: {lead['name']}\n"
        f"Cargo: {lead['title']}\n"
        f"Tamanho da empresa: {lead['company_size']}\n"
        f"Desafio: {lead['challenge']}\n"
    )


def call_grok_api(prompt_text: str) -> str:
    if not GROK_API_KEY:
        raise ValueError("GROK_API_KEY não definida no .env")

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "Responda apenas com JSON válido, sem texto adicional."},
            {"role": "user", "content": prompt_text},
        ],
        "temperature": 0.2,
    }

    resp = requests.post(GROK_API_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    j = resp.json()

    # Tentar extrair o conteúdo conforme diferentes formatos
    try:
        return j["choices"][0]["message"]["content"]
    except Exception:
        # fallback para resposta direta
        return j.get("output") or json.dumps(j)


def call_openai_api(prompt_text: str) -> str:
    if openai_client is None:
        raise ValueError("Cliente OpenAI não inicializado")

    resp = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "Responda apenas com JSON válido, sem texto adicional."},
            {"role": "user", "content": prompt_text},
        ],
        temperature=0.2,
    )

    # compatibilidade com formatos
    try:
        return resp.choices[0].message.content
    except Exception:
        # tentar outros caminhos
        j = resp if isinstance(resp, dict) else resp
        return json.dumps(j)


def classify_lead_with_ai(lead: Dict[str, str]) -> str:
    prompt = build_prompt(lead)
    if PROVIDER == "grok":
        return call_grok_api(prompt)
    else:
        return call_openai_api(prompt)


def main() -> None:
    high_priority = []

    for lead in SIMULATED_LEADS:
        try:
            raw = classify_lead_with_ai(lead)
            parsed = extract_json(raw)

            print("─" * 60)
            print(f"Lead: {lead['name']}")
            print(f"Prioridade: {parsed['prioridade']}")
            print(f"Dor: {parsed['pain_point']}")
            print(f"Motivo: {parsed['reason']}")

            if parsed["prioridade"].strip().lower() in ("alta", "alto potencial", "alto"):
                high_priority.append({**lead, **parsed})

        except Exception as e:
            print(f"Erro ao processar {lead['name']}: {e}")

    # Salvar leads de alta prioridade
    with open("high_priority_leads.json", "w", encoding="utf-8") as f:
        json.dump(high_priority, f, ensure_ascii=False, indent=2)

    print(f"\nArquivo salvo com {len(high_priority)} leads de alta prioridade: high_priority_leads.json")


if __name__ == "__main__":
    main()
