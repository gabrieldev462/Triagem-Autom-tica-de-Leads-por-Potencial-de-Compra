high_priority_leads = []
"""Main do projeto Smart Lead Triage.

Suporte a dois provedores de LLM configuráveis via variáveis de ambiente:
- OpenAI (SDK) quando `PROVIDER=openai` (padrão)
- Grok/xAI via requisição HTTP quando `PROVIDER=grok`

Este arquivo faz a triagem de leads simulados, pede a classificação à IA e salva
os leads de alta prioridade em `high_priority_leads.json`.
"""
import argparse
import os
import re
import json
from typing import Dict, List
import csv
from pathlib import Path
import requests
from dotenv import load_dotenv
import time
import logging
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
try:
    from prometheus_client import start_http_server, Counter, Histogram, Summary
except Exception:
    start_http_server = None
    Counter = None
    Histogram = None
    Summary = None
try:
    from pythonjsonlogger import jsonlogger
except Exception:
    jsonlogger = None
from threading import Lock

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

def get_openai_client():
    global openai_client
    if openai_client is not None:
        return openai_client

    if not API_KEY:
        raise ValueError("API_KEY não encontrada. Defina API_KEY no .env para usar OpenAI.")
    if OpenAI is None:
        raise ImportError("openai SDK não encontrado. Instale com 'pip install openai'.")
    openai_client = OpenAI(api_key=API_KEY)
    return openai_client


# Simple file-backed cache for prompt -> response
CACHE_FILE = Path(".ai_cache.json")


def _prompt_key(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def load_cache() -> Dict[str, str]:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache: Dict[str, str]) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_cached_response(prompt: str) -> str | None:
    cache = load_cache()
    return cache.get(_prompt_key(prompt))


def set_cached_response(prompt: str, response: str) -> None:
    cache = load_cache()
    cache[_prompt_key(prompt)] = response
    save_cache(cache)


# Simple retry decorator with exponential backoff
def retry(max_attempts: int = 3, backoff: float = 1.0):
    def deco(func):
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    sleep = backoff * (2 ** (attempt - 1))
                    time.sleep(sleep)
        return wrapper
    return deco


# Configure structured JSON logging when available
logger = logging.getLogger("smart-triage")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
if jsonlogger is not None:
    fmt = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    handler.setFormatter(fmt)
else:
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(handler)


# Metrics (thread-safe)
_metrics_lock = Lock()
METRICS = {
    "total_calls": 0,
    "cache_hits": 0,
    "errors": 0,
    "total_time_seconds": 0.0,
    "per_call_times": [],
}


def record_metrics(duration: float = 0.0, cached: bool = False, error: bool = False) -> None:
    with _metrics_lock:
        # count only non-cached calls towards total_calls
        METRICS["total_calls"] += 0 if cached else 1
        if cached:
            METRICS["cache_hits"] += 1
        if error:
            METRICS["errors"] += 1
        METRICS["total_time_seconds"] += float(duration or 0.0)
        METRICS["per_call_times"].append(float(duration or 0.0))
    # update prometheus metrics if available
    try:
        if Counter is not None:
            if cached:
                PROM_CACHE_HITS.inc()
            else:
                PROM_REQUESTS.inc()
            if error:
                PROM_ERRORS.inc()
            if HISTOGRAM is not None:
                PROM_LATENCY.observe(float(duration or 0.0))
            if SUMMARY is not None:
                PROM_SUMMARY.observe(float(duration or 0.0))
    except Exception:
        pass


