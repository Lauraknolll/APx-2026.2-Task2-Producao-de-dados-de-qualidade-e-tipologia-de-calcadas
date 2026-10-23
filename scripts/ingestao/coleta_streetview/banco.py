"""
O estado do pipeline (SQLite), a escolha da vista de cada zona e o resultado.

Banco — data/processed/streetview.db. Cada etapa lê e grava aqui, o que torna
tudo retomável: interromper e rodar de novo continua de onde parou.
    pontos      uma linha por ZONA (trecho de ~50 m de calçada). A identidade
                é (fid, anel, ordem): a k-ésima zona do anel de um polígono do
                passeio.gpkg — estável entre rodadas com o mesmo espaçamento.
                Guarda o status (pendente | aprovada | recoleta), a vista
                escolhida (`tentativa`) e quais quadrados dela são limpos.
    tentativas  as vistas candidatas de cada zona: um panorama com a câmera
                apontada para um alvo da zona, o close baixado e o que a
                segmentação mediu nele.
    pontos_rua  a que rua (nome do OSM) cada zona pertence; uma zona de
                esquina pode estar em duas.
    parametros  o espaçamento das zonas (muda a identidade delas).
    rotulos     o gabarito humano de cada quadrado, para calibrar o filtro
                (calibracao.py).

Escolha da vista — um quadrado é LIMPO quando tem piso de calçada >=
MIN_CALCADA e obstrução na frente (veículo + pessoa + borrão do carro) <=
MAX_OBSTRUCAO; uma vista passa se tiver pelo menos um quadrado limpo. Entre
as vistas que passam, a zona fica com a de captura mais recente (o que se
avalia é a calçada como está hoje); na mesma data, a com mais quadrados
limpos e, depois, a de melhor nota. Só lê e grava o banco — não baixa nem
segmenta —, o que permite recalibrar os limites com `reavaliar`.

Resultado — downloads-ruas/<rua>/: só os quadrados limpos da vista escolhida
de cada zona aprovada (<zona>_<tentativa>_<quadrado>.jpg) e um indice.csv
que liga cada foto à zona, às coordenadas e ao panorama de origem. A pasta é
sincronizada com o banco a cada rodada: o que deixou de valer sai.
"""

import csv
import json
import shutil
import sqlite3
import unicodedata
from pathlib import Path
from typing import Optional

from .config import (DB_PATH, MAX_OBSTRUCAO, MIN_CALCADA, OBSTRUCAO_NA_FRENTE, PASTA_IMAGENS, PASTA_RUAS,
                     RAIZ)
from .geometria import buscar_rua


# --------------------------------------------------------------------------- #
# Banco
# --------------------------------------------------------------------------- #

