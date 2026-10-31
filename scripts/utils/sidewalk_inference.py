import json
import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from PIL import Image
from tqdm import tqdm
import torch
import torch.nn.functional as F
import torchvision.transforms as T
from transformers import AutoImageProcessor, AutoModelForImageClassification
from huggingface_hub import hf_hub_download

from scripts.utils.device import get_device
from scripts.utils.data_utils import listar_imagens_coco, CLASSES_V3
from scripts.utils.sidewalk_models import DinoVisionTransformerClassifier

# Modelos oficiais do Project Sidewalk no Hugging Face
VALIDATOR_MODEL_ID = "projectsidewalk/sidewalk-validator-ai-surfaceproblem"
TAGGER_REPO_ID = "projectsidewalk/sidewalk-tagger-ai-surfaceproblem"
TAGGER_FILENAME = "validated-dino-cls-b-surfaceproblem-tags-best.pth"

# 13 classes oficiais da cabeça multi-label do Tagger (Liu et al., ASSETS '24)
SIDEWALK_TAGS = [
    "brick/cobblestone",
    "bumpy",
    "construction",
    "cracks",
    "grass",
    "height difference",
    "narrow sidewalk",
    "rail/tram track",
    "sand/gravel",
    "NULL",
    "uneven/slanted",
    "utility panel",
    "very broken",
]

# Tags válidas desconsiderando placeholder NULL de treino
VALID_TAGS = [tag for tag in SIDEWALK_TAGS if tag != "NULL"]


def carregar_validator_hf(model_id=VALIDATOR_MODEL_ID, device=None):
    """
    Carrega o modelo oficial sidewalk-validator-ai-surfaceproblem do Hugging Face.
    Classificador binário: 0 -> correct (há problema de superfície) | 1 -> incorrect (sem problema).
    """
    if device is None:
        device = get_device()
    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModelForImageClassification.from_pretrained(model_id)
    model.to(device)
    model.eval()
    return processor, model, device


