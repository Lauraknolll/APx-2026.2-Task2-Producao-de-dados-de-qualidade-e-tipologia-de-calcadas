"""
Banco SQLite (streetview.db): o estado de todo o pipeline.

Cada etapa lê e grava aqui, o que torna tudo retomável: interromper e rodar
de novo continua de onde parou.

Tabelas:
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
"""

import sqlite3
from pathlib import Path

from .config import DB_PATH
from .osm import buscar_rua

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
