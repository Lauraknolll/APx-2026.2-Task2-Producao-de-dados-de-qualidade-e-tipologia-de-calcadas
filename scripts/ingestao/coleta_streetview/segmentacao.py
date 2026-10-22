"""
Etapa 3 — `segmentar`: cada quadrado mostra calçada sem obstrução?

Um modelo de segmentação semântica (SegFormer-B2 treinado no Cityscapes, via
Hugging Face `transformers`, rodando localmente) classifica cada pixel da
vista de contexto em 19 classes (rua, calçada, prédio, carro, pessoa...). Em
cada quadrado — um terço do retângulo do close dentro da vista de contexto —
mede:

    piso       fração de pixels "calçada" ou "terreno";
    obstrução  fração de cada tipo de CLASSES_OBSTRUCAO, mais o borrão que o
               Google põe sobre o próprio carro (que o modelo não conhece; é
               detectado por não ter textura, no próprio quadrado).

Depois `selecao.decidir_zona` escolhe a vista de cada zona e
`exportacao.exportar_ruas` atualiza downloads-ruas/.
"""

import json
import sqlite3
from pathlib import Path

from .banco import filtro_zonas
from .config import (CLASSES_OBSTRUCAO, CLASSES_PISO, MODELO_SEGMENTACAO, OBSTRUCAO_NA_FRENTE,
                     PASTA_IMAGENS, RAIZ)
from .exportacao import exportar_ruas, resumo_exportacao
from .selecao import decidir_zona, motivo_rejeicao
from .util import dica


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

    filtro, params = filtro_zonas(args)
    linhas = conn.execute(f"""
        SELECT t.ponto_id, t.arquivo, t.recorte FROM pontos p
        JOIN tentativas t ON t.ponto_id = p.id
        WHERE p.status = 'pendente' AND t.arquivo IS NOT NULL AND t.frac_calcada IS NULL {filtro}
    """, params).fetchall()
    if not linhas:
        print("Nenhuma vista baixada esperando segmentação" + dica(args, " — rode 'baixar' antes") + ".")
        return

    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
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
