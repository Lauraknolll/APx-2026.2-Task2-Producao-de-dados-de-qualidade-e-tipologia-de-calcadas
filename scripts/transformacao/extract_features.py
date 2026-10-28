import argparse
import os
import sys
import json
import torch
import numpy as np
from PIL import Image
from transformers import AutoImageProcessor, AutoModel
from tqdm import tqdm

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from scripts.utils.device import get_device


def process_split(split_name, base_dir, processor, model, device):
    split_dir = os.path.join(base_dir, split_name)
    json_path = os.path.join(split_dir, "_annotations.coco.json")

    if not os.path.exists(json_path):
        print(f"[{split_name}] Anotações não encontradas, pulando...")
        return None, None

    with open(json_path, "r", encoding="utf-8") as f:
        coco_data = json.load(f)

    # Mapear IDs das categorias
    cat_ids = {cat["name"]: cat["id"] for cat in coco_data.get("categories", [])}

    # Mapear categorias por imagem
    img_to_cats = {}
    for ann in coco_data.get("annotations", []):
        img_id = ann["image_id"]
        cat_id = ann["category_id"]
        img_to_cats.setdefault(img_id, set()).add(cat_id)

    features_list = []
    labels_list = []

    # Ordem de prioridade / mapeamento de 5 classes:
    # 0: Adequada
    # 1: Parcialmente Adequado
    # 2: Inadequada
    # 3: Sem calçada
    # 4: Não identificável
    id_nao = cat_ids.get("Nao identificavel")
    id_sem = cat_ids.get("Sem calcada")
    id_inadequada = cat_ids.get("Inadequada")
    id_parcial = cat_ids.get("Parcialmente Adequado")
    id_adequada = cat_ids.get("Adequada")

    print(f"Extraindo features em '{split_name}'...")
    for img_info in tqdm(coco_data["images"]):
        img_id = img_info["id"]
        cats = img_to_cats.get(img_id, set())
        if not cats:
            continue

        if id_nao and id_nao in cats:
            label = 4
        elif id_sem and id_sem in cats:
            label = 3
        elif id_inadequada and id_inadequada in cats:
            label = 2
        elif id_parcial and id_parcial in cats:
            label = 1
        elif id_adequada and id_adequada in cats:
            label = 0
        else:
            continue

        img_filename = img_info["file_name"]
        img_path = os.path.join(split_dir, img_filename)

        try:
            image = Image.open(img_path).convert("RGB")
            inputs = processor(images=image, return_tensors="pt").to(device)
            with torch.no_grad():
                outputs = model(**inputs)

            # Token [CLS] (índice 0) contém a representação global da imagem
            cls_token = outputs.last_hidden_state[:, 0, :].cpu().numpy()
            features_list.append(cls_token)
            labels_list.append(label)
        except Exception as e:
            print(f"Erro processando {img_filename}: {e}")

    if not features_list:
        return None, None

    features_array = np.vstack(features_list)
    labels_array = np.array(labels_list)
    return features_array, labels_array


def main():
    parser = argparse.ArgumentParser(description="Extração de features DINOv2 a partir de anotações COCO.")
    parser.add_argument(
        "--dataset",
        default="data/raw/apx2-bzsou-v3",
        help="Caminho do dataset COCO (default: data/raw/apx2-bzsou-v3)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Diretório de saída para os arquivos .npy (default: data/processed/<nome_dataset>)",
    )
    parser.add_argument(
        "--model",
        default="projectsidewalk/sidewalk-validator-ai-surfaceproblem",
        help="ID do modelo no HuggingFace (default: projectsidewalk/sidewalk-validator-ai-surfaceproblem)",
    )
    args = parser.parse_args()

    dataset_dir = args.dataset
    output_dir = args.output or os.path.join("data", "processed", os.path.basename(dataset_dir))

    if not os.path.exists(dataset_dir):
        print(f"[ERRO] Diretório do dataset não encontrado em '{dataset_dir}'!")
        return

    os.makedirs(output_dir, exist_ok=True)

    device = get_device()
    print(f"Iniciando extração. Usando dispositivo: {device}")
    print(f"Carregando modelo '{args.model}' do HuggingFace...")

    processor = AutoImageProcessor.from_pretrained(args.model)
    model = AutoModel.from_pretrained(args.model).to(device)
    model.eval()

    splits = ["train", "valid", "test"]
    for split in splits:
        feat, lbl = process_split(split, dataset_dir, processor, model, device)
        if feat is not None:
            feat_path = os.path.join(output_dir, f"{split}_features.npy")
            lbl_path = os.path.join(output_dir, f"{split}_labels.npy")
            np.save(feat_path, feat)
            np.save(lbl_path, lbl)
            print(f"[{split}] Salvo: {feat.shape[0]} amostras, vetor {feat.shape[1]}D -> {output_dir}")

    print(f"\nExtração concluída! Vetores salvos em '{output_dir}'.")


if __name__ == "__main__":
    main()
