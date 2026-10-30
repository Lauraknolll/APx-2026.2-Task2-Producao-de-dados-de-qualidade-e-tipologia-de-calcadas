"""
Os dados do mapa que vêm da coleta: o traçado de cada rua e a vista
escolhida de cada zona, que o servidor local (servidor.py) entrega à página.

As avaliações ficam à parte (tabela `avaliacoes`), e a
nota de cada zona e a cor da rua são calculadas na página (static/app.js,
`notaEm`), porque a cor depende do zoom: cada ponto do traçado recebe a média
das notas das fotos daquela rua, com peso 1 / (d² + r²), d a distância até a
foto e r um raio que acompanha o zoom. De longe (r grande) as fotos pesam
quase igual e a rua fica com a cor geral dela; de perto (r pequeno) contam as
fotos vizinhas, e entre uma foto e outra a cor passa de uma para a outra aos
poucos (gradiente).

Daqui sai:
- por rua do banco: o traçado do OSM (o mesmo, congelado, que a coleta usou),
  com um vértice a cada PASSO metros no máximo, para o gradiente;
- por zona aprovada: a vista escolhida (a de data/processed/downloads-ruas/),
  no ponto da calçada que ela mostra, e os quadrados limpos dela, com as
  medidas da segmentação.
"""

import json
import math
import sqlite3
from collections import defaultdict

from scripts.ingestao.coleta_streetview.banco import nota, pasta_da_rua
from scripts.ingestao.coleta_streetview.config import OBSTRUCAO_NA_FRENTE
from scripts.ingestao.coleta_streetview.geometria import buscar_rua

PASSO = 5.0  # m: distância máxima entre vértices do traçado (resolução do gradiente)


def zonas(conn: sqlite3.Connection) -> list[dict]:
    """
    Por zona aprovada (e ligada a alguma rua): a vista escolhida, o ponto da
    calçada que ela mostra, as ruas da zona (duas numa esquina) e os
    quadrados limpos, com o piso, a obstrução e a nota da segmentação.
    """
    ruas_da_zona = defaultdict(list)
    for pid, rua in conn.execute("SELECT ponto_id, rua FROM pontos_rua ORDER BY rua"):
        ruas_da_zona[pid].append(rua)

    resultado = []
    for pid, posicao, limpos, endereco, data, pano, lat, lon, heading, pitch, medidas, distancia in conn.execute("""
            SELECT p.id, p.tentativa, p.quadrados, p.endereco, t.data, t.pano_id,
                   COALESCE(t.alvo_lat, p.lat), COALESCE(t.alvo_lon, p.lon), t.heading, t.pitch,
                   t.quadrados, t.distancia
            FROM pontos p JOIN tentativas t ON t.ponto_id = p.id AND t.posicao = p.tentativa
            WHERE p.status = 'aprovada' AND p.quadrados IS NOT NULL
            ORDER BY p.id"""):
        if not ruas_da_zona[pid]:
            continue
        medidas = json.loads(medidas) if medidas else []
        quadrados = []
        for k in (int(q) for q in limpos.split(",")):
            m = medidas[k - 1] if k <= len(medidas) else None
            quadrados.append({
                "quadrado": k,
                "piso": m and m["piso"],
                "obstrucao": m and round(sum(m["obstrucao"].get(t, 0) for t in OBSTRUCAO_NA_FRENTE), 3),
                "nota": m and round(nota(m["piso"], m["obstrucao"]), 3),
            })
        resultado.append({
            "id": pid, "posicao": posicao, "ruas": ruas_da_zona[pid], "lat": lat, "lon": lon,
            "endereco": endereco, "captura": data, "distancia": distancia, "quadrados": quadrados,
            "streetview": (f"https://www.google.com/maps/@?api=1&map_action=pano&pano={pano}"
                           f"&heading={heading:.0f}&pitch={pitch:.0f}"),
        })
    return resultado


def _densificar(trecho: list[tuple]) -> list[list[float]]:
    """O trecho com vértices a no máximo PASSO m uns dos outros; [lat, lon]."""
    pontos = [trecho[0]]
    for (la, oa), (lb, ob) in zip(trecho, trecho[1:]):
        dy = (lb - la) * 111_320
        dx = (ob - oa) * 111_320 * math.cos(math.radians(la))
        n = max(1, math.ceil(math.hypot(dx, dy) / PASSO))
        pontos += [(la + i / n * (lb - la), oa + i / n * (ob - oa)) for i in range(1, n + 1)]
    return [[round(lat, 6), round(lon, 6)] for lat, lon in pontos]  # ~10 cm


def ruas(conn: sqlite3.Connection) -> list[dict]:
    """
    Por rua do banco: o traçado densificado, quantas zonas ela tem no banco
    e quantas ainda estão pendentes, e o nome da pasta dela (o prefixo das
    imagens no Roboflow).
    """
    resultado = []
    for rua, total, pendentes in conn.execute("""
            SELECT r.rua, COUNT(*), SUM(p.status = 'pendente')
            FROM pontos_rua r JOIN pontos p ON p.id = r.ponto_id
            GROUP BY r.rua ORDER BY r.rua""").fetchall():
        _, trechos = buscar_rua(rua)
        resultado.append({
            "nome": rua, "pasta": pasta_da_rua(rua).name, "zonas": total, "pendentes": pendentes,
            "trechos": [_densificar(t) for t in trechos if len(t) > 1],
        })
    return resultado
