-- Entrega 1a: pedidos de EXCLUSÃO na mesma fila das coletas.
-- Idempotente. Aplicar ANTES de atualizar o worker no VPS — é o que garante
-- que o worker antigo falhe limpo (o alvo é JSON, vira busca sem resultado).
-- Spec: docs/superpowers/specs/2026-07-30-exclusao-coleta-design.md

alter table coleta_pedido drop constraint if exists coleta_pedido_tipo_check;
alter table coleta_pedido add  constraint coleta_pedido_tipo_check
  check (tipo in ('termo','ids','excluir'));
