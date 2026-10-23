"""
Modelo de previsão de curto prazo (Fase 10, DA10), treinado fora do laço de perguntas.

    dados.py         séries regulares de 30 min dos parâmetros alvo
    atributos.py     lags, médias móveis, hora em seno e cosseno, sem vazamento temporal
    baselines.py     ingênuo, ingênuo sazonal, MAE e RMSE
    treino.py        Pipeline + TimeSeriesSplit e a regra de aceite (vencer os dois baselines)
    persistencia.py  joblib + metadados.json com SHA-256 e versão do scikit-learn (POL-12)
    relatorio.py     tabela de validação e teste, com o aviso de dados sintéticos

O treino roda por python main.py --treinar-previsao. O LLM não chama nada deste
pacote: a ferramenta prever (src/agente/ferramentas/previsao.py) só LÊ o modelo salvo.

Documentação: docs/agente/ferramentas.md § 4.12 e docs/agente/todo.md (Fase 10)
"""
