"""
Etapa 1 — `coletar`: zonas de calçada e vistas candidatas (só metadados).

Divide a linha central de cada calçada do passeio.gpkg em zonas de ~50 m. Em
cada zona marca alvos a cada 10 m e, para cada alvo, pega o panorama do
Google mais próximo, com a câmera apontada para aquele alvo: cada candidata é
um close perpendicular de um pedaço diferente da zona. A captura histórica
mais recente de cada panorama entra como reserva. Nada é baixado aqui.
"""

import math
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from . import geometria
from .config import CALCADAS_PATH, DISTANCIA_RUA, ESPACAMENTO
from .osm import bbox_rua, buscar_rua, distancia_rua
from .streetview import buscar_panorama, camera, motivo_descarte, panorama_por_id
from .util import dica


def zonas_da_area(bbox_ll: tuple, trechos: Optional[list], espacamento: float = ESPACAMENTO,
                  caminho: Path = CALCADAS_PATH, dist_rua: float = DISTANCIA_RUA) -> list[tuple]:
    """
    Zonas de calçada numa área — só geometria local, sem rede: (chave, linha
    central, (início, fim) em m, lat, lon do centro). Com `trechos` (o traçado
    de uma rua), só as zonas a até `dist_rua` m do eixo dela.
    """
    lon0, lat0, lon1, lat1 = bbox_ll
    (e0, n0), (e1, n1) = geometria.ll_para_utm(lat0, lon0), geometria.ll_para_utm(lat1, lon1)
    bbox = (min(e0, e1), min(n0, n1), max(e0, e1), max(n0, n1))
    zonas = []
    for cal in geometria.ler_calcadas(caminho, bbox):
        for n_anel, anel in enumerate(cal["aneis"]):
            linha = geometria.LinhaCentral(anel)
            for ordem, (inicio, fim) in enumerate(linha.zonas(espacamento)):
                px, py = linha.ponto((inicio + fim) / 2)
                if not (bbox[0] <= px <= bbox[2] and bbox[1] <= py <= bbox[3]):
                    continue
                lat, lon = geometria.utm_para_ll(px, py)
                if trechos and distancia_rua(lat, lon, trechos) > dist_rua:
                    continue  # calçada de outra rua que só passa perto
                zonas.append(((cal["fid"], n_anel, ordem), linha, (inicio, fim), lat, lon))
    return zonas


def zonas_da_rua(nome: str) -> tuple[str, list[tuple]]:
    """(nome oficial no OSM, zonas da rua), com os parâmetros padrão."""
    nome_osm, trechos = buscar_rua(nome)
    return nome_osm, zonas_da_area(bbox_rua(trechos, DISTANCIA_RUA + 50), trechos)


def tentativas_da_zona(linha: geometria.LinhaCentral, inicio: float, fim: float, args) -> tuple:
    """
    Vistas candidatas de uma zona: para cada alvo (a cada `args.passo` m, do
    centro para as pontas), o panorama mais próximo que passa em
    `motivo_descarte`; depois, como reserva, as capturas históricas deles.
    Retorna (tentativas, rua, endereço), cada tentativa uma tupla na ordem
    das colunas de `tentativas` gravadas por `_gravar_zona`.
    """
    centro = (inicio + fim) / 2
    n = max(1, round((fim - inicio) / args.passo))
    alvos = sorted((inicio + (fim - inicio) * (k + 0.5) / n for k in range(n)), key=lambda s: abs(s - centro))
    opcoes, vistos, principal = [], set(), None

    def considerar(origem: str, pano, alvo: tuple, desvio: float):
        if pano is not None and pano.id not in vistos:
            vistos.add(pano.id)
            if motivo_descarte(pano, *alvo, args.desde) is None:
                opcoes.append((origem, pano, alvo, desvio))

    recentes = []
    for s in alvos:
        alvo = linha.ponto(s)
        pano = buscar_panorama(*geometria.utm_para_ll(*alvo))
        principal = principal or pano
        considerar(f"{s - centro:+.0f}m", pano, alvo, s - centro)
        if pano is not None:
            recentes.append((pano, alvo, s - centro))
    for pano, alvo, desvio in recentes:
        for h in pano.historical[:args.historicas]:
            if not (args.desde and str(h.date) < args.desde) and h.id not in vistos:
                considerar(f"historica {desvio:+.0f}m", panorama_por_id(h.id), alvo, desvio)

    tentativas = []
    for origem, pano, (ax, ay), desvio in opcoes:
        dist, heading, pitch = camera(pano, ax, ay)
        tentativas.append((origem, pano.id, pano.lat, pano.lon, str(pano.date),
                           round(math.degrees(pano.heading) % 360, 2),
                           round(dist, 1), round(heading, 1), round(pitch, 1),
                           *geometria.utm_para_ll(ax, ay), round(desvio, 1)))
    rua = endereco = None
    if principal:
        rua = ", ".join(sorted({str(s.name) for s in principal.street_names or []})) or None
        endereco = ", ".join(str(a) for a in principal.address or []) or None
    return tentativas, rua, endereco


