"""
Treina o classificador de produção (Cenário 4 por padrão) e grava o .joblib
que a coleta usa para avaliar as calçadas sozinha.

Um comando, da raiz do repositório:

    python -m scripts.inferencia.treinar

1. Dataset: usa data/raw/<projeto>-v<versão>/ (COCO, como o
   scripts/ingestao/download_roboflow.py baixa). Se não existir, baixa do
   Roboflow com as chaves do .env (ROBOFLOW_API_KEY, ROBOFLOW_WORKSPACE_NAME,
   ROBOFLOW_PROJECT_NAME, ROBOFLOW_VERSION). Ou aponte um com --dataset.
2. Embeddings: token [CLS] do backbone do Project Sidewalk, com o mesmo
   código do scripts/transformacao/extract_features.py. Ficam em cache em
   data/processed/<dataset>/ (apague para extrair de novo).
3. Treino: a receita do cenário em scripts/utils/linear_probing.CENARIOS
   (pré-processamento, undersampling e modelo), avaliada em validação e teste
   — os números devem bater com data/reports/avaliacao_taxonomias_v4/.
4. Modelo final: por padrão, refeito com treino + validação (mais dados, mesma
   receita); --so-treino grava o do passo 3. Sai em
   data/models/producao/classificador_qualidade.joblib, com o backbone, as
   classes e as métricas dentro.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from scripts.ingestao.coleta_streetview import config  # noqa: E402

PADRAO_CENARIO = "04_3classes_com_naoid"


def baixar_dataset() -> Path:
    from dotenv import load_dotenv

    load_dotenv(RAIZ / ".env")
    chave, ws, proj = (os.getenv(v) for v in ("ROBOFLOW_API_KEY", "ROBOFLOW_WORKSPACE_NAME", "ROBOFLOW_PROJECT_NAME"))
    versao = int(os.getenv("ROBOFLOW_VERSION", "1"))
    if not (chave and ws and proj):
        sys.exit("Sem dataset local e sem ROBOFLOW_API_KEY / ROBOFLOW_WORKSPACE_NAME / ROBOFLOW_PROJECT_NAME "
                 "no .env. Passe --dataset ou preencha o .env.")
    destino = RAIZ / "data" / "raw" / f"{proj}-v{versao}"
    if (destino / "train" / "_annotations.coco.json").is_file():
        return destino
    from roboflow import Roboflow

    print(f"Baixando {ws}/{proj} v{versao} do Roboflow para {destino.relative_to(RAIZ)}...")
    Roboflow(api_key=chave).workspace(ws).project(proj).version(versao).download(
        "coco", location=str(destino), overwrite=True)
    return destino


def extrair(dataset: Path, saida: Path, backbone: str):
    """Os .npy de treino/validação/teste, extraindo só se ainda não existem."""
    if all((saida / f"{s}_features.npy").is_file() for s in ("train", "valid", "test")):
        print(f"Embeddings já extraídos em {saida.relative_to(RAIZ)} (apague para extrair de novo).")
        return
    import numpy as np
    from transformers import AutoImageProcessor, AutoModel

    from scripts.transformacao.extract_features import process_split
    from scripts.utils.device import get_device

    disp = get_device()
    print(f"Extraindo embeddings com {backbone} ({disp})...")
    proc = AutoImageProcessor.from_pretrained(backbone)
    modelo = AutoModel.from_pretrained(backbone).to(disp).eval()
    saida.mkdir(parents=True, exist_ok=True)
    for split in ("train", "valid", "test"):
        X, y = process_split(split, str(dataset), proc, modelo, disp)
        if X is None:
            sys.exit(f"O split '{split}' do dataset não tem imagens anotadas.")
        np.save(saida / f"{split}_features.npy", X)
        np.save(saida / f"{split}_labels.npy", y)


def metricas(pipe, X, y) -> dict:
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score

    p = pipe.predict(X)
    return {"acuracia": round(accuracy_score(y, p), 4), "acuracia_balanceada": round(balanced_accuracy_score(y, p), 4),
            "f1_macro": round(f1_score(y, p, average="macro"), 4),
            "f1_ponderado": round(f1_score(y, p, average="weighted"), 4)}


def main(argv=None):
    from scripts.utils.linear_probing import CENARIOS

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, help="pasta COCO (train/valid/test); sem isso, baixa do Roboflow")
    ap.add_argument("--cenario", default=PADRAO_CENARIO, choices=sorted(CENARIOS),
                    help=f"receita de scripts/utils/linear_probing.CENARIOS (default: {PADRAO_CENARIO})")
    ap.add_argument("--backbone", default=config.BACKBONE_QUALIDADE)
    ap.add_argument("--saida", type=Path, default=config.MODELO_QUALIDADE)
    ap.add_argument("--so-treino", action="store_true", help="não refaz o modelo final com treino + validação")
    args = ap.parse_args(argv)

    import joblib
    import numpy as np

    from scripts.inferencia.classificador import classe_da_interface
    from scripts.utils.data_utils import aplicar_taxonomia, carregar_dados
    from scripts.utils.linear_probing import treinar_pipeline

    cfg = CENARIOS[args.cenario]
    for nome in cfg["nomes"]:
        classe_da_interface(nome)  # falha antes de treinar se o cenário não couber no mapa

    dataset = (args.dataset if args.dataset else baixar_dataset()).resolve()
    processado = RAIZ / "data" / "processed" / dataset.name
    extrair(dataset, processado, args.backbone)

    d = carregar_dados(processed_dir=str(processado), raw_dir=str(dataset))
    tr = aplicar_taxonomia(d["X_train"], d["y_train"], cfg["mapa"])
    va = aplicar_taxonomia(d["X_valid"], d["y_valid"], cfg["mapa"])
    te = aplicar_taxonomia(d["X_test"], d["y_test"], cfg["mapa"])
    print(f"\n{cfg['titulo']}\n  {cfg['modelo_nome']} · pré-proc. {cfg['preproc']} · undersampling {cfg['teto_under']}")
    print(f"  amostras: treino {len(tr[1])}, validação {len(va[1])}, teste {len(te[1])}")

    pipe, _ = treinar_pipeline(*tr, cfg["preproc"], cfg["teto_under"], cfg["modelo_fn"])
    m = {"validacao": metricas(pipe, *va), "teste": metricas(pipe, *te)}
    for split, v in m.items():
        print(f"  {split:10s} acc {v['acuracia']:.2%} · bal. acc {v['acuracia_balanceada']:.2%} · "
              f"F1 macro {v['f1_macro']:.3f}")

    if not args.so_treino:
        X = np.vstack([tr[0], va[0]])
        y = np.concatenate([tr[1], va[1]])
        pipe, _ = treinar_pipeline(X, y, cfg["preproc"], cfg["teto_under"], cfg["modelo_fn"])
        print(f"  modelo final refeito com treino + validação ({len(y)} amostras); "
              "as métricas acima são do modelo só com treino.")

    nome = f"cenario{args.cenario[:2]}-{dataset.name}"
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "pipeline": pipe, "classes": cfg["nomes"], "backbone": args.backbone, "nome": nome,
        "cenario": args.cenario, "dataset": dataset.name, "metricas": m,
        "treino_e_validacao": not args.so_treino,
        "criado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, args.saida)
    args.saida.with_suffix(".json").write_text(json.dumps(
        {"nome": nome, "cenario": args.cenario, "classes": cfg["nomes"], "backbone": args.backbone,
         "dataset": dataset.name, "metricas": m}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nModelo gravado em {args.saida.relative_to(RAIZ) if args.saida.is_relative_to(RAIZ) else args.saida}"
          " — a próxima coleta já avalia sozinha. Para as ruas já coletadas:\n"
          "  python -m scripts.ingestao.coleta_streetview avaliar")


if __name__ == "__main__":
    main()
