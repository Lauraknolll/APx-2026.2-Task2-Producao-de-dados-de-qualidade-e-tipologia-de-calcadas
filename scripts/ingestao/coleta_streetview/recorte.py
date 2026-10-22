"""
Etapa 2 — `baixar`: o close da calçada de cada vista candidata.

Para cada candidata, recorta do panorama um close que vai da guia ao
alinhamento dos prédios, na resolução máxima, em proporção 3:1, e o corta em
3 quadrados de lado múltiplo de 14 (o patch das redes DINOv2/ViT). Salva
também uma vista de contexto, mais aberta e na mesma direção, que é o que a
segmentação usa: o modelo não reconhece calçada num close sem rua e prédios
em volta.

Arquivos, em data/processed/streetview/:
    <zona>_<tentativa>.jpg                 o close
    quadrados/<zona>_<tentativa>_<k>.jpg   os quadrados, k = 1..3 da esquerda para a direita
    contexto/<zona>_<tentativa>.jpg        a vista aberta

As candidatas vão em levas: primeiro as capturas recentes; as históricas só
nas zonas em que nenhuma recente passou no filtro da segmentação.
"""

import json
import math
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import geometria
from .banco import filtro_zonas
from .config import (ALTURA_CAMERA, CALCADAS_PATH, CONTEXTO_FOV, CONTEXTO_TAMANHO, LADO_MULTIPLO,
                     PASTA_IMAGENS, RAIZ)
from .streetview import panorama_por_id, renderizar
from .util import dica


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
