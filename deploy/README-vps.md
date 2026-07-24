# Deploy do worker de coleta no VPS (Ubuntu 24.04)

Roteiro para subir o `worker_coleta.py` como serviço no VPS da infosab. Faça junto com o
Claude no SSH — os passos com segredo (cookie, chaves) são colados por você.

## 1. Dependências e código

```bash
sudo apt update && sudo apt install -y python3 python3-pip git
sudo useradd -r -m -d /opt/extrator-ldi extrator   # usuário de serviço (sem login)
sudo -u extrator git clone https://github.com/clovissabino-oss/videosldi.git /opt/extrator-ldi
cd /opt/extrator-ldi
sudo apt install -y python3-flask python3-requests   # requests + flask (sync_supabase importa painel, que usa flask)
```

## 2. Configuração (segredos — NÃO vão pro git)

`config.json` (o coletor lê daqui — vertical/concorrência):
```bash
sudo -u extrator tee /opt/extrator-ldi/config.json >/dev/null <<'EOF'
{ "termo_busca": "", "filtro_local": "", "vertical": "concursos",
  "pasta_saida": "saida", "incluir_url": true, "concorrencia": 4 }
EOF
sudo -u extrator mkdir -p /opt/extrator-ldi/saida
```

`supabase.json` (worker lê Supabase + Resend daqui). Cole os valores reais:
```bash
sudo -u extrator tee /opt/extrator-ldi/supabase.json >/dev/null <<'EOF'
{ "url": "https://zpjsoidxhfwziprjxpqx.supabase.co",
  "service_key": "<SERVICE_ROLE_KEY>",
  "resend_api_key": "<RESEND_API_KEY>",
  "admin_email": "<e-mail do admin p/ aviso de cookie>" }
EOF
sudo chmod 600 /opt/extrator-ldi/supabase.json
```

## 3. Cookie inicial no Supabase (config_ldi)

O worker lê o cookie do Supabase, não de arquivo. Grave o `__Secure-SID` atual (pegue no
F12 do admin logado). Rode uma vez (do VPS ou de qualquer lugar com a service_key):
```bash
cd /opt/extrator-ldi
sudo -u extrator python3 -c "import json,requests; c=json.load(open('supabase.json')); base=c['url'].rstrip('/')+'/rest/v1'; k=c['service_key']; h={'apikey':k,'Authorization':'Bearer '+k,'Content-Type':'application/json','Prefer':'resolution=merge-duplicates'}; requests.post(base+'/config_ldi', headers=h, params={'on_conflict':'id'}, json={'id':1,'cookie':'__Secure-SID=<COLE_O_TOKEN>','atualizado_por':'deploy'}).raise_for_status(); print('cookie gravado')"
```
(Na Fase 4 isso vira o campo do /admin — aqui é manual só para o primeiro boot.)

## 4. Serviço systemd

```bash
sudo cp /opt/extrator-ldi/deploy/worker-coleta.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now worker-coleta
sudo journalctl -u worker-coleta -f      # acompanhar
```

## 5. Aceite (critérios do spec)

1. `journalctl` mostra "worker no ar"; em segundos, `cookie_status` no Supabase atualiza
   (`valido=true` com o cookie válido).
2. Enfileirar um pedido de teste (por SQL no Supabase ou script):
   ```sql
   insert into coleta_pedido (tipo, alvo, rotulo, pedido_por)
   values ('ids', '<uuid-de-um-curso>', 'Teste VPS', 'deploy');
   ```
   → worker processa → status `concluida` → o concurso "Teste VPS" aparece no seletor do app.
3. Enfileirar e, no meio, `update coleta_pedido set status='cancelando' where id=<id>` →
   vira `cancelada` (lembrando: o cancelamento drena os downloads já enfileirados, não é
   instantâneo).
4. Pôr um cookie inválido em `config_ldi` e enfileirar → `aguardando_cookie` +
   `cookie_status.valido=false` + e-mail chega. Renovar o cookie e `update ... set
   status='pendente'` (retentar) → reprocessa.
5. Reiniciar o serviço com um pedido em `rodando` (`sudo systemctl restart worker-coleta`)
   → a reconciliação do boot devolve o pedido a `pendente` e ele reprocessa.

## Notas
- **De→para do Metabase**: o VPS não gera o cache gz (exige Warp), mas agora **consome** a
  tabela `depara_video` do Supabase — o `montar_payload` casa o "ano de gravação real" de lá.
  O VPS não precisa de nada: o Clovis mantém a tabela atualizada com `py sync_depara_supabase.py`
  na máquina dele. (Se a tabela estiver vazia, o ano fica vazio, sem erro.)
- Atualizar o worker depois: `sudo -u extrator git -C /opt/extrator-ldi pull && sudo systemctl restart worker-coleta`.
- O `supabase.json` do VPS é o único lugar com a service_key/Resend no servidor — `chmod 600`, nunca no git.
