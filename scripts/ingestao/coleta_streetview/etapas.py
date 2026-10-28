"""
As etapas do pipeline, na ordem: `coletar`, `baixar`, `segmentar` (e
`reavaliar`, que refaz a escolha sem baixar nada).

1. coletar   — zonas e vistas candidatas (só metadados). Divide a linha
               central de cada calçada em zonas de ~50 m; em cada zona marca
               alvos a cada 10 m e, para cada alvo, pega o panorama do Google
               mais próximo, com a câmera apontada para aquele alvo: cada
               candidata é um close perpendicular de um pedaço diferente da
               zona. A captura histórica mais recente de cada panorama entra
               como reserva.
2. baixar    — o close de cada candidata: da guia ao alinhamento dos prédios,
               na resolução máxima, em proporção 3:1, cortado em 3 quadrados
               de lado múltiplo de 14 (o patch das redes DINOv2/ViT), mais uma
               vista de contexto aberta na mesma direção. Primeiro as capturas
               recentes; as históricas só nas zonas em que nenhuma recente
               passou no filtro. Arquivos em data/processed/streetview/:
                   <zona>_<tentativa>.jpg                 o close
                   quadrados/<zona>_<tentativa>_<k>.jpg   os quadrados, k = 1..3
                   contexto/<zona>_<tentativa>.jpg        a vista aberta
3. segmentar — cada quadrado mostra calçada sem obstrução? O SegFormer-B2
               (Cityscapes, via Hugging Face, local) classifica cada pixel da
               vista de contexto — num close sem rua e prédios em volta ele não
               reconhece calçada. Em cada quadrado (uma fatia exata do
               retângulo do close dentro do contexto) mede o piso (calçada ou
               terreno) e a obstrução, incluindo o borrão que o Google põe
               sobre o próprio carro (detectado por não ter textura). Depois
               escolhe a vista de cada zona e atualiza data/processed/downloads-ruas/.
"""

import json
import math
import random
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from . import geometria
from .banco import decidir_zona, exportar_ruas, filtro_zonas, motivo_rejeicao, resumo_exportacao
from .config import (ALTURA_CAMERA, CALCADAS_PATH, CLASSES_OBSTRUCAO, CLASSES_PISO, CONTEXTO_FOV,
                     CONTEXTO_TAMANHO, DISTANCIA_RUA, ESPACAMENTO, LADO_MULTIPLO, MODELO_SEGMENTACAO,
                     OBSTRUCAO_NA_FRENTE, PASTA_IMAGENS, RAIZ)
from .geometria import bbox_rua, buscar_rua, distancia_rua
from .streetview import buscar_panorama, camera, motivo_descarte, panorama_por_id, renderizar

def dica(args, texto: str) -> str:
    """Dica de qual comando rodar depois — omitida dentro do fluxo completo
    ('rua'), que já roda tudo em sequência."""
    return "" if getattr(args, "fluxo", False) else texto


# --------------------------------------------------------------------------- #
# 1. coletar
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# 2. baixar
# --------------------------------------------------------------------------- #

def enquadrar(distancia: float, largura: float, args) -> tuple[float, float, float]:
    """
    (pitch, fov horizontal, fov vertical) de uma vista que pega a calçada da
    guia ao alinhamento e nada mais. A guia fica a distância - largura/2 da
    câmera e o alinhamento a distância + largura/2; em volta, uma folga. A
    vista nunca desce além de `args.limite_inferior`, onde começa o borrão do
    carro do Google.
    """
    perto, longe = max(distancia - largura / 2, 1.0), distancia + largura / 2
    a_perto = -math.degrees(math.atan2(ALTURA_CAMERA, perto))
    a_longe = -math.degrees(math.atan2(ALTURA_CAMERA, longe))
    folga = (a_longe - a_perto) * (args.folga - 1) / 2
    topo, base = a_longe + folga, max(a_perto - folga, args.limite_inferior)
    if topo - base < args.fov_min:
        topo = base + args.fov_min
    fov_v = topo - base
    fov_h = 2 * math.degrees(math.atan(math.tan(math.radians(fov_v / 2)) * args.quadrados))
    return (topo + base) / 2, fov_h, fov_v