def carregar_tagger_hf(repo_id=TAGGER_REPO_ID, filename=TAGGER_FILENAME, device=None):
    """
    Baixa e carrega o checkpoint oficial do sidewalk-tagger-ai-surfaceproblem do Hugging Face Hub,
    instanciando a arquitetura nativa DinoVisionTransformerClassifier com 13 classes multi-label.
    """
    if device is None:
        device = get_device()
    pth_path = hf_hub_download(repo_id=repo_id, filename=filename)
    state = torch.load(pth_path, map_location="cpu", weights_only=False)
    state_dict = state.get("model_state_dict", state)

    model = DinoVisionTransformerClassifier("base", nc=13)
    model.load_state_dict(state_dict, strict=True)
    model.to(device)
    model.eval()

    transform = T.Compose([
        T.Resize((518, 518)),
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    return transform, model, device


def executar_ou_carregar_predicoes(
    raw_dir="data/raw/apx2-bzsou-v3",
    splits=("test", "valid", "train"),
    output_dir="data/raw/apx2-bzsou-v3/predicoes_sidewalk",
    forcar_recalculo=False,
    device=None,
):
    """
    Executa a inferência de ambos os modelos do Project Sidewalk (Validator e Tagger)
    sobre os recortes de imagem do dataset v3 ou carrega o resultado consolidado se já salvo.
    Os resultados são salvos em CSV e JSON com link completo para as imagens originais.
    """
    out_path = Path(output_dir)
    csv_file = out_path / "predicoes_sidewalk_v3.csv"
    json_file = out_path / "predicoes_sidewalk_v3.json"

    if csv_file.exists() and not forcar_recalculo:
        print(f"Carregando predições existentes de '{csv_file}'...")
        return pd.read_csv(csv_file)

    out_path.mkdir(parents=True, exist_ok=True)
    df_imagens = listar_imagens_coco(raw_dir=raw_dir, splits=splits)
    if df_imagens.empty:
        raise FileNotFoundError(f"Nenhuma anotação COCO encontrada em '{raw_dir}' para os splits {splits}.")

    print(f"Iniciando inferência Sidewalk sobre {len(df_imagens)} recortes do dataset v3...")
    if device is None:
        device = get_device()
    print(f"Dispositivo de execução: {device}")

    # 1. Carregar modelos
    print(f"Carregando Validator HF ('{VALIDATOR_MODEL_ID}')...")
    v_proc, v_model, _ = carregar_validator_hf(device=device)

    print(f"Carregando Tagger HF ('{TAGGER_REPO_ID}')...")
    t_trans, t_model, _ = carregar_tagger_hf(device=device)

    registros = []
    for idx, row in tqdm(df_imagens.iterrows(), total=len(df_imagens), desc="Inferência Sidewalk"):
        img_path = row["image_path"]
        try:
            image_pil = Image.open(img_path).convert("RGB")
        except Exception as e:
            print(f"Aviso: Não foi possível abrir imagem '{img_path}': {e}")
            continue

        # --- A. Inferência do Validator (Binário) ---
        v_inputs = v_proc(images=image_pil, return_tensors="pt").to(device)
        with torch.no_grad():
            v_logits = v_model(**v_inputs).logits
            v_probs = F.softmax(v_logits, dim=-1).squeeze().cpu().numpy()

        p_correct = float(v_probs[0])
        p_incorrect = float(v_probs[1])
        v_pred = "correct" if p_correct >= p_incorrect else "incorrect"
        v_conf = max(p_correct, p_incorrect)

        # --- B. Inferência do Tagger (13 classes multi-label) ---
        t_tensor = t_trans(image_pil).unsqueeze(0).to(device)
        with torch.no_grad():
            t_logits = t_model(t_tensor)
            t_probs = torch.sigmoid(t_logits).squeeze().cpu().numpy()

        # Top 3 tags (ignorando placeholder NULL)
        tags_validas = [(SIDEWALK_TAGS[i], float(t_probs[i])) for i in range(13) if SIDEWALK_TAGS[i] != "NULL"]
        tags_validas_sort = sorted(tags_validas, key=lambda x: x[1], reverse=True)

        d_reg = {
            "split": row["split"],
            "image_id": row["image_id"],
            "file_name": row["file_name"],
            "original_name": row["original_name"],
            "rua": row["rua"],
            "image_path": row["image_path"],
            "label_id": row["label_id"],
            "label_nome": row["label_nome"],
            # Validator
            "validator_pred": v_pred,
            "validator_conf": round(v_conf, 4),
            "validator_prob_correct": round(p_correct, 4),
            "validator_prob_incorrect": round(p_incorrect, 4),
            # Tagger Top 3
            "tagger_top1_name": tags_validas_sort[0][0],
            "tagger_top1_prob": round(tags_validas_sort[0][1], 4),
            "tagger_top2_name": tags_validas_sort[1][0],
            "tagger_top2_prob": round(tags_validas_sort[1][1], 4),
            "tagger_top3_name": tags_validas_sort[2][0],
            "tagger_top3_prob": round(tags_validas_sort[2][1], 4),
        }

        # Adiciona colunas individuais para cada tag
        for i, tag_name in enumerate(SIDEWALK_TAGS):
            if tag_name != "NULL":
                col_name = "tag_" + tag_name.replace("/", "_").replace(" ", "_")
                d_reg[col_name] = round(float(t_probs[i]), 4)

        registros.append(d_reg)

    df_resultado = pd.DataFrame(registros)
    df_resultado.to_csv(csv_file, index=False, encoding="utf-8")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(df_resultado.to_dict(orient="records"), f, indent=2, ensure_ascii=False)

    print(f"Predições salvas com sucesso em:\n -> {csv_file}\n -> {json_file}")
    return df_resultado


def avaliar_validator(df_pred, split="test", reports_dir="data/reports/avaliacao_sidewalk_nativo"):
    """
    Gera análise estatística comparando os rótulos humanos do nosso dataset com as decisões
    do sidewalk-validator-ai-surfaceproblem (correct = há problema | incorrect = sem problema).
    """
    df_s = df_pred[df_pred["split"] == split].copy() if split else df_pred.copy()
    if df_s.empty:
        print("Nenhuma amostra encontrada para o split especificado.")
        return

    print("=" * 80)
    print(f"AVALIAÇÃO DO SIDEWALK VALIDATOR AI (Split: {split.upper() if split else 'TODOS'} — {len(df_s)} amostras)")
    print("Significado nativo do Sidewalk:")
    print(" -> 'correct': Há problema de superfície na calçada")
    print(" -> 'incorrect': Não há problema de superfície (calçada em boas condições)")
    print("=" * 80)

    # 1. Tabela Cruzada
    crosstab = pd.crosstab(df_s["label_nome"], df_s["validator_pred"], margins=True)
    print("\n--- Distribuição das Predições por Classe do Nosso Dataset ---")
    print(crosstab)

    # 2. Avaliação de Alinhamento Binário
    # Calçadas Adequadas -> Esperado 'incorrect' (sem defeito)
    # Calçadas Inadequadas / Parcialmente Adequadas -> Esperado 'correct' (com defeito)
    df_bin = df_s[df_s["label_nome"].isin(["Adequada", "Inadequada", "Parcialmente Adequado"])].copy()
    if not df_bin.empty:
        y_real_bin = df_bin["label_nome"].apply(lambda x: "incorrect" if x == "Adequada" else "correct")
        y_pred_bin = df_bin["validator_pred"]
        acertos = (y_real_bin == y_pred_bin).sum()
        total = len(df_bin)
        taxa_alinhamento = acertos / total

        print(f"\n--- Alinhamento Binário com Critério Humano ({total} amostras analisáveis) ---")
        print(f"Adequadas consideradas 'incorrect' (Sem Defeito) e Inadequadas/Parciais consideradas 'correct' (Com Defeito):")
        print(f"Taxa de Concordância: {taxa_alinhamento:.2%} ({acertos}/{total})")

        # Matriz de concordância
        from sklearn.metrics import confusion_matrix
        cm = confusion_matrix(y_real_bin, y_pred_bin, labels=["incorrect", "correct"])
        print("\nMatriz de Concordância [Linha: Humano, Coluna: Sidewalk]:")
        print(f"                 Prev: incorrect (Sem Defeito)  Prev: correct (Com Defeito)")
        print(f"Real: Adequada                 {cm[0, 0]:<30} {cm[0, 1]}")
        print(f"Real: Inadequada/Parcial       {cm[1, 0]:<30} {cm[1, 1]}")

    # Salva relatório resumido se desejado
    if reports_dir:
        rep_path = Path(reports_dir)
        rep_path.mkdir(parents=True, exist_ok=True)
        crosstab.to_csv(rep_path / f"tabela_cruzada_validator_{split}.csv")


def avaliar_tagger(df_pred, split="test", reports_dir="data/reports/avaliacao_sidewalk_nativo"):
    """
    Calcula a probabilidade média e a frequência de disparo de cada uma das 12 tags
    do Sidewalk Tagger para cada uma das classes reais do dataset v3.
    Gera e salva um heatmap de coocorrência.
    """
    df_s = df_pred[df_pred["split"] == split].copy() if split else df_pred.copy()
    if df_s.empty:
        print("Nenhuma amostra encontrada para o split especificado.")
        return

    cols_tag = [c for c in df_s.columns if c.startswith("tag_")]
    mapa_col_para_tag = {c: c.replace("tag_", "").replace("_", " ") for c in cols_tag}

    # Calcula médias de confiança por classe
    medias_por_classe = df_s.groupby("label_nome")[cols_tag].mean().rename(columns=mapa_col_para_tag)

    print("=" * 80)
    print(f"AVALIAÇÃO DO SIDEWALK TAGGER AI (Split: {split.upper() if split else 'TODOS'} — {len(df_s)} amostras)")
    print("Probabilidade Média de cada Tag do Sidewalk por Classe Real:")
    print("=" * 80)
    print((medias_por_classe * 100).round(1).astype(str) + "%")

    # Heatmap visual
    fig, ax = plt.subplots(figsize=(12, 5.5))
    sns.heatmap(
        medias_por_classe * 100,
        annot=True,
        fmt=".1f",
        cmap="YlGnBu",
        cbar_kws={"label": "Probabilidade Média (%)"},
        ax=ax,
    )
    ax.set_title(f"Associação de Classes Reais com Tags Oficiais do Sidewalk ({split})", fontsize=13, pad=12)
    ax.set_ylabel("Classe Real do Dataset v3", fontsize=11)
    ax.set_xlabel("Tag do Project Sidewalk", fontsize=11)
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()

    if reports_dir:
        rep_path = Path(reports_dir)
        rep_path.mkdir(parents=True, exist_ok=True)
        caminho_fig = rep_path / f"tagger_heatmap_{split}.png"
        fig.savefig(caminho_fig, dpi=140)
        print(f"\n[Heatmap salvo em '{caminho_fig}']")

    plt.show()


def plotar_10_amostras_validator(df_pred, split="test", seed=None):
    """
    Exibe um grid 2x5 com 10 amostras reais sorteadas aleatoriamente do split.
    Se seed=None, sorteia 10 novas amostras a cada execução da célula.
    Mostra o crop da calçada, rótulo humano, e a predição binária do Sidewalk Validator.
    """
    df_s = df_pred[df_pred["split"] == split].copy() if split else df_pred.copy()
    if len(df_s) < 10:
        amostras = df_s
    else:
        amostras = df_s.sample(n=10, random_state=seed)

    fig, axes = plt.subplots(2, 5, figsize=(20, 9.5), layout="constrained")
    axes = axes.flatten()
    fig.suptitle("Amostras Aleatórias — sidewalk-validator-ai-surfaceproblem", fontsize=15, weight="bold")

    for i, (_, row) in enumerate(amostras.iterrows()):
        ax = axes[i]
        try:
            img = Image.open(row["image_path"]).convert("RGB")
            ax.imshow(img)
        except Exception:
            ax.imshow(np.full((224, 224, 3), 200, dtype=np.uint8))
        ax.axis("off")

        rua_curta = row["rua"].replace("avenida-", "av. ").replace("rua-", "r. ")[:20]
        real_cls = row["label_nome"]
        v_pred = row["validator_pred"]
        v_conf = row["validator_conf"]

        # Legenda amigável
        pred_legenda = "Com Defeito (correct)" if v_pred == "correct" else "Sem Defeito (incorrect)"

        # Coerência esperada: Adequada -> incorrect | Inadequada/Parcial -> correct
        if real_cls == "Adequada":
            coerente = v_pred == "incorrect"
        elif real_cls in ["Inadequada", "Parcialmente Adequado"]:
            coerente = v_pred == "correct"
        else:
            coerente = None

        if coerente is True:
            cor = "forestgreen"
            tag_status = "[ALINHADO]"
        elif coerente is False:
            cor = "crimson"
            tag_status = "[DIVERGENTE]"
        else:
            cor = "darkgoldenrod"
            tag_status = "[NEUTRO]"

        ax.set_title(
            f"{tag_status} {rua_curta}\nReal: {real_cls}\nSidewalk: {pred_legenda} ({v_conf:.1%})",
            color=cor,
            fontsize=10.5,
            weight="bold",
            pad=8,
        )

    plt.show()


def plotar_10_amostras_tagger(df_pred, split="test", seed=None):
    """
    Exibe um grid 2x5 com 10 amostras reais sorteadas aleatoriamente do split.
    Se seed=None, sorteia 10 novas amostras a cada execução da célula.
    Mostra o crop da calçada, rótulo humano, e as 3 principais tags preditas pelo Tagger.
    """
    df_s = df_pred[df_pred["split"] == split].copy() if split else df_pred.copy()
    if len(df_s) < 10:
        amostras = df_s
    else:
        amostras = df_s.sample(n=10, random_state=seed)

    fig, axes = plt.subplots(2, 5, figsize=(20, 10.5), layout="constrained")
    axes = axes.flatten()
    fig.suptitle("Amostras Aleatórias — sidewalk-tagger-ai-surfaceproblem (Top 3 Tags)", fontsize=15, weight="bold")

    for i, (_, row) in enumerate(amostras.iterrows()):
        ax = axes[i]
        try:
            img = Image.open(row["image_path"]).convert("RGB")
            ax.imshow(img)
        except Exception:
            ax.imshow(np.full((224, 224, 3), 200, dtype=np.uint8))
        ax.axis("off")

        rua_curta = row["rua"].replace("avenida-", "av. ").replace("rua-", "r. ")[:20]
        real_cls = row["label_nome"]

        t1 = f"1. {row['tagger_top1_name']}: {row['tagger_top1_prob']:.1%}"
        t2 = f"2. {row['tagger_top2_name']}: {row['tagger_top2_prob']:.1%}"
        t3 = f"3. {row['tagger_top3_name']}: {row['tagger_top3_prob']:.1%}"

        ax.set_title(
            f"{rua_curta}\nReal: {real_cls}\n{t1}\n{t2}\n{t3}",
            color="navy",
            fontsize=10.5,
            weight="bold",
            pad=8,
        )

    plt.show()


__all__ = [
    "VALIDATOR_MODEL_ID",
    "TAGGER_REPO_ID",
    "TAGGER_FILENAME",
    "SIDEWALK_TAGS",
    "VALID_TAGS",
    "carregar_validator_hf",
    "carregar_tagger_hf",
    "executar_ou_carregar_predicoes",
    "avaliar_validator",
    "avaliar_tagger",
    "plotar_10_amostras_validator",
    "plotar_10_amostras_tagger",
]

