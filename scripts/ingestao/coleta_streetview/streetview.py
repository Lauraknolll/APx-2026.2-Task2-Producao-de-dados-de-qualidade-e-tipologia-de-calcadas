"""
Acesso ao Google Street View.

Os metadados (panorama mais próximo, panorama por id, capturas históricas)
vêm da biblioteca streetlevel, que usa as APIs internas do Google Maps — as
mesmas do navegador: não precisa de chave nem é cobrado, mas pode quebrar se
o Google mudar algo, e consultas demais seguidas levam a bloqueio temporário
do IP (`com_retry`). https://github.com/sk-zk/streetlevel

As imagens não passam pela streetlevel: `renderizar` baixa direto do
servidor de tiles só os blocos de 512 px que uma vista usa e monta a vista
em perspectiva.
"""

import io
import math
import sys
import time
from typing import Optional

import requests

from . import geometria
from .config import ALTURA_CAMERA, DIST_MAX, DIST_MIN

def com_retry(funcao, *args, max_tentativas: int = 5, **kwargs):
    """
    Chama `funcao` repetindo com espera exponencial (1, 2, 4, 8, 16 s). Se
    nunca der certo, o mais provável é o Google ter bloqueado o IP por um
    tempo — melhor parar e rodar de novo mais tarde.
    """
    for tentativa in range(max_tentativas):
        try:
            return funcao(*args, **kwargs)
        except Exception as exc:
            espera = 2 ** tentativa
            print(f"  ! {type(exc).__name__}: {str(exc)[:150]} — tentando de novo em {espera}s",
                  file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"Street View falhou {max_tentativas} vezes seguidas; "
                       "pode ser bloqueio temporário. Rode de novo mais tarde.")


TILE_URL = ("https://streetviewpixels-pa.googleapis.com/v1/tile?cb_client=maps_sv.tactile"
            "&panoid={}&x={}&y={}&zoom={}")
HEADERS_TILE = {"Origin": "https://www.google.com", "Referer": "https://www.google.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0"}


def buscar_panorama(lat: float, lon: float):
    """Panorama mais próximo de (lat, lon), num raio de DIST_MAX m, ou None."""
    from streetlevel import streetview
    return com_retry(streetview.find_panorama, lat, lon, radius=int(DIST_MAX), locale="pt")


def panorama_por_id(pano_id: str):
    """Metadados completos de um panorama (necessários para baixar os tiles)."""
    from streetlevel import streetview
    return com_retry(streetview.find_panorama_by_id, pano_id, locale="pt")


def camera(pano, px: float, py: float) -> tuple[float, float, float]:
    """(distância, heading, pitch) para olhar do panorama até o chão no
    ponto (px, py), em UTM."""
    e, n = geometria.ll_para_utm(pano.lat, pano.lon)
    d = math.hypot(px - e, py - n)
    return d, geometria.azimute(e, n, px, py), -math.degrees(math.atan2(ALTURA_CAMERA, d))


def motivo_descarte(pano, px: float, py: float, desde: Optional[str]) -> Optional[str]:
    """Por que o panorama não serve para o alvo (px, py), ou None se serve."""
    if pano is None:
        return "sem_panorama"
    if pano.is_third_party or pano.source != "launch":
        return "nao_e_carro"  # foto de usuário, trekker, interior de loja...
    if desde and str(pano.date) < desde:
        return "antigo"
    if not DIST_MIN <= camera(pano, px, py)[0] <= DIST_MAX:
        return "distancia"
    return None


def _baixar_tile(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS_TILE, timeout=30)
    resp.raise_for_status()  # dentro do retry: um 5xx passageiro é tentado de novo
    return resp.content


def renderizar(pano, zoom: int, heading: float, heading_pano: float, pitch: float,
               fov_h: float, largura_px: int, altura: int):
    """
    Vista em perspectiva do panorama (array RGB altura x largura_px), olhando
    para `heading`/`pitch` com campo de visão horizontal `fov_h`.

    Para cada pixel da vista calcula a direção (azimute, elevação), converte
    para linha/coluna no panorama equirretangular, baixa só os tiles que essas
    posições tocam e interpola (bilinear).
    """
    import numpy as np
    from PIL import Image
    from scipy.ndimage import map_coordinates

    W, H, ts = pano.image_sizes[zoom].x, pano.image_sizes[zoom].y, pano.tile_size.x

    f = (largura_px / 2) / math.tan(math.radians(fov_h / 2))
    x, y = np.meshgrid((np.arange(largura_px) + 0.5 - largura_px / 2) / f,
                       (altura / 2 - np.arange(altura) - 0.5) / f)
    p = math.radians(pitch)
    frente, cima = math.cos(p) - y * math.sin(p), math.sin(p) + y * math.cos(p)
    azimute = heading + np.degrees(np.arctan2(x, frente))
    elevacao = np.degrees(np.arctan2(cima, np.hypot(frente, x)))
    col = ((azimute - heading_pano) / 360 + 0.5) * W
    centro = col.flat[col.size // 2]
    col = centro + ((col - centro + W / 2) % W - W / 2)  # contínuo, sem a costura do panorama
    lin = np.clip((0.5 - elevacao / 180) * H, 0, H - 1)

    tx0, tx1 = int(col.min() // ts), int(col.max() // ts)
    ty0, ty1 = int(lin.min() // ts), int(lin.max() // ts)
    mosaico = np.zeros(((ty1 - ty0 + 1) * ts, (tx1 - tx0 + 1) * ts, 3), np.uint8)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            conteudo = com_retry(_baixar_tile, TILE_URL.format(pano.id, tx % math.ceil(W / ts), ty, zoom))
            tile = np.asarray(Image.open(io.BytesIO(conteudo)).convert("RGB"))[:ts, :ts]
            mosaico[(ty - ty0) * ts:(ty - ty0) * ts + tile.shape[0],
                    (tx - tx0) * ts:(tx - tx0) * ts + tile.shape[1]] = tile
    coords = [lin - ty0 * ts - 0.5, col - tx0 * ts - 0.5]
    return np.stack([map_coordinates(mosaico[..., c], coords, order=1, mode="nearest")
                     for c in range(3)], axis=-1)