ESQUEMA = """
    CREATE TABLE IF NOT EXISTS pontos (
        id         INTEGER PRIMARY KEY,
        fid        INTEGER NOT NULL,              -- polígono do passeio.gpkg
        anel       INTEGER NOT NULL,
        ordem      INTEGER NOT NULL,              -- k-ésima zona do anel
        lat        REAL NOT NULL,                 -- centro da zona
        lon        REAL NOT NULL,
        rua        TEXT,                          -- nome da via, segundo o Google
        endereco   TEXT,                          -- endereço do panorama mais próximo
        tentativa  INTEGER NOT NULL DEFAULT 1,    -- vista escolhida (tentativas.posicao)
        status     TEXT NOT NULL,                 -- pendente | aprovada | recoleta
        motivo     TEXT,                          -- recoleta: sem_panorama | todas_rejeitadas
        quadrados  TEXT,                          -- quadrados limpos da vista escolhida: "1,3"
        UNIQUE (fid, anel, ordem)
    );

    CREATE TABLE IF NOT EXISTS tentativas (
        ponto_id      INTEGER NOT NULL,
        posicao       INTEGER NOT NULL,           -- nº da tentativa na zona (>= 1000: recusada pela IA)
        origem        TEXT NOT NULL,              -- "+10m" (alvo em relação ao centro) | "historica +10m"
        pano_id       TEXT NOT NULL,
        pano_lat      REAL NOT NULL,
        pano_lon      REAL NOT NULL,
        data          TEXT,                       -- AAAA-MM da captura
        heading_pano  REAL NOT NULL,              -- graus: direção do centro do panorama
        alvo_lat      REAL,                       -- o pedaço de calçada que a vista mostra
        alvo_lon      REAL,
        desvio        REAL,                       -- m do alvo ao centro da zona
        distancia     REAL NOT NULL,              -- m do panorama até o alvo
        heading       REAL NOT NULL,              -- graus, 0 = Norte: para onde a vista aponta
        pitch         REAL NOT NULL,              -- graus, negativo = para baixo (mira o alvo)
        arquivo       TEXT,                       -- close baixado (relativo à raiz do projeto)
        recorte       TEXT,                       -- JSON: retângulo do close na vista de contexto
        erro          TEXT,                       -- erro do download, se houve
        frac_calcada  REAL,                       -- piso visível no close inteiro
        obstrucao     TEXT,                       -- JSON: fração do close tampada, por tipo
        quadrados     TEXT,                       -- JSON: piso e obstrução de cada quadrado
        rejeicao      TEXT,                       -- por que a vista não serve, se não serve
        PRIMARY KEY (ponto_id, posicao)
    );

    CREATE TABLE IF NOT EXISTS pontos_rua (
        ponto_id  INTEGER NOT NULL,
        rua       TEXT NOT NULL,                  -- nome oficial no OSM
        PRIMARY KEY (ponto_id, rua)
    );

    CREATE TABLE IF NOT EXISTS parametros (
        chave TEXT PRIMARY KEY,
        valor TEXT
    );

    CREATE TABLE IF NOT EXISTS rotulos (          -- gabarito humano (calibracao.py)
        ponto_id  INTEGER NOT NULL,
        posicao   INTEGER NOT NULL,
        quadrado  INTEGER NOT NULL,               -- 1..3, da esquerda para a direita
        rotulo    TEXT NOT NULL,                  -- calibracao.ROTULOS
        autor     TEXT,
        quando    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ponto_id, posicao, quadrado)
    );
"""

# Colunas que bancos de versões anteriores não têm.
_MIGRACOES = {
    "tentativas": [("alvo_lat", "REAL"), ("alvo_lon", "REAL"), ("desvio", "REAL"),
                   ("recorte", "TEXT"), ("obstrucao", "TEXT"), ("quadrados", "TEXT")],
    "pontos": [("quadrados", "TEXT")],
}


