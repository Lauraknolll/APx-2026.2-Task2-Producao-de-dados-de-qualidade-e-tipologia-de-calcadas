import glob
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
import torch.nn as nn
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

# Índices e nomes das 11 tags puras de defeito/obstáculo (sem 'brick/cobblestone' e sem 'NULL')
INDICES_SEM_BRICK = [i for i, tag in enumerate(SIDEWALK_TAGS) if tag not in ("brick/cobblestone", "NULL")]
TAGS_SEM_BRICK = [SIDEWALK_TAGS[i] for i in INDICES_SEM_BRICK]


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
    output_dir="data/reports/avaliacao_sidewalk_nativo",
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


def criar_tagger_sem_brick(repo_id=TAGGER_REPO_ID, filename=TAGGER_FILENAME, device=None):
    """
    Carrega o modelo sidewalk-tagger-ai-surfaceproblem e realiza a remoção cirúrgica
    da classe 'brick/cobblestone' (índice 0) e do placeholder 'NULL' (índice 9) na
    cabeça classificadora (Linear(256, 13) -> Linear(256, 11)), preservando os pesos
    pré-treinados das 11 tags reais de defeito/obstáculo.
    """
    transform, model, device = carregar_tagger_hf(repo_id=repo_id, filename=filename, device=device)

    old_out = model.classifier[2]
    new_out = nn.Linear(old_out.in_features, len(INDICES_SEM_BRICK))
    with torch.no_grad():
        new_out.weight.copy_(old_out.weight[INDICES_SEM_BRICK])
        new_out.bias.copy_(old_out.bias[INDICES_SEM_BRICK])

    model.classifier[2] = new_out.to(device)
    model.eval()
    return transform, model, device


