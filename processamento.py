"""
processamento.py — Lê arquivo bruto da safra, aplica filtros e regras.
CONECTADAS carregado do Supabase automaticamente.
"""

import os
import pandas as pd
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Cache global ──────────────────────────────────────────────────────────────
_PORT_CACHE = {}
_CONECTADAS_DATA_UPLOAD = None

def get_data_upload_conectadas():
    return _CONECTADAS_DATA_UPLOAD

def conectadas_carregado():
    return bool(_PORT_CACHE)

def _get_sb():
    try:
        from supabase import create_client
        url = os.getenv('SUPABASE_URL', '')
        key = os.getenv('SUPABASE_KEY', '')
        if not url or not key: return None
        return create_client(url, key)
    except Exception as e:
        print(f"[Supabase] Erro ao conectar: {e}")
        return None

# ── Normalizar número ─────────────────────────────────────────────────────────
def _fmt_num(v):
    if v is None or v == '': return ''
    s = str(v).strip().replace(' ','').replace('-','').replace('(','').replace(')','')
    if s.endswith('.0'): s = s[:-2]
    try:    return str(int(float(s))) if s else ''
    except: return s

# ── Montar cache CONECTADAS ───────────────────────────────────────────────────
def _build_cache(con: pd.DataFrame):
    global _PORT_CACHE, _CONECTADAS_DATA_UPLOAD
    con = con.copy()
    con['NUM_STR'] = con['NUMERO_LINHA'].apply(_fmt_num)
    con['TEL_STR'] = con['TELEFONE_PORTADO'].apply(_fmt_num)

    mask_num = con['NUM_STR'] != ''
    mask_tel = con['TEL_STR'] != ''

    d_nome  = con[mask_num].set_index('NUM_STR')['NOME'].to_dict()
    d_tel   = con[mask_num].set_index('NUM_STR')['TELEFONE_PORTADO'].apply(_fmt_num).to_dict()
    d_linha = con[mask_num].set_index('NUM_STR')['NUMERO_LINHA'].apply(_fmt_num).to_dict()
    d_port  = con[mask_num].set_index('NUM_STR')['PORTABILIDADE'].to_dict()

    d_nome.update( con[mask_tel].set_index('TEL_STR')['NOME'].to_dict())
    d_tel.update(  con[mask_tel].set_index('TEL_STR')['TELEFONE_PORTADO'].apply(_fmt_num).to_dict())
    d_linha.update(con[mask_tel].set_index('TEL_STR')['NUMERO_LINHA'].apply(_fmt_num).to_dict())
    d_port.update( con[mask_tel].set_index('TEL_STR')['PORTABILIDADE'].to_dict())

    _PORT_CACHE = {'nome': d_nome, 'tel': d_tel, 'linha': d_linha, 'port': d_port}
    _CONECTADAS_DATA_UPLOAD = datetime.now().strftime('%d/%m/%Y %H:%M')
    print(f"[CONECTADAS] Cache: {len(d_nome)} entradas")

def _carregar_conectadas_supabase():
    global _PORT_CACHE
    try:
        sb = _get_sb()
        if not sb:
            print("[CONECTADAS] Sem conexão Supabase")
            return False
        todos = []
        offset = 0
        max_tentativas = 100  # segurança
        tentativa = 0
        print(f"[CONECTADAS] Iniciando carregamento...")
        while tentativa < max_tentativas:
            tentativa += 1
            try:
                res = sb.table('conectadas').select(
                    'NOME,TELEFONE_PORTADO,NUMERO_LINHA,PORTABILIDADE'
                ).range(offset, offset+999).execute()
            except Exception as e_lote:
                print(f"[CONECTADAS] Erro no lote {offset}: {e_lote}")
                break
            if not res.data:
                break
            todos.extend(res.data)
            print(f"[CONECTADAS] Lote {tentativa}: {len(todos)} registros acumulados")
            if len(res.data) < 1000:
                break
            offset += 1000
        if not todos:
            print("[CONECTADAS] Nenhum registro retornado")
            return False
        _build_cache(pd.DataFrame(todos))
        print(f"[CONECTADAS] ✓ Cache montado: {len(todos)} registros")
        return True
    except Exception as e:
        print(f"[CONECTADAS] Erro geral: {e}")
        return False

