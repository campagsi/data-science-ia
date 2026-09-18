# docs/plano-testes.md`


# Estratégia e Plano de Testes

## 1. Visão Geral
Este documento formaliza as práticas de garantia da qualidade de software adotadas no pipeline, detalhando a separação de testes unitários, testes de integração e validação de contratos sintéticos.

---

## 2. Níveis de Teste

### 2.1 Testes Unitários
Focam no isolamento total da camada de lógica e regras puras de negócio:
* **Entidades e Domínio:** Garantir que entidades rejeitem estados inválidos na instanciação.
* **Validação Sintática:** Testar sanitizadores de campos nulos, formatos inválidos de datas e caracteres corrompidos.
* **Cálculo Estatístico:** Alimentar os algoritmos de média, mediana, desvio padrão e limites IQR com matrizes numéricas determinísticas contendo anomalias conhecidas e validar a classificação.

### 2.2 Testes de Integração
Validam a interoperabilidade segura com componentes de infraestrutura:
* **Persistência Relacional:** Validação de transações em banco PostgreSQL isolado (ex: instâncias descartáveis em containers).
* **Idempotência do Banco:** Tentativa de persistir tuplas duplicadas e verificar a aplicação correta da cláusula `ON CONFLICT`.
* **Rollback Transacional:** Forçar inconsistência no meio de um lote de leituras e validar a integridade transacional garantindo que nenhum item parcial seja gravado.

### 2.3 Testes de Contrato e Ingestão
* **Mock de API REST:** Utilização de interceptores HTTP para emular timeouts, payloads quebrados, respostas `404` e `500`.
* **Cenários de Fronteira no JSON:** Execução contra arquivos de teste contendo estruturas vazias (`[]`), chaves ausentes e strings em locais de valores numéricos.

---

## 3. Matriz de Cenários e Casos Críticos

| Identificador | Módulo | Cenário Avaliado | Resultado Esperado |
|---|---|---|---|
| **CT-01** | `validation` | Leitura com pH igual a $16.5$ (fora da escala físico-química). | Descarte controlado e gravação de log de anomalia sintática. |
| **CT-02** | `validation` | Leitura contendo data e hora futura em relação a `now()`. | Rejeição imediata por violação da regra temporal. |
| **CT-03** | `persistence` | Inserção simultânea de 2 registros idênticos (mesma estação, data e métrica). | Sem falha catastrófica; o registro existente deve ser atualizado (`upsert`). |
| **CT-04** | `analysis` | Amostra uniforme onde todos os valores de condutividade são iguais. | $IQR = 0$, desvio padrão $0$, nenhum registro marcado como outlier. |
| **CT-05** | `analysis` | Amostra de oxigênio dissolvido com 99 pontos normais e 1 ponto com $0.05 \text{ mg/L}$. | O ponto destoante deve ser rotulado com `is_outlier = true`. |

---

## 4. Execução Automatizada e Cobertura
A meta estabelecida de cobertura de testes de lógica de negócio e validação é de **no mínimo 80%**. Os comandos de execução são:
```bash
# Execução completa com relatório de cobertura
# pytest --cov=environmental_pipeline tests/

# Execução focada em testes unitários rápidos
# pytest tests/unit/