Passos para criar uma branch e abrir um Pull Request (PR):

1. Crie e troque para uma nova branch:

```bash
git checkout -b feat/metrics-prometheus
```

2. Adicione e commit suas mudanças:

```bash
git add .
git commit -m "feat: add Prometheus metrics, structured logging, CI artifact upload"
```

3. Envie a branch para o remoto:

```bash
git push origin feat/metrics-prometheus
```

4. Abra um PR no GitHub:
- Acesse o repositório no GitHub e clique em "Compare & pull request" na branch enviada.
- Preencha título e descrição (resuma as mudanças: prometheus + logs JSON + CI artifact + README).
- Solicite revisão e crie o PR.

5. (Opcional) Se quiser abrir o PR via CLI, use `gh` (GitHub CLI):

```bash
gh pr create --title "feat: Prometheus metrics + structured logging" --body "Adiciona prometheus_client, logs JSON, upload de metrics.json no CI e instruções no README." --base main
```
