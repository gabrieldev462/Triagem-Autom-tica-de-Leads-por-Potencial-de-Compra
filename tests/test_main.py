import json
import tempfile
import os
import sys
from pathlib import Path

# ensure project root is on sys.path so `import main` works under pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import extract_json, normalize_priority, load_leads, build_prompt


def test_extract_json_simple():
    txt = '{"prioridade": "Alta", "pain_point": "Dor", "reason": "Motivo"}'
    out = extract_json(txt)
    assert out["prioridade"] == "Alta"
    assert out["pain_point"] == "Dor"
    assert out["reason"] == "Motivo"


def test_extract_json_with_text():
    txt = "Resposta: {'prioridade': 'Média', 'pain_point': 'x', 'reason': 'y'}"
    out = extract_json(txt)
    assert out["prioridade"].lower().startswith("m")


def test_normalize_priority():
    assert normalize_priority("Alta") == "alta"
    assert normalize_priority("MÉDIA") == "média"
    assert normalize_priority("algo") == "baixa"


def test_load_leads_csv(tmp_path):
    p = tmp_path / "leads.csv"
    p.write_text("name,title,company_size,challenge\nA,B,1-10,Test")
    leads = load_leads(str(p))
    assert isinstance(leads, list)
    assert leads[0]["name"] == "A"


def test_build_prompt_contains_name():
    lead = {"name": "Joao", "title": "CEO", "company_size": "1-50", "challenge": "teste"}
    p = build_prompt(lead)
    assert "Joao" in p
