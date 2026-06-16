<div align="center">

# 🚀 Smart Lead Triage 🤖

<p align="center">
  <b>Automação Inteligente de Marketing & Qualificação de Leads com IA</b>
</p>

---

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![JavaScript](https://img.shields.io/badge/javascript-%23323330.svg?style=for-the-badge&logo=javascript&logoColor=%23F7DF1E)
![OpenAI](https://img.shields.io/badge/OpenAI-412991.svg?style=for-the-badge&logo=OpenAI&logoColor=white)
![Status](https://img.shields.io/badge/Status-MVP%20Pronto-green?style=for-the-badge)

</div>

<br>

## 🎯 O Problema
Em agências de marketing, a **triagem manual de leads** gera gargalos. O time comercial perde tempo com curiosos, enquanto clientes de alto valor esfriam na base por falta de atendimento ágil.

## 💡 A Solução
O **Smart Lead Triage** automatiza 100% esse fluxo:
1. **Ingere** dados brutos de formulários de marketing.
2. **Usa IA** via API para ler o cargo e a dor do lead em tempo real.
3. **Categoriza** e prioriza os contatos automaticamente, separando as oportunidades quentes.

---

## 🛠️ Como Executar o Projeto

```bash
# 1. Clone o repositório
git clone https://github.com/SEU_USUARIO/smart-lead-triage.git

# 2. Acesse a pasta
cd smart-lead-triage

# 3. Crie um .env com suas chaves
# Para OpenAI:
API_KEY=sua_chave_openai
PROVIDER=openai
OPENAI_MODEL=gpt-4o-mini

# Para Grok/xAI:
# PROVIDER=grok
# GROK_API_KEY=sua_chave_grok
# OPENAI_MODEL=openai/gpt-oss-20b

# 4. Execute a automação
python main.py --input leads.csv
```

### Exemplo de CSV
O arquivo `leads.csv` deve conter as colunas:
`name,title,company_size,challenge`

### Alternativas
- `python main.py` usa lista simulada de leads
- `python main.py --provider grok` força uso do Grok, mesmo se .env estiver diferente
- `python main.py --model openai/gpt-oss-20b` altera o modelo usado

### Execução concorrente e cache
- `--workers N` define quantas threads concorrentes usar nas chamadas à IA (padrão 4)
- O script mantém um cache local `.ai_cache.json` para evitar chamadas repetidas durante desenvolvimento
 - `--metrics` ativa a geração de métricas básicas (latências, hits de cache, erros)
 - Use `--metrics-output file.json` para mudar o arquivo de saída (padrão `metrics.json`)
 - Use `--prometheus-port PORT` para expor métricas Prometheus em `:PORT` (requer `prometheus_client`) 

### Testes e desenvolvimento
- Instalar dependências:

```bash
pip install -r requirements.txt
```

- Rodar testes com `pytest`:

```bash
pytest -q
```

### Docker
Construir e rodar:

```bash
docker build -t smart-triage .
docker run --rm -v $(pwd)/leads.csv:/app/leads.csv smart-triage
```
