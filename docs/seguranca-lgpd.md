# Segurança e LGPD

## Dados tratados

O payload contém dados ambientais e identificadores institucionais de operadores e estações. Não há, no contrato atual, nome de pessoa física, documento pessoal ou coordenada residencial.

## Regras

- não registrar tokens, senhas ou URLs privadas nos logs;
- manter credenciais apenas em variáveis de ambiente ou secret manager;
- não anonimizar `operador_codigo` ou `estacao_codigo` antes da persistência, pois eles são necessários para manter os relacionamentos e rastrear a origem da leitura;
- restringir o acesso ao banco e aos arquivos brutos;
- registrar apenas os campos necessários para análise;
- revisar novos campos antes de incluí-los no contrato.

## Logs

Os logs podem registrar `fonte`, `estacao_codigo`, data/hora e motivo de rejeição. Valores completos de credenciais e dados de autenticação nunca devem ser registrados.