def abrir_db(path: Path = DB_PATH) -> sqlite3.Connection:
    """Abre (e cria ou atualiza, se preciso) o banco do pipeline."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(ESQUEMA)
    for tabela, colunas in _MIGRACOES.items():
        existentes = {c[1] for c in conn.execute(f"PRAGMA table_info({tabela})")}
        for coluna, tipo in colunas:
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    return conn


def filtro_zonas(args) -> tuple[str, list]:
    """Cláusula SQL (sobre `p.id`) que restringe uma etapa a uma rua (--rua)
    e/ou a zonas específicas (--zonas), com seus parâmetros."""
    sql, params = "", []
    if getattr(args, "rua", None):
        nome, _ = buscar_rua(args.rua)
        sql += " AND p.id IN (SELECT ponto_id FROM pontos_rua WHERE rua = ?)"
        params.append(nome)
    if getattr(args, "zonas", None):
        ids = [int(z) for z in str(args.zonas).split(",")]
        sql += f" AND p.id IN ({','.join('?' * len(ids))})"
        params += ids
    return sql, params


# --------------------------------------------------------------------------- #
# Escolha da vista de cada zona
# --------------------------------------------------------------------------- #

# Motivos gravados pelo filtro; são refeitos a cada decisão. Qualquer outro
# motivo em `tentativas.rejeicao` é uma recusa da etapa de IA, que é mantida.
MOTIVOS_DO_FILTRO = ("pouca_calcada", "obstruida")


def motivo_rejeicao(piso: float, obstrucao: dict, min_calcada: float = MIN_CALCADA,
                    max_obstrucao: float = MAX_OBSTRUCAO) -> Optional[str]:
    """Por que um quadrado (ou vista) não passa no filtro, ou None se passa."""
    if piso < min_calcada:
        return f"pouca_calcada ({piso:.0%})"
    na_frente = {t: obstrucao.get(t, 0.0) for t in OBSTRUCAO_NA_FRENTE}
    if sum(na_frente.values()) > max_obstrucao:
        return f"obstruida ({sum(na_frente.values()):.0%}, mais {max(na_frente, key=na_frente.get)})"
    return None


def nota(piso: float, obstrucao: dict) -> float:
    """Quanto melhor a vista: piso visível menos o que está na frente dele."""
    return piso - sum(obstrucao.get(t, 0.0) for t in OBSTRUCAO_NA_FRENTE)


def avaliar_quadrados(quadrados: list[dict], min_calcada: float,
                      max_obstrucao: float) -> tuple[list[int], Optional[str], float]:
    """
    (quadrados limpos, numerados a partir de 1; motivo, se nenhum é; nota
    média dos limpos). Cada quadrado passa ou não no filtro sozinho — um carro
    num terço do close não condena os outros dois.
    """
    limpos = [k for k, q in enumerate(quadrados, 1)
              if motivo_rejeicao(q["piso"], q["obstrucao"], min_calcada, max_obstrucao) is None]
    if not limpos:
        melhor = max(quadrados, key=lambda q: nota(q["piso"], q["obstrucao"]))
        motivo = motivo_rejeicao(melhor["piso"], melhor["obstrucao"], min_calcada, max_obstrucao)
        return [], f"{motivo} em todos os quadrados", 0.0
    media = sum(nota(quadrados[k - 1]["piso"], quadrados[k - 1]["obstrucao"]) for k in limpos) / len(limpos)
    return limpos, None, media


def decidir_zona(conn: sqlite3.Connection, ponto_id: int,
                 min_calcada: float = MIN_CALCADA, max_obstrucao: float = MAX_OBSTRUCAO) -> str:
    """
    Escolhe a vista da zona entre as candidatas já segmentadas e grava o
    resultado em `pontos`. Se nenhuma passa, ou se ainda falta avaliar alguma
    mais recente que a melhor, a zona segue pendente; se não há mais o que
    avaliar, vai para recoleta. Retorna o novo status.
    """
    melhor, falta = None, []
    for posicao, data, frac_calcada, obstrucao, quadrados, rejeicao in conn.execute(
            "SELECT posicao, COALESCE(data, ''), frac_calcada, obstrucao, quadrados, rejeicao "
            "FROM tentativas WHERE ponto_id = ? AND posicao < 1000 ORDER BY posicao", (ponto_id,)).fetchall():
        if rejeicao and not rejeicao.startswith(MOTIVOS_DO_FILTRO):
            continue  # recusada pela etapa de IA: não volta
        if frac_calcada is None:
            falta.append(data)  # ainda não baixada (ou o download falhou; o 'baixar' tenta de novo)
            continue
        # Vistas segmentadas antes dos quadrados contam como um quadrado só.
        quadrados = json.loads(quadrados) if quadrados else [
            {"piso": frac_calcada, "obstrucao": json.loads(obstrucao)}]
        limpos, motivo, media = avaliar_quadrados(quadrados, min_calcada, max_obstrucao)
        conn.execute("UPDATE tentativas SET rejeicao = ? WHERE ponto_id = ? AND posicao = ?",
                     (motivo, ponto_id, posicao))
        chave = (data, len(limpos), media)
        if motivo is None and (melhor is None or chave > melhor[0]):
            melhor = (chave, posicao, limpos)

    if melhor and not any(data > melhor[0][0] for data in falta):
        status, tentativa, motivo, limpos = "aprovada", melhor[1], None, ",".join(map(str, melhor[2]))
    elif falta:
        status, tentativa, motivo, limpos = "pendente", None, None, None
    else:
        status, tentativa, motivo, limpos = "recoleta", None, "todas_rejeitadas", None
    conn.execute("UPDATE pontos SET status = ?, tentativa = COALESCE(?, tentativa), motivo = ?, quadrados = ? "
                 "WHERE id = ?", (status, tentativa, motivo, limpos, ponto_id))
    return status


def registrar_rejeicao(conn: sqlite3.Connection, ponto_id: int, motivo: str):
    """
    Para a etapa de IA de avaliação: a vista escolhida para a zona não serve.
    Ela nunca mais é escolhida, e a zona passa para a melhor reserva; se não
    houver, vai para recoleta. Rode `reavaliar` (ou o fluxo da rua) depois
    para atualizar downloads-ruas/.
    """
    tentativa = conn.execute("SELECT tentativa FROM pontos WHERE id = ?", (ponto_id,)).fetchone()[0]
    conn.execute("UPDATE tentativas SET rejeicao = ? WHERE ponto_id = ? AND posicao = ?",
                 (f"recusada: {motivo}", ponto_id, tentativa))
    decidir_zona(conn, ponto_id)
    conn.commit()


# --------------------------------------------------------------------------- #
# Resultado: downloads-ruas/<rua>/
# --------------------------------------------------------------------------- #

CAMPOS_INDICE = ["arquivo", "zona", "quadrado", "captura", "lat", "lon", "endereco", "piso",
                 "obstrucao", "pano_id"]


def pasta_da_rua(rua: str) -> Path:
    """downloads-ruas/<nome da rua sem acentos, minúsculo, com hífens>/"""
    sem_acento = unicodedata.normalize("NFKD", rua).encode("ascii", "ignore").decode()
    return PASTA_RUAS / "-".join("".join(c if c.isalnum() else " " for c in sem_acento.lower()).split())


def exportar_ruas(conn: sqlite3.Connection) -> dict[str, int]:
    """Sincroniza downloads-ruas/<rua>/ de todas as ruas; retorna quadrados por rua."""
    contagem = {}
    for (rua,) in conn.execute("SELECT DISTINCT rua FROM pontos_rua").fetchall():
        pasta = pasta_da_rua(rua)
        pasta.mkdir(parents=True, exist_ok=True)
        desejados, linhas = {}, []
        for pid, tentativa, limpos, endereco, data, pano, alat, alon, quadrados in conn.execute("""
                SELECT p.id, p.tentativa, p.quadrados, p.endereco, t.data, t.pano_id, t.alvo_lat,
                       t.alvo_lon, t.quadrados
                FROM pontos p JOIN pontos_rua r ON r.ponto_id = p.id
                JOIN tentativas t ON t.ponto_id = p.id AND t.posicao = p.tentativa
                WHERE r.rua = ? AND p.status = 'aprovada' AND p.quadrados IS NOT NULL
                ORDER BY p.id""", (rua,)):
            medidas = json.loads(quadrados) if quadrados else []
            for k in map(int, limpos.split(",")):
                nome = f"{pid}_{tentativa}_{k}.jpg"
                desejados[nome] = PASTA_IMAGENS / "quadrados" / nome
                m = medidas[k - 1] if k <= len(medidas) else {"piso": None, "obstrucao": {}}
                linhas.append({"arquivo": nome, "zona": pid, "quadrado": k, "captura": data,
                               "lat": round(alat, 7), "lon": round(alon, 7), "endereco": endereco or "",
                               "piso": m["piso"],
                               "obstrucao": round(sum(m["obstrucao"].get(t, 0) for t in OBSTRUCAO_NA_FRENTE), 3),
                               "pano_id": pano})
        for arquivo in pasta.glob("*.jpg"):
            if arquivo.name not in desejados:
                arquivo.unlink()
        for nome, origem in desejados.items():
            if not (pasta / nome).exists() and origem.exists():
                shutil.copy2(origem, pasta / nome)
        with open(pasta / "indice.csv", "w", newline="", encoding="utf-8") as f:
            escritor = csv.DictWriter(f, fieldnames=CAMPOS_INDICE)
            escritor.writeheader()
            escritor.writerows(linhas)
        contagem[rua] = len(desejados)
    return contagem


def resumo_exportacao(contagem: dict[str, int]) -> str:
    """Uma linha com quantos quadrados cada rua tem em downloads-ruas/."""
    if not contagem:
        return ""
    return "Quadrados de calçada por rua: " + "; ".join(
        f"{n} em {pasta_da_rua(rua).relative_to(RAIZ)}" for rua, n in contagem.items())
