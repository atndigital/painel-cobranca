"""
banco.py — Persistência via Supabase.
"""

import os
import pandas as pd
from datetime import date
from pathlib import Path

SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')

_sb = None
def _get_sb():
    global _sb
    if _sb is None:
        from supabase import create_client
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb

# ── Fallback local (caso Supabase falhe) ──────────────────────────────────────
DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)
CTRL_FILE = DATA_DIR / 'controle.parquet'
HIST_FILE = DATA_DIR / 'historico.parquet'
SNAP_FILE = DATA_DIR / 'snapshots.parquet'

def _safe_read(path):
    try:
        if path.exists(): return pd.read_parquet(path)
    except: pass
    return pd.DataFrame()

def _safe_write(df, path):
    try: df.to_parquet(path, index=False)
    except Exception as e: print(f"[local] Erro {path}: {e}")

def _to_df(data):
    if isinstance(data, pd.DataFrame): return data
    if not data: return pd.DataFrame()
    return pd.DataFrame(data)

# ── CONTROLE ──────────────────────────────────────────────────────────────────
def carregar_controle() -> pd.DataFrame:
    try:
        res = _get_sb().table('controle_envio').select('*').execute()
        df = _to_df(res.data)
        if len(df) > 0 and 'id' in df.columns:
            df = df.drop(columns=['id'])
        return df
    except Exception as e:
        print(f"[Supabase] carregar_controle: {e}")
        return _safe_read(CTRL_FILE)

def salvar_controle(df: pd.DataFrame):
    try:
        sb = _get_sb()
        # Limpar tabela e reinserir
        sb.table('controle_envio').delete().neq('id', 0).execute()
        if len(df) == 0: return
        # Converter datas para string
        df_save = df.copy()
        for col in df_save.columns:
            if df_save[col].dtype == 'object': continue
            try:
                if pd.api.types.is_datetime64_any_dtype(df_save[col]):
                    df_save[col] = df_save[col].dt.strftime('%Y-%m-%d')
            except: pass
        # Converter date objects
        for col in df_save.columns:
            df_save[col] = df_save[col].apply(
                lambda v: v.strftime('%Y-%m-%d') if isinstance(v, date) else v)
        records = df_save.where(pd.notnull(df_save), None).to_dict('records')
        # Inserir em lotes de 500
        for i in range(0, len(records), 500):
            sb.table('controle_envio').insert(records[i:i+500]).execute()
        _safe_write(df, CTRL_FILE)
    except Exception as e:
        print(f"[Supabase] salvar_controle: {e}")
        _safe_write(df, CTRL_FILE)

# ── HISTÓRICO ─────────────────────────────────────────────────────────────────
def carregar_historico() -> pd.DataFrame:
    try:
        res = _get_sb().table('historico_pagamentos').select('*').execute()
        df = _to_df(res.data)
        if len(df) > 0 and 'id' in df.columns:
            df = df.drop(columns=['id'])
        return df
    except Exception as e:
        print(f"[Supabase] carregar_historico: {e}")
        return _safe_read(HIST_FILE)

def salvar_historico(df: pd.DataFrame):
    try:
        sb = _get_sb()
        sb.table('historico_pagamentos').delete().neq('id', 0).execute()
        if len(df) == 0: return
        df_save = df.copy()
        for col in df_save.columns:
            df_save[col] = df_save[col].apply(
                lambda v: v.strftime('%Y-%m-%d') if isinstance(v, date) else v)
        records = df_save.where(pd.notnull(df_save), None).to_dict('records')
        for i in range(0, len(records), 500):
            sb.table('historico_pagamentos').insert(records[i:i+500]).execute()
        _safe_write(df, HIST_FILE)
    except Exception as e:
        print(f"[Supabase] salvar_historico: {e}")
        _safe_write(df, HIST_FILE)

# ── SNAPSHOTS DE ESTORNO ──────────────────────────────────────────────────────
def carregar_snapshots() -> pd.DataFrame:
    try:
        res = _get_sb().table('snapshots_estorno').select('*').order('DATA').execute()
        df = _to_df(res.data)
        if len(df) > 0 and 'id' in df.columns:
            df = df.drop(columns=['id'])
        return df
    except Exception as e:
        print(f"[Supabase] carregar_snapshots: {e}")
        return _safe_read(SNAP_FILE)

def salvar_snapshot(safra, gross, estorno, pagamentos, data=None):
    hoje = data or date.today()
    novo = {
        'DATA': hoje.strftime('%Y-%m-%d') if isinstance(hoje, date) else str(hoje),
        'SAFRA': safra, 'GROSS': int(gross),
        'ESTORNO': int(estorno), 'PAGAMENTOS': int(pagamentos),
        'PCT_ESTORNO': round(estorno / gross * 100, 2) if gross else 0,
    }
    try:
        _get_sb().table('snapshots_estorno').insert(novo).execute()
    except Exception as e:
        print(f"[Supabase] salvar_snapshot: {e}")
    snap = carregar_snapshots()
    _safe_write(snap, SNAP_FILE)
    return snap