def dump_metrics(path: str) -> None:
    try:
        with _metrics_lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(METRICS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Não foi possível gravar métricas em {path}: {e}")


# Prometheus metrics objects (created lazily)
PROM_REQUESTS = None
PROM_CACHE_HITS = None
PROM_ERRORS = None
PROM_LATENCY = None
PROM_SUMMARY = None


def start_prometheus_server(port: int = 8000):
    global PROM_REQUESTS, PROM_CACHE_HITS, PROM_ERRORS, PROM_LATENCY, PROM_SUMMARY
    if start_http_server is None:
        logger.warning("prometheus_client não disponível; instalar prometheus_client para expor métricas")
        return
    try:
        PROM_REQUESTS = Counter("smart_trie_requests_total", "Total de chamadas à IA")
        PROM_CACHE_HITS = Counter("smart_trie_cache_hits_total", "Total de cache hits")
        PROM_ERRORS = Counter("smart_trie_errors_total", "Total de erros")
        PROM_LATENCY = Histogram("smart_trie_latency_seconds", "Latência das chamadas à IA")
        PROM_SUMMARY = Summary("smart_trie_latency_summary_seconds", "Resumo de latências")
        start_http_server(port)
        logger.info(f"Prometheus metrics available at :{port}/")
    except Exception as e:
        logger.error(f"Erro ao iniciar servidor Prometheus: {e}")


def load_leads(path: str) -> List[Dict[str, str]]:
    file_path = Path(path)
    if file_path.suffix.lower() == ".csv":
        with open(file_path, "r", encoding="utf-8") as f:
            return [row for row in csv.DictReader(f)]
    elif file_path.suffix.lower() == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        raise ValueError("Apenas .csv ou .json são suportados.")


def parse_args():
    parser = argparse.ArgumentParser(description="Triagem de leads")
    parser.add_argument("--input", "-i", help="Arquivo CSV ou JSON com os leads")
    parser.add_argument("--provider", "-p", choices=["openai", "grok"], help="openai ou grok. Se omitido, usa PROVIDER do .env")
    parser.add_argument("--model", "-m", help="Nome do modelo a usar. Se omitido, usa OPENAI_MODEL do .env")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Número de threads concorrentes para chamadas à IA")
    parser.add_argument("--metrics", action="store_true", help="Gerar arquivo de métricas ao final (metrics.json por padrão)")
    parser.add_argument("--metrics-output", default="metrics.json", help="Caminho do arquivo de saída de métricas")
    parser.add_argument("--prometheus-port", type=int, help="Porta para expor métricas Prometheus (ex: 8000)")
    return parser.parse_args()


def validate_leads(leads: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not isinstance(leads, list) or len(leads) == 0:
        raise ValueError("Nenhum lead encontrado no arquivo de entrada.")

    required_keys = {"name", "title", "company_size", "challenge"}
    for index, lead in enumerate(leads, start=1):
        if not isinstance(lead, dict):
            raise ValueError(f"Lead na posição {index} não é um objeto JSON válido.")
        missing = [key for key in required_keys if not lead.get(key)]
        if missing:
            raise ValueError(
                f"Lead na posição {index} está faltando campos obrigatórios: {', '.join(missing)}"
            )
    return leads


def normalize_priority(priority: str) -> str:
    normalized = priority.strip().lower()
    if normalized in ("alta", "alto potencial", "alto"):
        return "alta"
    if normalized in ("média", "medio", "médio", "média prioridade", "media"):
        return "média"
    return "baixa"


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
    {
        "name": "RAFAEL GOMES PEREIRA",
        "title": "Diretor Comercial",
        "company_size": "Mais de 500",
        "challenge": "Estou buscando uma solução para automatizar a triagem de leads e focar nos mais qualificados.",
    },
    {
        "name": "JULIA SANTOS ALVES",
        "title": "Gerente de Marketing Digital",
        "company_size": "51-100",
        "challenge": "Tenho dificuldade em analisar grandes volumes de leads e identificar os mais relevantes para minhas campanhas.",
    },
    {
        "name": "GUSTAVO LIMA FERREIRA",
        "title": "Coordenador de Vendas",
        "company_size": "101-500",
        "challenge": "Quero otimizar meu funil de vendas, mas não sei como priorizar meus leads de forma eficaz.",
    },
    {
        "name": "MARIA EDUARDA SANTOS",
        "title": "Assistente de Marketing",
        "company_size": "1-50",
        "challenge": "Estou pesquisando ferramentas para entender melhor o mercado e reunir ideias para apresentar futuramente à equipe. Ainda não temos orçamento definido."
    },
    {
        "name": "ANA PAULA SILVA",
        "title": "Analista de Vendas",
        "company_size": "1-50",
        "challenge": "Estou buscando informações sobre novos produtos e serviços para apresentar aos meus clientes potenciais."
    },
    {
        "name": "LUCAS MOURA COSTA",
        "title": "Estagiário de Marketing",
        "company_size": "1-50",
        "challenge": "Quero contribuir com a equipe de marketing, mas ainda não tenho experiência suficiente."
    },
    {
        "name": "FERNANDA RIBEIRO OLIVEIRA",
        "title": "Coordenadora de Atendimento",
        "company_size": "1-50",
        "challenge": "Preciso melhorar a comunicação com os clientes e resolver suas dúvidas de forma mais eficiente."
    },
    {
        "name": "MARCOS ANTONIO LIMA",
        "title": "Consultor de Vendas",
        "company_size": "1-50",
        "challenge": "Estou buscando novos clientes e oportunidades de venda em mercados emergentes."
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


@retry(max_attempts=3, backoff=1.0)
def call_grok_api(prompt_text: str, model_name: str) -> str:
    if not GROK_API_KEY:
        raise ValueError("GROK_API_KEY não definida no .env")

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
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
        return j.get("output") or json.dumps(j)


@retry(max_attempts=3, backoff=1.0)
def call_openai_api(prompt_text: str, model_name: str) -> str:
    client = get_openai_client()

    resp = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "Responda apenas com JSON válido, sem texto adicional."},
            {"role": "user", "content": prompt_text},
        ],
        temperature=0.2,
    )

    try:
        return resp.choices[0].message.content
    except Exception:
        j = resp if isinstance(resp, dict) else resp
        return json.dumps(j)