def baixar_vista(pano_id: str, heading_pano: float, heading: float, distancia: float,
                 largura: float, destino: Path, args) -> dict:
    """
    Gera o close, os quadrados e a vista de contexto de uma candidata.
    Retorna o retângulo do close dentro da vista de contexto, em frações da
    imagem ({x0, x1, y0, y1}) — as duas vistas têm o mesmo eixo, então o
    close é exatamente o retângulo central do contexto.
    """
    from PIL import Image

    pano = panorama_por_id(pano_id)
    if pano is None:
        raise RuntimeError("panorama não existe mais")
    zoom = len(pano.image_sizes) - 1
    W = pano.image_sizes[zoom].x

    pitch, fov_h, fov_v = enquadrar(distancia, largura, args)
    # Sem esticar além da resolução nativa; lado múltiplo de 14, para os
    # quadrados entrarem nas redes de avaliação sem redimensionar.
    altura = min(args.altura_max, int(fov_v * W / 360))
    altura = max(LADO_MULTIPLO, altura // LADO_MULTIPLO * LADO_MULTIPLO)
    vista = Image.fromarray(renderizar(pano, zoom, heading, heading_pano, pitch, fov_h,
                                       altura * args.quadrados, altura))
    vista.save(destino, quality=92)
    (destino.parent / "quadrados").mkdir(exist_ok=True)
    for k in range(args.quadrados):
        vista.crop((k * altura, 0, (k + 1) * altura, altura)).save(
            destino.parent / "quadrados" / f"{destino.stem}_{k + 1}.jpg", quality=92)

    ctx_w, ctx_h = CONTEXTO_TAMANHO
    ctx_fov_v = 2 * math.degrees(math.atan(math.tan(math.radians(CONTEXTO_FOV / 2)) * ctx_h / ctx_w))
    contexto = renderizar(pano, min(3, zoom), heading, heading_pano, pitch, CONTEXTO_FOV, ctx_w, ctx_h)
    (destino.parent / "contexto").mkdir(exist_ok=True)
    Image.fromarray(contexto).save(destino.parent / "contexto" / destino.name, quality=88)
    rx = math.tan(math.radians(fov_h / 2)) / math.tan(math.radians(CONTEXTO_FOV / 2)) / 2
    ry = math.tan(math.radians(fov_v / 2)) / math.tan(math.radians(ctx_fov_v / 2)) / 2
    return {"x0": 0.5 - rx, "x1": 0.5 + rx, "y0": 0.5 - ry, "y1": 0.5 + ry}


def cmd_baixar(args, conn: sqlite3.Connection) -> int:
    """Baixa as candidatas das zonas pendentes; retorna quantas vistas tentou."""
    PASTA_IMAGENS.mkdir(parents=True, exist_ok=True)

    filtro, params = filtro_zonas(args)
    por_zona: dict[int, list] = {}
    for linha in conn.execute(f"""
        SELECT t.ponto_id, t.posicao, t.pano_id, t.heading_pano, t.heading, t.distancia, p.fid,
               t.origem LIKE 'historica%'
        FROM pontos p JOIN tentativas t ON t.ponto_id = p.id
        WHERE p.status = 'pendente' AND t.arquivo IS NULL AND t.posicao < 1000 {filtro}
        ORDER BY p.id, t.posicao
    """, params):
        por_zona.setdefault(linha[0], []).append(linha)
    for pid, linhas in por_zona.items():  # recentes primeiro; históricas só quando não sobram recentes
        recentes = [linha[:-1] for linha in linhas if not linha[-1]]
        por_zona[pid] = recentes or [linha[:-1] for linha in linhas]
    zonas = list(por_zona)
    if args.aleatorio:
        random.shuffle(zonas)
    if args.limite:
        zonas = zonas[:args.limite]
    pendentes = [linha for pid in zonas for linha in por_zona[pid]]
    larguras = geometria.larguras(CALCADAS_PATH, {linha[-1] for linha in pendentes})
    print(f"{len(pendentes)} vistas de {len(zonas)} zonas para baixar...")

    def tarefa(linha):
        ponto_id, posicao, pano_id, heading_pano, heading, distancia, fid = linha
        destino = PASTA_IMAGENS / f"{ponto_id}_{posicao}.jpg"
        try:
            recorte = baixar_vista(pano_id, heading_pano, heading, distancia, larguras[fid], destino, args)
            return ponto_id, posicao, str(destino.relative_to(RAIZ)), json.dumps(recorte), None
        except Exception as exc:  # registra e segue — não derruba o lote inteiro
            return ponto_id, posicao, None, None, str(exc)[:300]

    ok = erros = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for n, (ponto_id, posicao, arquivo, recorte, erro) in enumerate(pool.map(tarefa, pendentes), 1):
            conn.execute("UPDATE tentativas SET arquivo = ?, recorte = ?, erro = ? "
                         "WHERE ponto_id = ? AND posicao = ?",
                         (arquivo, recorte, erro, ponto_id, posicao))
            ok += arquivo is not None
            erros += arquivo is None
            if n % 10 == 0 or n == len(pendentes):
                conn.commit()
                print(f"  [{n}/{len(pendentes)}] ok={ok} erros={erros}")
    conn.commit()
    print(f"Concluído: ok={ok} erros={erros}. Vistas em {PASTA_IMAGENS.relative_to(RAIZ)}/"
          + dica(args, " — rode 'segmentar'."))
    return len(pendentes)


# --------------------------------------------------------------------------- #
# 3. segmentar
# --------------------------------------------------------------------------- #

def frac_borrao(img) -> float:
    """
    Fração da imagem coberta pelo borrão do carro do Google. O borrão é liso:
    a variância local do laplaciano (quanto de textura há em volta de cada
    pixel) fica perto de zero, enquanto qualquer piso real tem textura.
    """
    import numpy as np
    from scipy.ndimage import laplace, uniform_filter

    cinza = np.asarray(img.convert("L").resize((img.width // 2, img.height // 2))).astype(float)
    lap = laplace(cinza)
    variancia = uniform_filter(lap ** 2, 15) - uniform_filter(lap, 15) ** 2
    return float((variancia < 8).mean())


def cmd_segmentar(args, conn: sqlite3.Connection):
    import numpy as np
    import torch
    from PIL import Image, ImageDraw
    from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
    from ...utils.device import get_device

    filtro, params = filtro_zonas(args)
    linhas = conn.execute(f"""
        SELECT t.ponto_id, t.arquivo, t.recorte FROM pontos p
        JOIN tentativas t ON t.ponto_id = p.id
        WHERE p.status = 'pendente' AND t.arquivo IS NOT NULL AND t.frac_calcada IS NULL {filtro}
    """, params).fetchall()
    if not linhas:
        print("Nenhuma vista baixada esperando segmentação" + dica(args, " — rode 'baixar' antes") + ".")
        return

    dispositivo = get_device()
    print(f"Segmentando {len(linhas)} vistas ({dispositivo})...")
    proc = SegformerImageProcessor.from_pretrained(MODELO_SEGMENTACAO)
    modelo = SegformerForSemanticSegmentation.from_pretrained(MODELO_SEGMENTACAO).to(dispositivo).eval()
    if args.mascaras:
        (PASTA_IMAGENS / "mascaras").mkdir(parents=True, exist_ok=True)

    for ponto_id, arquivo, recorte in linhas:
        # Segmenta a vista de contexto e mede só o retângulo que é o close.
        contexto = Image.open(RAIZ / Path(arquivo).parent / "contexto" / Path(arquivo).name).convert("RGB")
        with torch.no_grad():
            logits = modelo(**proc(images=contexto, return_tensors="pt").to(dispositivo)).logits
        classes = torch.nn.functional.interpolate(
            logits, size=contexto.size[::-1], mode="bilinear").argmax(1)[0].cpu().numpy()
        piso = np.isin(classes, CLASSES_PISO)
        r = json.loads(recorte)
        h, w = classes.shape
        ys = slice(int(r["y0"] * h), int(r["y1"] * h))
        x0, x1 = int(r["x0"] * w), int(r["x1"] * w)
        close = Image.open(RAIZ / arquivo)

        def medir(xs: slice, img_borrao) -> tuple[float, dict]:
            obstrucao = {tipo: round(float(np.isin(classes[ys, xs], ids).mean()), 3)
                         for tipo, ids in CLASSES_OBSTRUCAO.items()}
            obstrucao["borrao"] = round(frac_borrao(img_borrao), 3)
            return round(float(piso[ys, xs].mean()), 3), obstrucao

        frac_calcada, obstrucao = medir(slice(x0, x1), close)
        # Cada quadrado é uma fatia vertical do retângulo do close no contexto:
        # as duas vistas têm o mesmo eixo, então a correspondência é exata.
        n, lado = round(close.width / close.height), close.height
        quadrados = []
        for k in range(n):
            xs = slice(x0 + (x1 - x0) * k // n, x0 + (x1 - x0) * (k + 1) // n)
            p, o = medir(xs, close.crop((k * lado, 0, (k + 1) * lado, lado)))
            quadrados.append({"piso": p, "obstrucao": o})
        conn.execute("UPDATE tentativas SET frac_calcada = ?, obstrucao = ?, quadrados = ? "
                     "WHERE ponto_id = ? AND arquivo = ?",
                     (frac_calcada, json.dumps(obstrucao), json.dumps(quadrados), ponto_id, arquivo))

        if args.mascaras:  # piso em magenta, resto escurecido; quadrados limpos em amarelo, os outros em vermelho
            arr = np.asarray(contexto).astype(float)
            arr[~piso] *= 0.45
            arr[piso] = arr[piso] * 0.5 + np.array([255, 0, 255]) * 0.5
            masc = Image.fromarray(arr.astype(np.uint8))
            desenho = ImageDraw.Draw(masc)
            for k, q in enumerate(quadrados):
                limpo = motivo_rejeicao(q["piso"], q["obstrucao"], args.min_calcada, args.max_obstrucao) is None
                desenho.rectangle([x0 + (x1 - x0) * k // n, ys.start, x0 + (x1 - x0) * (k + 1) // n, ys.stop],
                                  outline="yellow" if limpo else "red", width=3)
            masc.save(PASTA_IMAGENS / "mascaras" / Path(arquivo).name, quality=85)
    conn.commit()

    cont = {"aprovada": 0, "pendente": 0, "recoleta": 0}
    for (ponto_id,) in conn.execute(f"""
            SELECT DISTINCT p.id FROM pontos p JOIN tentativas t ON t.ponto_id = p.id
            WHERE p.status = 'pendente' AND t.frac_calcada IS NOT NULL {filtro}""", params).fetchall():
        cont[decidir_zona(conn, ponto_id, args.min_calcada, args.max_obstrucao)] += 1
    conn.commit()
    print(f"{cont['aprovada']} zonas aprovadas (a melhor vista entre as que têm algum quadrado com piso >= "
          f"{args.min_calcada:.0%} e {' + '.join(OBSTRUCAO_NA_FRENTE)} <= {args.max_obstrucao:.0%}), "
          f"{cont['recoleta']} para recoleta (nenhuma vista passou).")
    print(resumo_exportacao(exportar_ruas(conn)))
    if cont["pendente"]:
        print(f"{cont['pendente']} zonas ainda têm vistas para baixar (capturas históricas)"
              + dica(args, " — rode 'baixar' e 'segmentar' de novo."))


# --------------------------------------------------------------------------- #
# reavaliar
# --------------------------------------------------------------------------- #

def cmd_reavaliar(args, conn: sqlite3.Connection):
    """Reaplica os limites às vistas já segmentadas, sem baixar nem segmentar
    nada — para calibrar --min-calcada e --max-obstrucao."""
    antes = dict(conn.execute("SELECT status, COUNT(*) FROM pontos GROUP BY status").fetchall())
    zonas = [r[0] for r in conn.execute("SELECT DISTINCT ponto_id FROM tentativas WHERE frac_calcada IS NOT NULL")]
    for pid in zonas:
        decidir_zona(conn, pid, args.min_calcada, args.max_obstrucao)
    conn.commit()
    depois = dict(conn.execute("SELECT status, COUNT(*) FROM pontos GROUP BY status").fetchall())
    print(f"{len(zonas)} zonas reavaliadas. Antes: {antes}. Depois: {depois}.")
    print(resumo_exportacao(exportar_ruas(conn)))