# ── ATUALIZAÇÃO ───────────────────────────────────────────────────────────────
def atualizar_banco(df_ctrl_atual, df_novo, safra):
    HIST_COLS = ['ENVIO', 'ULTIMO ENVIO', 'STATUS PAGAMENTO']
    KEY_COLS  = ['NUMERO DE ACESSO', 'FATURA']
    OBRIG     = KEY_COLS + HIST_COLS + ['SAFRA']

    for c in OBRIG:
        if c not in df_novo.columns: df_novo[c] = None

    if df_ctrl_atual is None or len(df_ctrl_atual) == 0:
        salvar_controle(df_novo)
        return df_novo.copy(), pd.DataFrame()

    cols_faltando = [c for c in OBRIG if c not in df_ctrl_atual.columns]
    if cols_faltando:
        print(f"[banco] Resetando — colunas faltando: {cols_faltando}")
        salvar_controle(df_novo)
        return df_novo.copy(), pd.DataFrame()

    df_outras = df_ctrl_atual[df_ctrl_atual['SAFRA'] != safra].copy()
    df_safra  = df_ctrl_atual[df_ctrl_atual['SAFRA'] == safra].copy()

    if len(df_safra) == 0:
        df_final = pd.concat([df_outras, df_novo], ignore_index=True)
        salvar_controle(df_final)
        return df_final, pd.DataFrame()

    for c in HIST_COLS:
        if c not in df_safra.columns: df_safra[c] = None

    ctrl_idx = set(zip(df_safra['NUMERO DE ACESSO'].fillna('').astype(str),
                       df_safra['FATURA'].fillna('').astype(str)))
    novo_idx  = set(zip(df_novo['NUMERO DE ACESSO'].fillna('').astype(str),
                        df_novo['FATURA'].fillna('').astype(str)))

    pagaram_keys = ctrl_idx - novo_idx
    df_pagaram = df_safra[df_safra.apply(
        lambda r: (str(r.get('NUMERO DE ACESSO','')), str(r.get('FATURA',''))) in pagaram_keys,
        axis=1)].copy()

    df_hist_new = pd.DataFrame()
    if len(df_pagaram) > 0:
        hoje = date.today()
        keep = ['SAFRA','CPF','NOME','NUMERO DE ACESSO','NUMERO PORTADO',
                'FATURA','VALOR','VENCIMENTO','PORTABILIDADE','ETAPA']
        df_hist_new = df_pagaram[[c for c in keep if c in df_pagaram.columns]].copy()
        df_hist_new.rename(columns={'ETAPA':'ETAPA NO PAGAMENTO'}, inplace=True)
        df_hist_new['DATA PAGAMENTO'] = hoje
        df_hist_new['DIAS ATÉ PAGAMENTO'] = df_hist_new['VENCIMENTO'].apply(
            lambda v: (hoje - v).days if isinstance(v, date) else None)

    cols_pres = [c for c in KEY_COLS + HIST_COLS if c in df_safra.columns]
    df_pres = df_safra[df_safra.apply(
        lambda r: (str(r.get('NUMERO DE ACESSO','')), str(r.get('FATURA',''))) in novo_idx,
        axis=1)][cols_pres].copy()

    if len(df_pres) > 0:
        df_merged = df_novo.merge(
            df_pres.rename(columns={c: c+'_OLD' for c in HIST_COLS if c in df_pres.columns}),
            on=KEY_COLS, how='left')
        for col in HIST_COLS:
            old_col = col + '_OLD'
            if old_col in df_merged.columns:
                df_merged[col] = df_merged[old_col].combine_first(df_merged[col])
                df_merged.drop(columns=[old_col], inplace=True)
    else:
        df_merged = df_novo.copy()

    df_final = pd.concat([df_outras, df_merged], ignore_index=True)
    salvar_controle(df_final)

    if len(df_hist_new) > 0:
        hist = carregar_historico()
        salvar_historico(pd.concat([hist, df_hist_new], ignore_index=True))

    return df_final, df_hist_new

# ── Registrar bloqueio ────────────────────────────────────────────────────────
def registrar_bloqueio(telefone_portado: str) -> bool:
    df = carregar_controle()
    if df is None or len(df) == 0: return False
    tel  = str(telefone_portado).strip()
    mask = df['NUMERO PORTADO'].astype(str).str.strip() == tel
    if not mask.any(): return False
    df.loc[mask, 'STATUS PAGAMENTO'] = 'BLOQUEADO'
    df.loc[mask, 'ETAPA']            = None
    salvar_controle(df)
    return True

# ── Registrar envio ───────────────────────────────────────────────────────────
def registrar_envio(numero_acesso: str, etapa: str, tipo: str, data_envio: date):
    df = carregar_controle()
    if df is None or len(df) == 0: return
    mask = df['NUMERO DE ACESSO'].astype(str) == str(numero_acesso)
    df.loc[mask, 'ENVIO']        = data_envio
    df.loc[mask, 'ULTIMO ENVIO'] = data_envio
    salvar_controle(df)
