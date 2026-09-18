# Versionamento

## Branches sugeridas

- `main`: versão estável;
- `feature/ingestao`: consumo e normalização do JSON;
- `feature/validacao`: regras do contrato e testes;
- `feature/banco`: schema e persistência;
- `feature/analise`: métricas e outliers;
- `docs/contrato-payload`: evolução da documentação.

## Regras para mudanças no contrato

Qualquer alteração de nome, tipo, obrigatoriedade ou unidade deve atualizar, no mesmo pull request:

- [docs/contrato-dados.md](contrato-dados.md);
- [docs/dicionario-dados.md](dicionario-dados.md);
- [docs/modelagem-banco.md](modelagem-banco.md), quando afetar persistência;
- fixtures e testes de validação;
- README e diagramas, quando o fluxo mudar.

## Commits

Usar mensagens objetivas, por exemplo:

```text
feat: normaliza payload ambiental
test: valida campos obrigatorios da estacao
docs: atualiza contrato do json real
```