def _carregar_ou_extrair_embeddings_tagger(
    raw_dir="data/raw/apx2-bzsou-v3",
    processed_dir="data/processed/apx2-bzsou-v3",
    device=None,
):
    """
    Carrega do cache (ou extrai do backbone DINOv2-Base do Tagger caso não exista)
    os embeddings de 768 dimensões e os scores das 12 tags originais para train, valid e test.
    Salva o arquivo compactado em processed_dir (ignorado no git).
    """
    proc_path = Path(processed_dir)
    proc_path.mkdir(parents=True, exist_ok=True)
    npz_file = proc_path / "features_hibridas_v3.npz"

    if npz_file.exists():
        return dict(np.load(npz_file, allow_pickle=True))

    if device is None:
        device = get_device()
    _, t_model, _ = carregar_tagger_hf(device=device)
    t_trans_fast = T.Compose([
        T.Resize(266),
        T.CenterCrop(266),
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    idx_valid = [i for i, tag in enumerate(SIDEWALK_TAGS) if tag != "NULL"]

    dados = {"tag_names": np.array(VALID_TAGS)}
    for split in ("train", "valid", "test"):
        df_s = listar_imagens_coco(raw_dir=raw_dir, splits=(split,))
        embs, tags, labels, paths = [], [], [], []
        batch_tensors, batch_meta = [], []

        for _, row in tqdm(df_s.iterrows(), total=len(df_s), desc=f"Extraindo DINOv2 Tagger ({split})"):
            try:
                img = Image.open(row["image_path"]).convert("RGB")
                batch_tensors.append(t_trans_fast(img))
                batch_meta.append((int(row["label_id"]), row["image_path"]))
            except Exception as e:
                print(f"Aviso ao abrir {row['image_path']}: {e}")
                continue

            if len(batch_tensors) == 16:
                bt = torch.stack(batch_tensors).to(device)
                with torch.no_grad():
                    feat = t_model.transformer(bt)
                    feat_norm = t_model.transformer.norm(feat)
                    probs = torch.sigmoid(t_model.classifier(feat_norm))[:, idx_valid]
                embs.append(feat_norm.cpu().numpy())
                tags.append(probs.cpu().numpy())
                for lid, pth in batch_meta:
                    labels.append(lid)
                    paths.append(pth)
                batch_tensors, batch_meta = [], []

        if batch_tensors:
            bt = torch.stack(batch_tensors).to(device)
            with torch.no_grad():
                feat = t_model.transformer(bt)
                feat_norm = t_model.transformer.norm(feat)
                probs = torch.sigmoid(t_model.classifier(feat_norm))[:, idx_valid]
            embs.append(feat_norm.cpu().numpy())
            tags.append(probs.cpu().numpy())
            for lid, pth in batch_meta:
                labels.append(lid)
                paths.append(pth)

        dados[f"X_{split}_emb"] = np.vstack(embs).astype(np.float32)
        dados[f"X_{split}_tags"] = np.vstack(tags).astype(np.float32)
        dados[f"y_{split}"] = np.array(labels, dtype=np.int64)
        dados[f"{split}_paths"] = np.array(paths)

    np.savez_compressed(npz_file, **dados)
    return dados


def finetunar_tagger_curitiba(
    raw_dir="data/raw/apx2-bzsou-v3",
    output_dir="data/reports/avaliacao_sidewalk_nativo",
    processed_dir="data/processed/apx2-bzsou-v3",
    epochs=35,
    lr=1.5e-3,
    forcar_retreino=False,
    device=None,
):
    """
    Executa o fine-tuning leve da cabeça classificadora do sidewalk-tagger-ai (sem 'brick/cobblestone')
    usando os dados de treino do dataset v3 de Curitiba com Supervisão Fraca + Pseudo-Labels:
      - Calçadas 'Adequada' (id=0): Target = [0, 0, ..., 0] nas 11 tags (ensina que o petit-pavé íntegro não é defeito).
      - Calçadas com defeito ('Inadequada', 'Parcialmente Adequado', 'Sem calçada'): Target baseado nas
        ativações do modelo original (Teacher) para preservar a capacidade de diagnosticar os 11 defeitos.
      - 'Não identificável' (id=2): Ignorada no treinamento para não introduzir ruído visual.
    Salva o checkpoint ajustado em processed_dir e as predições tabulares em output_dir.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    proc_path = Path(processed_dir)
    proc_path.mkdir(parents=True, exist_ok=True)

    csv_file = out_path / "predicoes_tagger_finetuned_v3.csv"
    json_file = out_path / "predicoes_tagger_finetuned_v3.json"
    pth_out = proc_path / "tagger_curitiba_sem_brick.pth"

    if csv_file.exists() and pth_out.exists() and not forcar_retreino:
        print(f"Carregando predições do Tagger Fine-Tunado (sem 'brick/cobblestone') de '{csv_file}'...")
        return pd.read_csv(csv_file)

    dados = _carregar_ou_extrair_embeddings_tagger(raw_dir=raw_dir, processed_dir=processed_dir, device=device)
    X_train_emb = dados["X_train_emb"]
    X_train_tags = dados["X_train_tags"]
    y_train = dados["y_train"]

    # Carrega os pesos originais da cabeça classificadora do Tagger no cache do HF
    pths = glob.glob(
        os.path.expanduser("~/.cache/huggingface/hub/models--projectsidewalk--sidewalk-tagger-ai-surfaceproblem/**/*.pth"),
        recursive=True,
    )
    if pths:
        pth_orig = pths[0]
    else:
        pth_orig = hf_hub_download(repo_id=TAGGER_REPO_ID, filename=TAGGER_FILENAME)

    state = torch.load(pth_orig, map_location="cpu", weights_only=False)
    sd = state.get("model_state_dict", state)

    # Instancia a cabeça com 11 classes (removendo 'brick/cobblestone' e 'NULL')
    head = nn.Sequential(
        nn.Linear(768, 256),
        nn.ReLU(),
        nn.Linear(256, len(TAGS_SEM_BRICK)),
    )
    with torch.no_grad():
        head[0].weight.copy_(sd["classifier.0.weight"])
        head[0].bias.copy_(sd["classifier.0.bias"])
        head[2].weight.copy_(sd["classifier.2.weight"][INDICES_SEM_BRICK])
        head[2].bias.copy_(sd["classifier.2.bias"][INDICES_SEM_BRICK])

    # Filtra 'Não identificável' (id=2) do split de treino
    mask_tr = y_train != 2
    X_tr = torch.tensor(X_train_emb[mask_tr], dtype=torch.float32)
    y_tr_cls = y_train[mask_tr]
    # X_train_tags possui 12 colunas (0 = brick/cobblestone, 1..11 = TAGS_SEM_BRICK)
    P_tr_teacher = X_train_tags[mask_tr][:, 1:]

    Y_target = np.zeros_like(P_tr_teacher)
    W_tr = torch.ones((len(y_tr_cls), 1), dtype=torch.float32)

    n_adequadas = int((y_tr_cls == 0).sum())
    n_defeitos = int((y_tr_cls != 0).sum())
    print(
        f"Iniciando Fine-Tuning Leve do Tagger (11 tags sem 'brick/cobblestone') em {len(y_tr_cls)} amostras de treino "
        f"({n_adequadas} Adequadas [target=0] | {n_defeitos} Com Defeito [pseudo-labels Teacher])..."
    )

    for i, c in enumerate(y_tr_cls):
        if c == 0:  # Adequada -> Nenhuma tag de defeito deve disparar
            Y_target[i] = 0.0
            W_tr[i] = 1.0
        else:  # Inadequada (1), Parcialmente Adequado (3), Sem calçada (4)
            t = P_tr_teacher[i].copy()
            top_idx = np.argsort(t)[-3:]
            for idx_top in top_idx:
                if t[idx_top] > 0.03:
                    t[idx_top] = min(1.0, t[idx_top] * 2.5)
            # Preserva sensibilidade a 'very broken' (índice 10) em calçadas Inadequadas e Sem calçada
            if c in (1, 4) and t[10] > 0.005:
                t[10] = min(1.0, max(t[10] * 5.0, 0.55))
            if t.max() < 0.5:
                t[np.argmax(P_tr_teacher[i])] = 0.75
            Y_target[i] = t
            W_tr[i] = 1.6

    Y_tr = torch.tensor(Y_target, dtype=torch.float32)

    torch.manual_seed(42)
    optimizer = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=1e-3)
    criterion = nn.BCEWithLogitsLoss(reduction="none")

    head.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        logits = head(X_tr)
        loss = (criterion(logits, Y_tr) * W_tr).mean()
        loss.backward()
        optimizer.step()

    head.eval()
    torch.save(
        {
            "classifier_state_dict": head.state_dict(),
            "tags": TAGS_SEM_BRICK,
            "indices_originais": INDICES_SEM_BRICK,
        },
        pth_out,
    )

    # Gera predições em todos os splits mantendo vínculo com as imagens originais
    df_imagens = listar_imagens_coco(raw_dir=raw_dir, splits=("test", "valid", "train"))
    mapa_emb = {}
    for split in ("test", "valid", "train"):
        paths_s = dados[f"{split}_paths"]
        embs_s = dados[f"X_{split}_emb"]
        for p, e in zip(paths_s, embs_s):
            mapa_emb[str(p)] = e

    registros = []
    with torch.no_grad():
        for _, row in df_imagens.iterrows():
            img_path = str(row["image_path"])
            if img_path not in mapa_emb:
                continue
            emb_t = torch.tensor(mapa_emb[img_path], dtype=torch.float32).unsqueeze(0)
            probs = torch.sigmoid(head(emb_t)).squeeze(0).numpy()

            tags_ordenadas = sorted(
                [(TAGS_SEM_BRICK[i], float(probs[i])) for i in range(len(TAGS_SEM_BRICK))],
                key=lambda x: x[1],
                reverse=True,
            )

            reg = {
                "split": row["split"],
                "image_id": row["image_id"],
                "file_name": row["file_name"],
                "original_name": row["original_name"],
                "rua": row["rua"],
                "image_path": row["image_path"],
                "label_id": row["label_id"],
                "label_nome": row["label_nome"],
                "tagger_ft_top1_name": tags_ordenadas[0][0],
                "tagger_ft_top1_prob": round(tags_ordenadas[0][1], 4),
                "tagger_ft_top2_name": tags_ordenadas[1][0],
                "tagger_ft_top2_prob": round(tags_ordenadas[1][1], 4),
                "tagger_ft_top3_name": tags_ordenadas[2][0],
                "tagger_ft_top3_prob": round(tags_ordenadas[2][1], 4),
            }
            for i, tag_name in enumerate(TAGS_SEM_BRICK):
                col_name = "tag_ft_" + tag_name.replace("/", "_").replace(" ", "_")
                reg[col_name] = round(float(probs[i]), 4)

            registros.append(reg)

    df_ft = pd.DataFrame(registros)
    df_ft.to_csv(csv_file, index=False, encoding="utf-8")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(df_ft.to_dict(orient="records"), f, indent=2, ensure_ascii=False)

    print(f"Checkpoint e predições do Tagger Fine-Tunado salvos em:\n -> {pth_out}\n -> {csv_file}")
    return df_ft


def comparar_tagger_antes_depois(
    df_original,
    df_finetuned,
    split="test",
    reports_dir="data/reports/avaliacao_sidewalk_nativo",
):
    """
    Compara quantitativamente e visualmente (Heatmaps lado a lado) as probabilidades médias
    de ativação das tags do Sidewalk Tagger ANTES (12 tags originais com 'brick/cobblestone')
    e DEPOIS do Fine-Tuning em Curitiba (11 tags de defeito sem 'brick/cobblestone').
    """
    df_orig_s = df_original[df_original["split"] == split].copy() if split else df_original.copy()
    df_ft_s = df_finetuned[df_finetuned["split"] == split].copy() if split else df_finetuned.copy()

    cols_orig = [c for c in df_orig_s.columns if c.startswith("tag_") and not c.startswith("tag_ft_")]
    mapa_orig = {c: c.replace("tag_", "").replace("_", " ") for c in cols_orig}
    medias_orig = df_orig_s.groupby("label_nome")[cols_orig].mean().rename(columns=mapa_orig) * 100

    cols_ft = [c for c in df_ft_s.columns if c.startswith("tag_ft_")]
    mapa_ft = {c: c.replace("tag_ft_", "").replace("_", " ") for c in cols_ft}
    medias_ft = df_ft_s.groupby("label_nome")[cols_ft].mean().rename(columns=mapa_ft) * 100

    print("=" * 95)
    print(f"COMPARATIVO SIDEWALK TAGGER: ANTES vs DEPOIS DO FINE-TUNING (Split: {split.upper()} — {len(df_ft_s)} amostras)")
    print("=" * 95)

    resumo = pd.DataFrame({
        "Antes: brick/cobblestone (%)": medias_orig.get("brick cobblestone", pd.Series(dtype=float)).round(1),
        "Antes: cracks (%)": medias_orig["cracks"].round(1),
        "Depois: cracks (%)": medias_ft["cracks"].round(1),
        "Antes: bumpy (%)": medias_orig["bumpy"].round(1),
        "Depois: bumpy (%)": medias_ft["bumpy"].round(1),
        "Antes: grass (%)": medias_orig["grass"].round(1),
        "Depois: grass (%)": medias_ft["grass"].round(1),
        "Depois: height diff (%)": medias_ft["height difference"].round(1),
        "Depois: very broken (%)": medias_ft["very broken"].round(1),
    })
    print("\n--- Resumo das Principais Mudanças na Confiança Média (%) ---")
    print(resumo.to_string())

    fig, axes = plt.subplots(1, 2, figsize=(20, 6), layout="constrained")

    sns.heatmap(
        medias_orig,
        annot=True,
        fmt=".1f",
        cmap="YlGnBu",
        vmin=0,
        vmax=70,
        cbar=False,
        ax=axes[0],
    )
    axes[0].set_title("ANTES: Tagger Original (12 Tags — Com 'brick/cobblestone')", fontsize=12.5, weight="bold", pad=10)
    axes[0].set_ylabel("Classe Real do Dataset v3", fontsize=11)
    axes[0].set_xlabel("Tag do Project Sidewalk", fontsize=11)
    axes[0].tick_params(axis="x", rotation=35)

    sns.heatmap(
        medias_ft,
        annot=True,
        fmt=".1f",
        cmap="YlGnBu",
        vmin=0,
        vmax=70,
        cbar_kws={"label": "Probabilidade Média (%)"},
        ax=axes[1],
    )
    axes[1].set_title(
        "DEPOIS: Tagger Fine-Tunado em Curitiba (11 Tags — Sem 'brick/cobblestone')",
        fontsize=12.5,
        weight="bold",
        pad=10,
    )
    axes[1].set_ylabel("")
    axes[1].set_xlabel("Tag de Defeito do Project Sidewalk", fontsize=11)
    axes[1].tick_params(axis="x", rotation=35)

    if reports_dir:
        rep_path = Path(reports_dir)
        rep_path.mkdir(parents=True, exist_ok=True)
        fig_path = rep_path / f"tagger_comparativo_finetuning_{split}.png"
        fig.savefig(fig_path, dpi=140)
        print(f"\n[Heatmap comparativo salvo em '{fig_path}']")

    plt.show()


def plotar_10_amostras_tagger_finetuned(df_finetuned, split="test", seed=None):
    """
    Exibe um grid 2x5 com 10 amostras reais sorteadas aleatoriamente do split.
    Se seed=None, sorteia 10 novas amostras a cada execução da célula.
    Mostra o crop da calçada, o rótulo humano e as Top 3 tags preditas pelo Tagger Fine-Tunado (sem brick).
    """
    df_s = df_finetuned[df_finetuned["split"] == split].copy() if split else df_finetuned.copy()
    if len(df_s) < 10:
        amostras = df_s
    else:
        amostras = df_s.sample(n=10, random_state=seed)

    fig, axes = plt.subplots(2, 5, figsize=(20, 10.5), layout="constrained")
    axes = axes.flatten()
    fig.suptitle(
        "Amostras Aleatórias — Sidewalk Tagger Fine-Tunado sem 'brick/cobblestone' (Top 3 Tags)",
        fontsize=15,
        weight="bold",
    )

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

        p1 = row["tagger_ft_top1_prob"]
        t1 = f"1. {row['tagger_ft_top1_name']}: {p1:.1%}"
        t2 = f"2. {row['tagger_ft_top2_name']}: {row['tagger_ft_top2_prob']:.1%}"
        t3 = f"3. {row['tagger_ft_top3_name']}: {row['tagger_ft_top3_prob']:.1%}"

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
    "INDICES_SEM_BRICK",
    "TAGS_SEM_BRICK",
    "carregar_validator_hf",
    "carregar_tagger_hf",
    "criar_tagger_sem_brick",
    "executar_ou_carregar_predicoes",
    "avaliar_validator",
    "avaliar_tagger",
    "plotar_10_amostras_validator",
    "plotar_10_amostras_tagger",
    "finetunar_tagger_curitiba",
    "comparar_tagger_antes_depois",
    "plotar_10_amostras_tagger_finetuned",
]