def garantir_conectadas():
    if not _PORT_CACHE:
        _carregar_conectadas_supabase()

# ── Constantes ────────────────────────────────────────────────────────────────
PAGA_S = {'Paga','Pagamento Cartão de Crédito','Ordem Pagto','Parcelada','Em Negociação'}

MES_SAFRA = {
    'JANEIRO':1,'FEVEREIRO':2,'MARÇO':3,'ABRIL':4,'MAIO':5,'JUNHO':6,
    'JULHO':7,'AGOSTO':8,'SETEMBRO':9,'OUTUBRO':10,'NOVEMBRO':11,'DEZEMBRO':12,
}

# Fechamento = 3 meses após a safra
FECHAMENTO_SAFRA = {
    'JANEIRO':'2026-04','FEVEREIRO':'2026-05','MARÇO':'2026-06','ABRIL':'2026-07',
    'MAIO':'2026-08','JUNHO':'2026-09','JULHO':'2026-10','AGOSTO':'2026-11',
    'SETEMBRO':'2026-12','OUTUBRO':'2027-01','NOVEMBRO':'2027-02','DEZEMBRO':'2027-03',
}

# ── STATUS ESTORNO pelo vencimento da 1ª fatura ───────────────────────────────
def _status_estorno(venc_1a, safra):
    """
    Fechamento = 3 meses após safra.
    - Venc <= fechamento - 2 → 2 FATURAS
    - Venc == fechamento - 1 → 1 FATURA
    - Venc >= fechamento     → SEM ESTORNO
    - Datas corrompidas (< 2026) → SEM ESTORNO
    """
    if venc_1a is None or (isinstance(venc_1a, float) and pd.isna(venc_1a)):
        return 'SEM ESTORNO'
    try:
        # Aceita datetime, date, Timestamp ou string dd/mm/yyyy
        if isinstance(venc_1a, (datetime, date, pd.Timestamp)):
            ts = pd.Timestamp(venc_1a)
            if pd.isna(ts): return 'SEM ESTORNO'
            p = pd.Period(ts.strftime('%Y-%m'), 'M')
        else:
            s = str(venc_1a).strip()
            # formato dd/mm/yyyy → converter para yyyy-mm
            if '/' in s and len(s) >= 8:
                parts = s.split('/')
                s = f"{parts[2][:4]}-{parts[1].zfill(2)}"
            p = pd.Period(s[:7], 'M')
        if p.year < 2026:
            return 'SEM ESTORNO'
        fech = pd.Period(FECHAMENTO_SAFRA.get(safra.upper(), '2026-06'), 'M')
        if p <= fech - 2:  return '2 FATURAS'
        if p == fech - 1:  return '1 FATURA'
        return 'SEM ESTORNO'
    except Exception as e:
        print(f"[_status_estorno] erro: {e} | venc_1a={venc_1a} | safra={safra}")
        return 'SEM ESTORNO'

# ── Calcular etapa pelo dias de atraso ────────────────────────────────────────
def calcular_etapa(dias, portin):
    if dias is None: return None
    PC = 'Portabilidade Concluida'
    if dias <= -2:           return 'Preventivo'
    if 0  <= dias <= 6:      return None
    if 7  <= dias <= 10:     return 'Etapa 1'
    if 11 <= dias <= 15:     return 'Etapa 2'
    if 16 <= dias <= 23:     return 'Etapa 3'
    if 24 <= dias <= 30:     return 'Etapa 4'
    if portin == PC:
        if 31 <= dias <= 42: return 'Etapa 5'
        if 43 <= dias <= 50: return 'Etapa 6'
        if 51 <= dias <= 62: return 'Etapa 7'
        if 63 <= dias <= 70: return 'Etapa 8'
    # 31+ dias sem Port. Concluída → Cobrança Final Sem Portin
    if dias >= 31:           return 'Cobrança Final Sem Portin'
    return None

