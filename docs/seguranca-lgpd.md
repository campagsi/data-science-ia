# Segurança e LGPD

## Requisito do enunciado

O trabalho original pede rotinas simples de anonimização ou exclusão de campos sensíveis dos identificadores de operadores/estações. Essa exigência permanece, mesmo que o dataset não contenha CPF ou nome de pessoa física. O status está na [matriz de alinhamento](alinhamento-enunciado.md).

## Dados tratados

O payload contém dados ambientais, códigos e nomes de operadores e estações, além de coordenadas geográficas. O contrato não prevê nome ou documento de pessoa física. Códigos e nomes podem identificar instituições ou locais; a ausência de CPF não basta para considerar atendida a exigência de minimização do enunciado.

## Regras

- não registrar tokens, senhas ou URLs privadas nos logs;
- manter credenciais apenas em variáveis de ambiente ou secret manager;
- atualmente `operador_codigo`, `estacao_codigo` e nomes são preservados para manter os relacionamentos; essa decisão técnica não atende, por si só, à exigência de anonimização/exclusão do enunciado;
- antes da entrega, definir e implementar minimização compatível com os relacionamentos, como separar chaves internas de identificadores exibidos e suprimir/mascarar identificadores diretos nas saídas, ou esclarecer formalmente a exigência;
- restringir o acesso ao banco e aos arquivos brutos;
- registrar apenas os campos necessários para análise;
- revisar novos campos antes de incluí-los no contrato.

## Logs

Os logs podem registrar `fonte`, data/hora e motivo de rejeição. Evitar códigos e nomes de operadores/estações até definir a estratégia de minimização. Valores completos de credenciais e dados de autenticação nunca devem ser registrados.
