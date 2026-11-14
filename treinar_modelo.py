"""
Treina o classificador de qualidade das calçadas (Cenário 4) e gera o .joblib
que a coleta usa para avaliar as fotos sozinha.

    Adequada | Inadequada Geral (parcial + inadequada + sem calçada) | Não identificável

Receita idêntica ao benchmark v4 (scripts/utils/linear_probing.py, cenário
"04_3classes_com_naoid"): embeddings [CLS] 1024D do backbone DINOv2 do Project
Sidewalk -> Normalizer L2 -> StandardScaler -> MLP(128, alpha=0.5,
early_stopping), sem undersampling, random_state=42.

COMO USAR
    1. Preencha a seção "PREENCHA AQUI" logo abaixo.
    2. Rode da raiz do repositório:  python treinar_modelo.py
    3. Saem:
         data/models/producao/classificador_qualidade.joblib   <- o modelo
         data/models/producao/classificador_qualidade.json     <- resumo e métricas
         data/reports/modelo_producao/                         <- relatório do teste:
             predicoes_validacao.csv / predicoes_teste.csv     uma linha por imagem: rua, classe
                                                                real, prevista, probabilidades, acertou
             matriz_confusao_teste.png, f1_por_classe.png
             amostras_acertos.png / amostras_erros.png         imagens do teste com real x previsto
             resumo.md                                          métricas e tabela de erros

O script baixa o dataset do Roboflow (data/raw/<projeto>-v<versão>/), extrai
os embeddings com cache (data/processed/<projeto>-v<versão>/) e treina. Rodar
de novo reaproveita o download e os embeddings: só o treino é refeito.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ============================================================================ #
#                               PREENCHA AQUI                                  #
# ============================================================================ #
#
# Onde achar no Roboflow (app.roboflow.com):
#   - Chave: Settings (engrenagem, menu lateral) -> API Keys -> "Private API Key"
#   - Workspace e projeto: na URL do projeto, app.roboflow.com/<WORKSPACE>/<PROJETO>/...
#   - Versão: aba "Versions" do projeto (a do dataset v4: 10 ruas, ~1.171 imagens)
#
# ⚠️  A CHAVE É SECRETA: não faça commit deste arquivo com ela preenchida nem
#     cole a chave em chats. Alternativa: deixe "" aqui e defina a variável de
#     ambiente ROBOFLOW_API_KEY (ou ponha no .env da raiz, que já é ignorado).

ROBOFLOW_API_KEY = ""                 # <<< PREENCHA: sua Private API Key
ROBOFLOW_WORKSPACE = ""               # <<< PREENCHA: nome do workspace (da URL)
ROBOFLOW_PROJETO = "apx2-bzsou"       # <<< CONFIRA: nome do projeto (da URL)
ROBOFLOW_VERSAO = 4                   # <<< CONFIRA: número da versão do dataset v4

# Se você já tem o dataset baixado (pasta com train/ valid/ test/ em formato
# COCO), aponte aqui e o Roboflow não é usado. Ex.: "data/raw/apx2-bzsou-v4"
DATASET_LOCAL = ""                    # <<< OPCIONAL

# ============================================================================ #
#            Daqui para baixo não precisa mexer (configuração fixa)            #
# ============================================================================ #

BACKBONE = "projectsidewalk/sidewalk-validator-ai-surfaceproblem"  # DINOv2-Large, Hugging Face
SAIDA = Path("data/models/producao/classificador_qualidade.joblib")
RELATORIO = Path("data/reports/modelo_producao")
RETREINAR_COM_VALIDACAO = True  # o modelo final usa treino + validação (as métricas são do só-treino)
LOTE = 16
SEMENTE = 42

# 5 classes do dataset -> 3 do Cenário 4 (mesma prioridade do extract_features.py)
CLASSES_DATASET = ["Adequada", "Parcialmente Adequado", "Inadequada", "Sem calcada", "Nao identificavel"]
CLASSES_MODELO = ["Adequada", "Inadequada Geral", "Não id."]
MAPA = {0: 0, 1: 1, 2: 1, 3: 1, 4: 2}


def _env(nome, valor):
    if valor:
        return valor
    if not os.getenv(nome) and Path(".env").is_file():
        try:
            from dotenv import load_dotenv
            load_dotenv(".env")
        except ImportError:
            pass
    return os.getenv(nome, "")


# ---------------------------------------------------------------------------- #
# 1. Dataset
# ---------------------------------------------------------------------------- #

def obter_dataset() -> Path:
    if DATASET_LOCAL:
        pasta = Path(DATASET_LOCAL)
        if not (pasta / "train" / "_annotations.coco.json").is_file():
            sys.exit(f"DATASET_LOCAL={pasta} não tem train/_annotations.coco.json.")
        return pasta

    chave = _env("ROBOFLOW_API_KEY", ROBOFLOW_API_KEY)
    workspace = _env("ROBOFLOW_WORKSPACE_NAME", ROBOFLOW_WORKSPACE)
    projeto = ROBOFLOW_PROJETO or _env("ROBOFLOW_PROJECT_NAME", "")
    if not chave or not workspace or not projeto:
        sys.exit("Preencha ROBOFLOW_API_KEY e ROBOFLOW_WORKSPACE na seção 'PREENCHA AQUI' do script "
                 "(ou no .env), ou aponte DATASET_LOCAL para um dataset já baixado.")

    destino = Path("data/raw") / f"{projeto}-v{ROBOFLOW_VERSAO}"
    if (destino / "train" / "_annotations.coco.json").is_file():
        print(f"[1/4] Dataset já baixado em {destino}")
        return destino
    from roboflow import Roboflow

    print(f"[1/4] Baixando {workspace}/{projeto} v{ROBOFLOW_VERSAO} do Roboflow...")
    Roboflow(api_key=chave).workspace(workspace).project(projeto).version(ROBOFLOW_VERSAO).download(
        "coco", location=str(destino), overwrite=True)
    return destino


def rotulos_do_split(pasta: Path):
    """[(caminho da imagem, rótulo 0..4)] de um split COCO; imagens sem rótulo ficam de fora."""
    coco = json.loads((pasta / "_annotations.coco.json").read_text(encoding="utf-8"))
    ids = {c["name"]: c["id"] for c in coco.get("categories", [])}
    por_imagem = {}
    for a in coco.get("annotations", []):
        por_imagem.setdefault(a["image_id"], set()).add(a["category_id"])
    prioridade = [(4, "Nao identificavel"), (3, "Sem calcada"), (2, "Inadequada"),
                  (1, "Parcialmente Adequado"), (0, "Adequada")]
    itens = []
    for img in coco["images"]:
        cats = por_imagem.get(img["id"], set())
        rotulo = next((r for r, nome in prioridade if ids.get(nome) in cats), None)
        if rotulo is not None:
            itens.append((pasta / img["file_name"], rotulo))
    return itens


# ---------------------------------------------------------------------------- #
# 2. Embeddings
# ---------------------------------------------------------------------------- #

def extrair_embeddings(dataset: Path):
    import numpy as np

    cache = Path("data/processed") / dataset.name
    if all((cache / f"{s}_features.npy").is_file() for s in ("train", "valid", "test")):
        print(f"[2/4] Embeddings já extraídos em {cache} (apague a pasta para extrair de novo)")
        return {s: (np.load(cache / f"{s}_features.npy"), np.load(cache / f"{s}_labels.npy"))
                for s in ("train", "valid", "test")}

    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModel

    disp = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[2/4] Extraindo embeddings com {BACKBONE} ({disp}). Na 1ª vez baixa ~1,2 GB do Hugging Face.")
    proc = AutoImageProcessor.from_pretrained(BACKBONE)
    modelo = AutoModel.from_pretrained(BACKBONE).to(disp).eval()

    cache.mkdir(parents=True, exist_ok=True)
    dados = {}
    for split in ("train", "valid", "test"):
        itens = rotulos_do_split(dataset / split)
        if not itens:
            sys.exit(f"O split '{split}' não tem imagens rotuladas.")
        feats = []
        for i in range(0, len(itens), LOTE):
            imgs = [Image.open(c).convert("RGB") for c, _ in itens[i:i + LOTE]]
            with torch.no_grad():
                saida = modelo(**proc(images=imgs, return_tensors="pt").to(disp))
            feats.append(saida.last_hidden_state[:, 0, :].float().cpu().numpy())
            print(f"      {split}: {min(i + LOTE, len(itens))}/{len(itens)}", end="\r")
        X, y = np.vstack(feats), np.array([r for _, r in itens])
        np.save(cache / f"{split}_features.npy", X)
        np.save(cache / f"{split}_labels.npy", y)
        print(f"      {split}: {len(y)} imagens, vetores {X.shape[1]}D")
        dados[split] = (X, y)
    return dados


# ---------------------------------------------------------------------------- #
# 3. Treino e avaliação
# ---------------------------------------------------------------------------- #

def novo_pipeline():
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import Normalizer, StandardScaler

    return Pipeline([
        ("norm_l2", Normalizer(norm="l2")),
        ("scaler", StandardScaler()),
        ("clf", MLPClassifier(hidden_layer_sizes=(128,), alpha=0.5, early_stopping=True,
                              max_iter=300, random_state=SEMENTE)),
    ])


def metricas(pipe, X, y):
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score, confusion_matrix,
                                 f1_score)

    p = pipe.predict(X)
    return {
        "acuracia": round(float(accuracy_score(y, p)), 4),
        "acuracia_balanceada": round(float(balanced_accuracy_score(y, p)), 4),
        "f1_macro": round(float(f1_score(y, p, average="macro")), 4),
        "f1_ponderado": round(float(f1_score(y, p, average="weighted")), 4),
        "f1_por_classe": {CLASSES_MODELO[i]: round(float(v), 3)
                          for i, v in enumerate(f1_score(y, p, average=None, labels=[0, 1, 2]))},
        "matriz_confusao": confusion_matrix(y, p, labels=[0, 1, 2]).tolist(),
    }


# ---------------------------------------------------------------------------- #
# Relatório do teste (o modelo só com treino: é o que as métricas medem)
# ---------------------------------------------------------------------------- #

def _rua(nome: str) -> str:
    # "rua-cascavel__1157_3_2_jpg.rf.<hash>.jpg" -> "rua-cascavel"
    return nome.split("__")[0] if "__" in nome else ""


def _original(nome: str) -> str:
    base = nome.split(".rf.")[0]
    return base[:-4] + ".jpg" if base.endswith("_jpg") else nome


def gerar_relatorio(pipe, splits, m):
    import csv

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from PIL import Image

    RELATORIO.mkdir(parents=True, exist_ok=True)
    nomes_5 = ["Adequada", "Parcialmente Adequado", "Inadequada", "Sem calçada", "Não identificável"]
    linhas_teste = []
    for split, (X, y, itens) in splits.items():
        probs = pipe.predict_proba(X)
        pred = probs.argmax(axis=1)
        linhas = []
        for (caminho, r5), real, prev, pr in zip(itens, y, pred, probs):
            linhas.append({
                "split": split, "arquivo": caminho.name, "nome_original": _original(caminho.name),
                "rua": _rua(caminho.name), "caminho": str(caminho), "rotulo_original": nomes_5[r5],
                "real": CLASSES_MODELO[real], "previsto": CLASSES_MODELO[prev],
                "confianca": round(float(pr[prev]), 4), "acertou": int(real == prev),
                **{f"prob_{c}": round(float(pr[i]), 4) for i, c in enumerate(CLASSES_MODELO)},
            })
        with open(RELATORIO / f"predicoes_{split}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(linhas[0]))
            w.writeheader()
            w.writerows(linhas)
        if split == "teste":
            linhas_teste = linhas

    # Matriz de confusão (teste), em contagem e em % da linha
    cm = np.array(m["teste"]["matriz_confusao"])
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.imshow(cm / np.maximum(cm.sum(axis=1, keepdims=True), 1), cmap="Blues", vmin=0, vmax=1)
    for i in range(3):
        for j in range(3):
            pct = cm[i, j] / max(cm[i].sum(), 1)
            ax.text(j, i, f"{cm[i, j]}\n{pct:.0%}", ha="center", va="center",
                    color="white" if pct > 0.5 else "black", fontsize=11)
    ax.set_xticks(range(3), CLASSES_MODELO)
    ax.set_yticks(range(3), CLASSES_MODELO)
    ax.set_xlabel("Previsto")
    ax.set_ylabel("Real")
    ax.set_title(f"Cenário 4 · teste · acc {m['teste']['acuracia']:.1%}")
    fig.tight_layout()
    fig.savefig(RELATORIO / "matriz_confusao_teste.png", dpi=140)
    plt.close(fig)

    # F1 por classe, validação x teste
    fig, ax = plt.subplots(figsize=(6, 3.5))
    x = np.arange(3)
    for k, (split, cor) in enumerate((("validacao", "#9bb7d4"), ("teste", "#2b6cb0"))):
        v = [m[split]["f1_por_classe"][c] for c in CLASSES_MODELO]
        ax.bar(x + (k - 0.5) * 0.38, v, 0.38, label=split, color=cor)
        for xi, vi in zip(x + (k - 0.5) * 0.38, v):
            ax.text(xi, vi + 0.02, f"{vi:.2f}", ha="center", fontsize=9)
    ax.set_xticks(x, CLASSES_MODELO)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("F1")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(RELATORIO / "f1_por_classe.png", dpi=140)
    plt.close(fig)

    # Amostras: 12 acertos e 12 erros do teste, estratificados por classe real
    rng = np.random.RandomState(SEMENTE)
    for nome, acertou in (("amostras_acertos", 1), ("amostras_erros", 0)):
        grupo = [l for l in linhas_teste if l["acertou"] == acertou]
        escolhidas, por_classe = [], {c: [l for l in grupo if l["real"] == c] for c in CLASSES_MODELO}
        for c in por_classe:
            rng.shuffle(por_classe[c])
        while len(escolhidas) < min(12, len(grupo)):
            for c in CLASSES_MODELO:
                if por_classe[c] and len(escolhidas) < 12:
                    escolhidas.append(por_classe[c].pop())
        if not escolhidas:
            continue
        cols = 4
        lins = (len(escolhidas) + cols - 1) // cols
        fig, axs = plt.subplots(lins, cols, figsize=(cols * 3.2, lins * 4.0))
        for ax in np.atleast_1d(axs).ravel():
            ax.axis("off")
        for ax, l in zip(np.atleast_1d(axs).ravel(), escolhidas):
            try:
                ax.imshow(Image.open(l["caminho"]).convert("RGB"))
            except OSError:
                ax.text(0.5, 0.5, "imagem não encontrada", ha="center", va="center")
            cor = "#1a7f37" if acertou else "#c62828"
            ax.set_title(f"Real: {l['real']}\nPrevisto: {l['previsto']} ({l['confianca']:.0%})\n{l['rua']}",
                         fontsize=8.5, color=cor)
        fig.suptitle(("Acertos" if acertou else "Erros") + " no conjunto de teste", fontsize=13)
        fig.tight_layout(rect=(0, 0, 1, 0.97), h_pad=2.5)
        fig.savefig(RELATORIO / f"{nome}.png", dpi=110)
        plt.close(fig)

    # Resumo em markdown
    t = m["teste"]
    erros = {}
    for l in linhas_teste:
        if not l["acertou"]:
            erros[(l["real"], l["previsto"])] = erros.get((l["real"], l["previsto"]), 0) + 1
    por_rua = {}
    for l in linhas_teste:
        a = por_rua.setdefault(l["rua"] or "?", [0, 0])
        a[0] += l["acertou"]
        a[1] += 1
    md = [
        "# Modelo de produção — Cenário 4 (relatório do teste)", "",
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · backbone `{BACKBONE}` · "
        "métricas do modelo treinado só com o treino.", "",
        "| Split | Acurácia | Acurácia balanceada | F1 macro | F1 ponderado |", "|---|---|---|---|---|",
        *[f"| {s} | {m[s]['acuracia']:.2%} | {m[s]['acuracia_balanceada']:.2%} | {m[s]['f1_macro']:.3f} | "
          f"{m[s]['f1_ponderado']:.3f} |" for s in ("validacao", "teste")], "",
        "Referência (data/reports/avaliacao_taxonomias_v4): teste 75,65% · bal. 64,67% · F1 macro 0,664.", "",
        "## F1 por classe (teste)", "",
        *[f"- **{c}**: {v:.2f}" for c, v in t["f1_por_classe"].items()], "",
        "![Matriz de confusão](matriz_confusao_teste.png)", "",
        "## Erros mais comuns (teste)", "", "| Real | Previsto | Imagens |", "|---|---|---|",
        *[f"| {r} | {p} | {n} |" for (r, p), n in sorted(erros.items(), key=lambda x: -x[1])], "",
        "## Acurácia por rua (teste)", "", "| Rua | Acertos | Imagens | Acurácia |", "|---|---|---|---|",
        *[f"| {r} | {a} | {n} | {a / n:.0%} |" for r, (a, n) in sorted(por_rua.items())], "",
        "## Arquivos", "",
        "- `predicoes_teste.csv`, `predicoes_validacao.csv`: uma linha por imagem (real, previsto, probabilidades)",
        "- `amostras_acertos.png`, `amostras_erros.png`: exemplos do teste com a classe real e a prevista",
        "- `f1_por_classe.png`, `matriz_confusao_teste.png`",
    ]
    (RELATORIO / "resumo.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"      Relatório em {RELATORIO}/ (predições por imagem, matriz de confusão, amostras, resumo.md)")


def main():
    import numpy as np

    dataset = obter_dataset()
    dados = extrair_embeddings(dataset)
    itens = {s: rotulos_do_split(dataset / s) for s in ("valid", "test")}
    for s in ("valid", "test"):  # o cache e o COCO têm de estar na mesma ordem
        if len(itens[s]) != len(dados[s][1]) or any(r != int(y) for (_, r), y in zip(itens[s], dados[s][1])):
            sys.exit(f"Os embeddings em cache de '{s}' não batem com as anotações do dataset: apague "
                     f"data/processed/{dataset.name}/ e rode de novo.")
    mapear = lambda y: np.array([MAPA[int(v)] for v in y])
    (Xtr, ytr), (Xva, yva), (Xte, yte) = [(X, mapear(y)) for X, y in (dados[s] for s in ("train", "valid", "test"))]

    print(f"[3/4] Treinando Cenário 4 (treino {len(ytr)}, validação {len(yva)}, teste {len(yte)})")
    pipe = novo_pipeline().fit(Xtr, ytr)
    m = {"validacao": metricas(pipe, Xva, yva), "teste": metricas(pipe, Xte, yte)}
    for split, v in m.items():
        print(f"      {split:10s} acc {v['acuracia']:.2%} | acc bal. {v['acuracia_balanceada']:.2%} | "
              f"F1 macro {v['f1_macro']:.3f} | por classe {v['f1_por_classe']}")
    print("      Referência do relatório v4 (teste): acc 75,65% | acc bal. 64,67% | F1 macro 0,664")
    if abs(m["teste"]["acuracia"] - 0.7565) > 0.05:
        print("      ⚠️  Acurácia de teste longe da referência: confira se a versão do dataset é a v4.")

    gerar_relatorio(pipe, {"validacao": (Xva, yva, itens["valid"]), "teste": (Xte, yte, itens["test"])}, m)

    if RETREINAR_COM_VALIDACAO:
        pipe = novo_pipeline().fit(np.vstack([Xtr, Xva]), np.concatenate([ytr, yva]))
        print(f"      Modelo final refeito com treino + validação ({len(ytr) + len(yva)} amostras)")

    import joblib
    import sklearn

    nome = f"cenario04-{dataset.name}"
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "pipeline": pipe, "classes": CLASSES_MODELO, "backbone": BACKBONE, "nome": nome,
        "cenario": "04_3classes_com_naoid", "dataset": dataset.name, "metricas": m,
        "treino_e_validacao": RETREINAR_COM_VALIDACAO, "sklearn": sklearn.__version__,
        "criado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, SAIDA)
    SAIDA.with_suffix(".json").write_text(json.dumps({
        "nome": nome, "classes": CLASSES_MODELO, "backbone": BACKBONE, "dataset": dataset.name,
        "sklearn": sklearn.__version__, "metricas": m}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[4/4] Pronto: {SAIDA}  (e o resumo em {SAIDA.with_suffix('.json').name})")


if __name__ == "__main__":
    main()