# ── Fatura mais urgente aberta ────────────────────────────────────────────────
def _parse_venc(vr):
    """Converte vencimento para date independente do tipo."""
    try:
        if isinstance(vr, str):            return datetime.strptime(vr,'%d/%m/%Y').date()
        elif isinstance(vr, datetime):     return vr.date()
        elif isinstance(vr, date):         return vr
        elif isinstance(vr, pd.Timestamp): return vr.date()
    except: pass
    return None

def _faturas_abertas(row, status_estorno=None, portin=None):
    """
    Retorna lista de faturas abertas a cobrar.
    - SEM ESTORNO          → []
    - 1 FATURA             → só 1ª fatura se aberta → [fat1]
    - 2 FATURAS + Port.Conc→ ambas abertas → [fat1, fat2]
    - 2 FATURAS + não Port → só a mais urgente → [fat_urgente]
    - 2 FATURAS (1 paga)   → só a aberta → [fat_aberta]
    """
    today = date.today()
    if status_estorno == 'SEM ESTORNO':
        return []

    faturas_check = ['1ª'] if status_estorno == '1 FATURA' else ['1ª', '2ª']
    abertas = []
    for n in faturas_check:
        st  = str(row.get(f'{n} fatura - Status da fatura') or '').strip()
        if st != 'Aberta': continue
        vr  = row.get(f'{n} fatura - Data de vencimento')
        venc = _parse_venc(vr)
        if not venc: continue
        val_raw = str(row.get(f'{n} fatura - Preço da fatura') or '')                      .replace('R$','').replace(',','.').strip()
        try:    val = float(val_raw)
        except: val = None
        abertas.append({'num': 1 if n=='1ª' else 2,
                        'valor': val, 'vencimento': venc,
                        'dias': (today - venc).days})

    if not abertas:
        return []

    # 2 FATURAS abertas + Portabilidade Concluída → retorna as duas
    if status_estorno == '2 FATURAS' and len(abertas) == 2 and portin == 'Portabilidade Concluida':
        return sorted(abertas, key=lambda x: x['vencimento'])

    # Demais casos → retorna só a mais urgente (menor vencimento)
    return [sorted(abertas, key=lambda x: x['vencimento'])[0]]

# Manter compatibilidade com chamadas antigas
def _fatura_urgente(row, status_estorno=None):
    fats = _faturas_abertas(row, status_estorno=status_estorno)
    return fats[0] if fats else None