def classify_lead_with_ai(lead: Dict[str, str], provider: str, model_name: str) -> str:
    prompt = build_prompt(lead)
    start = time.perf_counter()
    try:
        cached = get_cached_response(prompt)
        if cached:
            duration = time.perf_counter() - start
            logger.info(f"Cache hit para lead: {lead.get('name')}")
            record_metrics(duration=duration, cached=True)
            return cached

        if provider == "grok":
            resp = call_grok_api(prompt, model_name)
        else:
            resp = call_openai_api(prompt, model_name)

        duration = time.perf_counter() - start
        try:
            set_cached_response(prompt, resp)
        except Exception:
            pass

        record_metrics(duration=duration, cached=False)
        return resp
    except Exception as e:
        duration = time.perf_counter() - start
        record_metrics(duration=duration, error=True)
        raise


def save_json(filename: str, leads: List[Dict[str, str]]) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)


def main(args=None) -> None:
    if args is None:
        provider = PROVIDER
        model_name = OPENAI_MODEL
        leads = SIMULATED_LEADS
    else:
        provider = args.provider.lower() if args.provider else PROVIDER
        model_name = args.model or OPENAI_MODEL

        if provider not in ("openai", "grok"):
            raise ValueError("Provedor inválido. Use 'openai' ou 'grok'.")

        if args.input:
            leads = validate_leads(load_leads(args.input))
        else:
            leads = SIMULATED_LEADS

    high_priority = []
    medium_priority = []
    low_priority = []

    # start prometheus server if requested
    if args is not None and getattr(args, "prometheus_port", None):
        start_prometheus_server(getattr(args, "prometheus_port"))

    # concurrent processing
    workers = args.workers if args is not None else 4
    logger.info(f"Processando {len(leads)} leads com {workers} workers")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_lead = {ex.submit(classify_lead_with_ai, lead, provider, model_name): lead for lead in leads}
        for fut in as_completed(future_to_lead):
            lead = future_to_lead[fut]
            try:
                raw = fut.result()
                parsed = extract_json(raw)

                logger.info("─" * 60)
                logger.info(f"Lead: {lead['name']}")
                logger.info(f"Prioridade: {parsed['prioridade']}")
                logger.info(f"Dor: {parsed['pain_point']}")
                logger.info(f"Motivo: {parsed['reason']}")

                prioridade = normalize_priority(parsed["prioridade"]) if parsed.get("prioridade") else "baixa"
                if prioridade == "alta":
                    high_priority.append({**lead, **parsed})
                elif prioridade == "média":
                    medium_priority.append({**lead, **parsed})
                else:
                    low_priority.append({**lead, **parsed})

            except Exception as e:
                logger.error(f"Erro ao processar {lead.get('name', 'lead desconhecido')}: {e}")

    save_json("high_priority_leads.json", high_priority)
    save_json("medium_priority_leads.json", medium_priority)
    save_json("low_priority_leads.json", low_priority)

    logger.info(f"\nArquivo salvo com {len(high_priority)} leads de alta prioridade: high_priority_leads.json")
    logger.info(f"Arquivo salvo com {len(medium_priority)} leads de média prioridade: medium_priority_leads.json")
    logger.info(f"Arquivo salvo com {len(low_priority)} leads de baixa prioridade: low_priority_leads.json")

    # gravar métricas se solicitado
    if args is not None and getattr(args, "metrics", False):
        out = getattr(args, "metrics_output", "metrics.json")
        dump_metrics(out)
        logger.info(f"Métricas gravadas em: {out}")

if __name__ == "__main__":
    args = parse_args()
    main(args)
            