def _gravar_zona(conn: sqlite3.Connection, chave: tuple, lat: float, lon: float,
                 resultado: tuple, recusados: set) -> str:
    """Grava a zona e suas candidatas; retorna o status (pendente | recoleta)."""
    tentativas, rua, endereco = resultado
    tentativas = [t for t in tentativas if t[1] not in recusados]
    if tentativas:
        status, motivo = "pendente", None
    else:
        status, motivo = "recoleta", ("todas_rejeitadas" if recusados else "sem_panorama")

    pid = conn.execute("""
        INSERT INTO pontos (fid, anel, ordem, lat, lon, rua, endereco, tentativa, status, motivo)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT (fid, anel, ordem) DO UPDATE SET
            lat = excluded.lat, lon = excluded.lon, rua = excluded.rua,
            endereco = excluded.endereco, tentativa = 1,
            status = excluded.status, motivo = excluded.motivo, quadrados = NULL
        RETURNING id
    """, (*chave, lat, lon, rua, endereco, status, motivo)).fetchone()[0]
    # As vistas recusadas pela IA ficam guardadas, depois das novas (posição
    # >= 1000), para que nunca voltem à fila da zona.
    conn.execute("DELETE FROM tentativas WHERE ponto_id = ? AND "
                 "(rejeicao IS NULL OR rejeicao NOT LIKE 'recusada:%')", (pid,))
    conn.execute("UPDATE tentativas SET posicao = posicao + 1000 WHERE ponto_id = ?", (pid,))
    conn.executemany(
        "INSERT INTO tentativas (ponto_id, posicao, origem, pano_id, pano_lat, pano_lon, data, "
        "heading_pano, distancia, heading, pitch, alvo_lat, alvo_lon, desvio) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(pid, n, *t) for n, t in enumerate(tentativas, 1)])
    return status


def cmd_coletar(args, conn: sqlite3.Connection):
    geometria.garantir_calcadas(args.calcadas)

    trechos = nome = None
    if args.rua:
        nome, trechos = buscar_rua(args.rua)
        args.bbox = bbox_rua(trechos, args.distancia_rua + 50)

    # As zonas só são comparáveis entre rodadas com o mesmo espaçamento.
    anterior = conn.execute("SELECT valor FROM parametros WHERE chave = 'espacamento'").fetchone()
    if anterior and float(anterior[0]) != args.espacamento:
        if conn.execute("SELECT 1 FROM pontos WHERE status = 'aprovada' LIMIT 1").fetchone():
            sys.exit(f"Já há zonas aprovadas com espaçamento {anterior[0]} m; "
                     f"use o mesmo espaçamento (ou um banco novo).")
        conn.executescript("DELETE FROM tentativas; DELETE FROM pontos_rua; DELETE FROM pontos;")
    conn.execute("INSERT OR REPLACE INTO parametros VALUES ('espacamento', ?)", (str(args.espacamento),))
    conn.commit()

    existentes = {(fid, anel, ordem): (pid, status)
                  for pid, fid, anel, ordem, status in
                  conn.execute("SELECT id, fid, anel, ordem, status FROM pontos")}
    recusados: dict[int, set] = {}
    for pid, pano in conn.execute("SELECT ponto_id, pano_id FROM tentativas WHERE rejeicao LIKE 'recusada:%'"):
        recusados.setdefault(pid, set()).add(pano)

    # O fluxo 'rua' pode restringir a algumas zonas já escolhidas (`args.apenas`).
    apenas = getattr(args, "apenas", None)
    trabalhos, pulados, da_rua = [], 0, []
    for chave, linha, trecho, lat, lon in zonas_da_area(args.bbox, trechos, args.espacamento,
                                                        args.calcadas, args.distancia_rua):
        if apenas is not None and chave not in apenas:
            continue
        da_rua.append(chave)
        pid, status = existentes.get(chave, (None, None))
        if status == "aprovada" or (status and not args.refazer):
            pulados += 1
            continue
        trabalhos.append((chave, linha, trecho, lat, lon, pid))

    print(f"{len(trabalhos)} zonas de ~{args.espacamento:.0f} m a consultar"
          + (f' na "{nome}"' if trechos else "")
          + (f" ({pulados} já consultadas antes{'' if args.refazer else '; --refazer refaz'})"
             if pulados else "") + "...")

    cont = {"pendente": 0, "recoleta": 0}
    n_tentativas = 0
    t0 = time.time()
    pool = ThreadPoolExecutor(max_workers=args.workers)
    try:
        resultados = pool.map(lambda t: tentativas_da_zona(t[1], *t[2], args), trabalhos)
        for i, ((chave, _, _, lat, lon, pid), resultado) in enumerate(zip(trabalhos, resultados), 1):
            status = _gravar_zona(conn, chave, lat, lon, resultado, recusados.get(pid, set()))
            cont[status] += 1
            n_tentativas += len(resultado[0]) if status == "pendente" else 0
            if i % 25 == 0 or i == len(trabalhos):
                conn.commit()
                print(f"  [{i}/{len(trabalhos)}] {cont['pendente']} com panorama, "
                      f"{cont['recoleta']} sem ({time.time() - t0:.0f}s)")
    finally:
        pool.shutdown(cancel_futures=True)
        if trechos:  # inclusive as zonas puladas, coletadas numa rodada anterior
            conn.executemany("INSERT OR IGNORE INTO pontos_rua SELECT id, ? FROM pontos "
                             "WHERE fid = ? AND anel = ? AND ordem = ?", [(nome, *c) for c in da_rua])
        conn.commit()

    if cont["pendente"]:
        print(f"Média de {n_tentativas / cont['pendente']:.1f} vistas candidatas por zona."
              + dica(args, " Nada foi baixado ainda — rode 'baixar'."))