# ── Processar arquivo de safra ────────────────────────────────────────────────
def processar_arquivo(uploaded_file, safra: str):
    garantir_conectadas()
    con = _PORT_CACHE

    # Ler arquivo — tenta utf-8, fallback para latin-1
    name = uploaded_file.name.lower()
    if name.endswith('.csv'):
        try:
            df_raw = pd.read_csv(uploaded_file, encoding='utf-8', sep=None, engine='python')
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            try:
                df_raw = pd.read_csv(uploaded_file, encoding='latin-1', sep=None, engine='python')
            except Exception:
                uploaded_file.seek(0)
                df_raw = pd.read_csv(uploaded_file, encoding='cp1252', sep=None, engine='python')
    else:
        df_raw = pd.read_excel(uploaded_file, engine='openpyxl')

    df = df_raw.copy()

    # Parse data de ativação — tolerante a formato, com auditoria de descarte
    import streamlit as st
    _raw_ativ = df['Data da ativação'].copy()
    df['Data da ativação'] = pd.to_datetime(
        df['Data da ativação'], format='%d/%m/%Y', errors='coerce')
    _falhas = df['Data da ativação'].isna() & _raw_ativ.notna()
    if _falhas.any():
        # 2ª tentativa: parse genérico dayfirst para formatos divergentes
        df.loc[_falhas, 'Data da ativação'] = pd.to_datetime(
            _raw_ativ[_falhas], dayfirst=True, errors='coerce')
    _nat = int((df['Data da ativação'].isna() & _raw_ativ.notna()).sum())
    if _nat > 0:
        _ex = _raw_ativ[df['Data da ativação'].isna() & _raw_ativ.notna()].iloc[0]
        st.warning(f"⚠️ {_nat} linha(s) com 'Data da ativação' ilegível foram "
                   f"descartadas. Exemplo do valor recebido: {_ex!r}")

    # ── FILTRO 1: somente mês E ano exatos da safra ───────────────────────────
    mes_num = MES_SAFRA.get(safra.upper(), 3)
    df = df[
        (df['Data da ativação'].dt.month == mes_num) &
        (df['Data da ativação'].dt.year  == 2026)
    ].copy()

    # Parse vencimentos
    df['1ª fatura - Data de vencimento'] = pd.to_datetime(
        df['1ª fatura - Data de vencimento'], dayfirst=True, errors='coerce')
    df['2ª fatura - Data de vencimento'] = pd.to_datetime(
        df['2ª fatura - Data de vencimento'], dayfirst=True, errors='coerce')
    print(f"[DEBUG] Vencimentos parseados: {df['1ª fatura - Data de vencimento'].notna().sum()}/{len(df)} | ex: {df['1ª fatura - Data de vencimento'].dropna().iloc[0] if df['1ª fatura - Data de vencimento'].notna().any() else 'nenhum'}")

    # ── FILTRO 2: venc 1ª >= mês de ativação ─────────────────────────────────
    mask = (df['1ª fatura - Data de vencimento'].notna() &
            df['Data da ativação'].notna() &
            (df['1ª fatura - Data de vencimento'].dt.to_period('M') <
             df['Data da ativação'].dt.to_period('M')))
    df = df[~mask].copy()

    df['Status do número de acesso'] = df['Status do número de acesso'].str.strip()

    # PORTIN via CONECTADAS
    def get_port(num):
        na_ = _fmt_num(num)
        v = con.get('port',{}).get(na_)
        if not v or (isinstance(v, float) and pd.isna(v)):
            tel_ = con.get('tel',{}).get(na_,'')
            v = con.get('port',{}).get(tel_) if tel_ else None
        return v if v and not (isinstance(v, float) and pd.isna(v)) else 0

    df['PORTIN'] = df['Número de acesso'].apply(get_port)
    _n_port    = (df['PORTIN'] == 'Portabilidade Concluida').sum()
    _n_nao     = (df['PORTIN'] == 'Portabilidade nao Concluida').sum()
    _n_null    = df['PORTIN'].isna().sum()
    _cache_sz  = len(con.get('port', {}))
    print(f"[PORTIN] Cache: {_cache_sz} entradas | Concluida: {_n_port} | Nao Concluida: {_n_nao} | Sem match: {_n_null}")

    # STATUS ESTORNO — sempre calculado pelo painel
    df['STATUS ESTORNO'] = df['1ª fatura - Data de vencimento'].apply(
        lambda v: _status_estorno(v, safra))

    # Salvar safra no Supabase (cliente por cliente)
    linhas_con = len(con.get('nome', {})) // 2 if con else 0
    _salvar_safra_supabase(df, safra, linhas_con)

    # ── Construir controle — somente ATIVOS com fatura aberta ─────────────────
    rows = []
    for _, row in df.iterrows():
        status = str(row.get('Status do número de acesso') or '').strip()
        if status != 'Ativo': continue

        portin     = str(row.get('PORTIN') or '')
        status_est = str(row.get('STATUS ESTORNO') or '').strip()
        if status_est == 'SEM ESTORNO': continue

        na        = _fmt_num(row.get('Número de acesso',''))
        st1       = str(row.get('1ª fatura - Status da fatura') or '').strip()
        st2       = str(row.get('2ª fatura - Status da fatura') or '').strip()
        nome_con  = con.get('nome',{}).get(na,'')
        tel_port  = _fmt_num(con.get('tel',{}).get(na,''))
        num_linha = _fmt_num(con.get('linha',{}).get(na,''))
        port_label = ('Concluida' if portin == 'Portabilidade Concluida'
                      else 'Nao Concluida' if portin not in ('','0',0) else '')

        def _parse_venc(vr):
            try:
                if isinstance(vr, str):            return datetime.strptime(vr,'%d/%m/%Y').date()
                elif isinstance(vr, datetime):     return vr.date()
                elif isinstance(vr, date):         return vr
                elif isinstance(vr, pd.Timestamp): return vr.date()
            except: pass
            return None

        def _parse_val(v):
            try: return float(str(v or '').replace('R$','').replace(',','.').strip())
            except: return None

        venc1 = _parse_venc(row.get('1ª fatura - Data de vencimento'))
        venc2 = _parse_venc(row.get('2ª fatura - Data de vencimento'))
        val1  = _parse_val(row.get('1ª fatura - Preço da fatura'))
        val2  = _parse_val(row.get('2ª fatura - Preço da fatura'))
        today = date.today()

        # ── Definir fatura a cobrar ────────────────────────────────────────
        # Regra: só cobra fatura dentro do período de estorno
        # STATUS ESTORNO '1 FATURA' → apenas 1ª fatura
        # STATUS ESTORNO '2 FATURAS' → fatura mais urgente (menor vencimento aberta)
        # Em ambos os casos: 1 linha por cliente nas etapas normais
        fat = None
        if status_est == '1 FATURA':
            if st1 not in PAGA_S and venc1:
                fat = {'num':1,'valor':val1,'vencimento':venc1,'dias':(today-venc1).days}
        elif status_est == '2 FATURAS':
            # Só considera fatura aberta se o vencimento dela também está no período de estorno
            _se2 = _status_estorno(venc2, safra) if venc2 else 'SEM ESTORNO'
            f1_aberta = st1 not in PAGA_S and venc1
            f2_aberta = st2 not in PAGA_S and venc2 and _se2 != 'SEM ESTORNO'
            if f1_aberta and f2_aberta:
                # Pega a mais urgente (menor vencimento)
                if venc1 <= venc2:
                    fat = {'num':1,'valor':val1,'vencimento':venc1,'dias':(today-venc1).days}
                else:
                    fat = {'num':2,'valor':val2,'vencimento':venc2,'dias':(today-venc2).days}
            elif f1_aberta:
                fat = {'num':1,'valor':val1,'vencimento':venc1,'dias':(today-venc1).days}
            elif f2_aberta:
                fat = {'num':2,'valor':val2,'vencimento':venc2,'dias':(today-venc2).days}
            elif f2_aberta:
                fat = {'num':2,'valor':val2,'vencimento':venc2,'dias':(today-venc2).days}

        if not fat: continue

        et = calcular_etapa(fat['dias'], portin)

        rows.append({
            'SAFRA':            safra,
            'CPF':              str(row.get('Cpf','') or ''),
            'NOME':             nome_con,
            'PROPOSTA':         str(row.get('Código externo','') or ''),
            'NUMERO DE ACESSO': na,
            'NUMERO PORTADO':   tel_port,
            'NUMERO LINHA':     num_linha,
            'STATUS ACESSO':    status,
            'FATURA':           fat['num'],
            'STATUS 1ª FATURA': st1,
            'STATUS 2ª FATURA': st2,
            'VALOR':            fat['valor'],
            'VENCIMENTO':       fat['vencimento'],
            'DIAS ATRASO':      fat['dias'],
            'PORTABILIDADE':    port_label,
            'ETAPA':            et,
            'STATUS ESTORNO':   status_est,
            'ENVIO':            None,
            'ULTIMO ENVIO':     None,
            'STATUS PAGAMENTO': st1 if fat['num'] == 1 else st2,
        })
    df_ctrl = pd.DataFrame(rows)
    resumo  = calcular_resumo_base(df, safra)

    achou = sum(1 for r in rows if r['NOME'])
    print(f"[CRUZAMENTO] {safra}: {achou}/{len(rows)} ({achou/len(rows):.0%}) com nome") if rows else None

    return df_ctrl, resumo

