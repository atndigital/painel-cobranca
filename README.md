# 📊 Painel de Cobrança — Safras TIM

App Streamlit para controle de cobrança de faturas em aberto por safra,
com funil de envio por WhatsApp, histórico de pagamentos e resumo analítico.

---

## 🚀 Instalação local (5 minutos)

### 1. Pré-requisitos
- Python 3.10+
- pip

### 2. Instalar dependências
```bash
pip install -r requirements.txt
```

### 3. Colocar o arquivo CONECTADAS
Copie o arquivo `CONECTADAS.xlsx` (ou `.xls`) para dentro da pasta `painel_cobranca/`.
Ele é usado para cruzar nome, número portado, número de linha e portabilidade.

### 4. Rodar o app
```bash
streamlit run app.py
```

O painel abre automaticamente em `http://localhost:8501`

---

## ☁️ Deploy online gratuito — Streamlit Cloud

1. Suba o projeto para um repositório GitHub (privado ou público)
2. Acesse https://share.streamlit.io
3. Conecte seu repositório
4. Selecione `app.py` como arquivo principal
5. Clique em **Deploy**

Pronto — o painel fica online com URL pública para o time acessar.

---

## 🗄️ Banco de dados — Supabase (opcional, recomendado para times)

Por padrão o app salva os dados localmente em `data/` (arquivos Parquet).
Para persistência em nuvem com múltiplos usuários simultâneos, use Supabase:

### 1. Criar conta gratuita em https://supabase.com

### 2. Criar as tabelas (SQL):
```sql
-- Controle de envio
create table controle_envio (
  id              bigserial primary key,
  "SAFRA"         text,
  "CPF"           text,
  "NOME"          text,
  "PROPOSTA"      text,
  "NUMERO DE ACESSO" text,
  "NUMERO PORTADO" text,
  "NUMERO LINHA"  text,
  "STATUS ACESSO" text,
  "FATURA"        int,
  "STATUS FATURA" text,
  "VALOR"         numeric,
  "VENCIMENTO"    date,
  "DIAS ATRASO"   int,
  "PORTABILIDADE" text,
  "ETAPA"         text,
  "TIPO DE ENVIO" text,
  "ENVIO"         date,
  "ULTIMO ENVIO"  date,
  "STATUS PAGAMENTO" text,
  unique ("NUMERO DE ACESSO", "FATURA", "SAFRA")
);

-- Histórico de pagamentos
create table historico_pagamentos (
  id              bigserial primary key,
  "SAFRA"         text,
  "CPF"           text,
  "NOME"          text,
  "NUMERO DE ACESSO" text,
  "NUMERO PORTADO" text,
  "FATURA"        int,
  "VALOR"         numeric,
  "VENCIMENTO"    date,
  "PORTABILIDADE" text,
  "ETAPA NO PAGAMENTO" text,
  "TIPO DE ENVIO" text,
  "DATA PAGAMENTO" date,
  "DIAS ATÉ PAGAMENTO" int
);
```

### 3. Configurar variáveis de ambiente
No Streamlit Cloud → Settings → Secrets:
```toml
SUPABASE_URL = "https://xxx.supabase.co"
SUPABASE_KEY = "sua_anon_key_aqui"
```

Ou localmente, crie um arquivo `.env`:
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=sua_anon_key_aqui
```

---

## 📋 Fluxo de uso

### Atualização semanal (5 minutos)
1. Gere o arquivo bruto pelo sistema (CSV ou XLSX)
2. Abra o painel → sidebar esquerdo
3. Faça upload do arquivo e selecione a safra
4. Clique em **⚡ Processar e Atualizar**
5. O painel recalcula automaticamente:
   - Quem pagou → vai para o Histórico
   - Quem continua em aberto → etapa atualizada
   - Histórico de envios preservado

### Seleção para WhatsApp
1. Use os filtros na sidebar (data de vencimento, etapa, portabilidade)
2. Clique em **📲 Exportar para WhatsApp**
3. Baixe o CSV formatado com número, nome, valor e vencimento
4. Importe na sua plataforma de disparo em massa

### Registrar envio realizado
- Na aba **Controle de Envio** → expanda "📝 Registrar envio realizado"
- Informe o número de acesso, etapa e tipo
- O sistema registra a data do envio

---

## 📁 Estrutura do projeto

```
painel_cobranca/
├── app.py              # Interface Streamlit (páginas e componentes)
├── processamento.py    # Leitura dos arquivos, filtros e regras de negócio
├── banco.py            # Persistência (local ou Supabase)
├── requirements.txt    # Dependências Python
├── README.md           # Este arquivo
├── CONECTADAS.xlsx     # ← Você coloca aqui
└── data/               # Criado automaticamente (dados locais)
    ├── controle.parquet
    └── historico.parquet
```

---

## 🔧 Regras de negócio implementadas

| Regra | Descrição |
|-------|-----------|
| Filtro ativação | Somente o mês da safra (ex: Março = apenas ativações em Mar/2026) |
| Filtro vencimento | Remove venc. anterior ao mês de ativação |
| Fatura urgente | Quando há 2 faturas abertas, prioriza a de menor vencimento |
| Status Estorno | Baseado no fechamento da safra (3 meses após ativação) |
| Etapa | Calculada por `hoje - data_vencimento` |
| Etapas 5-8 | Somente Portabilidade Concluída |
| Meta de estorno | 38% do Gross |
| Atualização | Preserva histórico de envios, identifica pagamentos automaticamente |