# ── Salvar safra no Supabase (cliente por cliente, substitui) ─────────────────
def _salvar_safra_supabase(df: pd.DataFrame, safra: str, linhas_conectadas: int = 0):
    import streamlit as st
    try:
        sb = _get_sb()
        if not sb: return
        faturas_enc = len(df)
        cobertura   = round(faturas_enc / linhas_conectadas * 100, 1) if linhas_conectadas else 0

        # Substituir registros da safra
        sb.table('safras').delete().eq('SAFRA', safra).execute()

        cols_map = {
            'Cpf': 'CPF',
            'Número de acesso': 'NUMERO DE ACESSO',
            'Status do número de acesso': 'STATUS DO ACESSO',
            'Data da ativação': 'DATA DA ATIVACAO',
            '1ª fatura - Status da fatura': 'STATUS 1 FATURA',
            '1ª fatura - Data de vencimento': 'VENCIMENTO 1 FATURA',
            '1ª fatura - Preço da fatura': 'VALOR 1 FATURA',
            '2ª fatura - Status da fatura': 'STATUS 2 FATURA',
            '2ª fatura - Data de vencimento': 'VENCIMENTO 2 FATURA',
            '2ª fatura - Preço da fatura': 'VALOR 2 FATURA',
            'STATUS ESTORNO': 'STATUS ESTORNO',
            'PORTIN': 'PORTIN',
        }
        df_save = df[[c for c in cols_map if c in df.columns]].rename(columns=cols_map).copy()
        df_save['SAFRA']               = safra
        df_save['LINHAS_CONECTADAS']   = linhas_conectadas
        df_save['FATURAS_ENCONTRADAS'] = faturas_enc
        df_save['COBERTURA_PCT']       = cobertura

        # Converter datas para string
        for col in ['DATA DA ATIVACAO','VENCIMENTO 1 FATURA','VENCIMENTO 2 FATURA']:
            if col in df_save.columns:
                df_save[col] = pd.to_datetime(df_save[col], errors='coerce').dt.strftime('%Y-%m-%d')

        # Limpar usando json round-trip — elimina NaN/NaT/Timestamp de forma definitiva
        import json, math as _math, numpy as _np
        def _safe(v):
            if v is None: return None
            if isinstance(v, _np.generic): v = v.item()  # numpy → python nativo
            if isinstance(v, float) and (_math.isnan(v) or _math.isinf(v)): return None
            if str(v) in ("nan","NaT","None","<NA>","NaN"): return None
            return v

        records = [{k: _safe(v) for k,v in r.items()} for r in df_save.to_dict("records")]

        # Verificar se JSON é válido antes de enviar
        try:
            json.dumps(records[:1])
        except Exception as e_json:
            print(f"[SAFRAS] JSON inválido: {e_json}")
            st.warning(f"⚠️ Tabela 'safras' não salva — JSON inválido: {e_json}")
            return

        for i in range(0, len(records), 500):
            try:
                sb.table("safras").insert(records[i:i+500]).execute()
            except Exception as e_insert:
                print(f"[SAFRAS] Erro insert lote {i}: {e_insert}")
                st.warning(f"⚠️ Tabela 'safras' — erro no insert: {e_insert}")
        print(f"[SAFRAS] ✓ {safra}: {faturas_enc} registros | cobertura {cobertura}%")
    except Exception as e:
        print(f"[SAFRAS] Erro: {e}")
        st.warning(f"⚠️ Tabela 'safras' não salva: {e}")

# ── Resumo analítico ──────────────────────────────────────────────────────────
def calcular_resumo_base(df_base: pd.DataFrame, safra: str) -> dict:
    if df_base is None or len(df_base) == 0: return _empty_resumo()
    PC  = 'Portabilidade Concluida'
    ip  = lambda p: p == PC
    is_ = lambda p: p != PC
    if 'PORTIN' not in df_base.columns: return _empty_resumo()

    df_at = df_base[df_base['Status do número de acesso'] == 'Ativo']
    df_in = df_base[df_base['Status do número de acesso'] != 'Ativo']
    N=len(df_base); NA=len(df_at); NC=len(df_in)
    PF=int(df_base['PORTIN'].apply(ip).sum()); SF=int(df_base['PORTIN'].apply(is_).sum())
    PA=int(df_at['PORTIN'].apply(ip).sum());   SA=int(df_at['PORTIN'].apply(is_).sum())
    PC_=int(df_in['PORTIN'].apply(ip).sum());  SC=int(df_in['PORTIN'].apply(is_).sum())

    CATS = ['SEM ESTORNO','1 FATURA PAGA','1 FATURA ABERTA','2 FATURAS - 2 PGS',
            '2 FATURAS (2 ABERTA)','2 FATURAS (1 PAGA 2 ABERTA)','2 FATURAS ( 1 ABERTO 2 PAGA']
    SIM  = {'1 FATURA ABERTA','2 FATURAS (2 ABERTA)',
            '2 FATURAS (1 PAGA 2 ABERTA)','2 FATURAS ( 1 ABERTO 2 PAGA'}

    def sit(row):
        se = str(row.get('STATUS ESTORNO') or '').strip()
        s1 = str(row.get('1ª fatura - Status da fatura') or '').strip()
        s2 = str(row.get('2ª fatura - Status da fatura') or '').strip()
        f1p=s1 in PAGA_S; f1a=not f1p and bool(s1); f2p=s2 in PAGA_S; f2a=not f2p and bool(s2)
        if se == 'SEM ESTORNO': return 'SEM ESTORNO'
        if se == '1 FATURA':
            if f1a: return '1 FATURA ABERTA'
            if f1p: return '1 FATURA PAGA'
            return 'SEM ESTORNO'
        if se == '2 FATURAS':
            if f1a and f2a: return '2 FATURAS (2 ABERTA)'
            if f1p and f2a: return '2 FATURAS (1 PAGA 2 ABERTA)'
            if f1a and f2p: return '2 FATURAS ( 1 ABERTO 2 PAGA'
            if f1p and f2p: return '2 FATURAS - 2 PGS'
            if f1p: return '1 FATURA PAGA'
            if f1a: return '1 FATURA ABERTA'
        return 'SEM ESTORNO'

    db = df_base.copy()
    db['_S'] = db.apply(sit, axis=1)
    da = db[db['Status do número de acesso'] == 'Ativo']

    rows_r = []
    for cat in CATS:
        t  = int((da['_S'] == cat).sum())
        pc = int(((da['_S'] == cat) & da['PORTIN'].apply(ip)).sum())
        rows_r.append((cat, t, pc, t-pc))

    ET=sum(r[1] for r in rows_r if r[0] in SIM)+NC
    EP=sum(r[2] for r in rows_r if r[0] in SIM)+PC_
    ES=sum(r[3] for r in rows_r if r[0] in SIM)+SC
    META=0.38; MV=META*N; RV=ET-MV

    return dict(safra=safra,N=N,NA=NA,NC=NC,PF=PF,SF=SF,PA=PA,SA=SA,PC_=PC_,SC=SC,
                rows=rows_r,ET=ET,EP=EP,ES=ES,CT=ET,CP=EP,CS=ES,META=META,MV=MV,RV=RV)

def calcular_resumo(df):
    if df is None or len(df) == 0: return _empty_resumo()
    N  = len(df)
    NA = int((df['STATUS ACESSO']=='Ativo').sum()) if 'STATUS ACESSO' in df.columns else N
    NC = N - NA
    SIM_ET = {'Etapa 1','Etapa 2','Etapa 3','Etapa 4',
              'Etapa 5','Etapa 6','Etapa 7','Etapa 8','Preventivo'}
    ET = int(df['ETAPA'].isin(SIM_ET).sum()) + NC if 'ETAPA' in df.columns else NC
    META=0.38; MV=META*N; RV=ET-MV
    return dict(N=N,NA=NA,NC=NC,PF=0,SF=0,PA=0,SA=0,PC_=0,SC=0,
                rows=[],ET=ET,EP=0,ES=0,CT=ET,CP=0,CS=0,META=META,MV=MV,RV=RV)

def _empty_resumo():
    return dict(N=0,NA=0,NC=0,PF=0,SF=0,PA=0,SA=0,PC_=0,SC=0,
                rows=[],ET=0,EP=0,ES=0,CT=0,CP=0,CS=0,META=0.38,MV=0,RV=0)
