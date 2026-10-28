import json
import os
import numpy as np

# Catálogo consolidado das principais taxonomias validadas no projeto
TAXONOMIAS = {
    "5_classes_original": {
        "descricao": "5 Classes Originais (Adequada, Parcial, Inadequada, Sem calçada, Não identificável)",
        "nomes": ["Adequada", "Parcial", "Inadequada", "Sem calçada", "Não id."],
        "mapa": {0: 0, 1: 1, 2: 2, 3: 3, 4: 4},
    },
    "4_classes_com_naoid": {
        "descricao": "4 Classes (Adequada, Parcial, Inadequada + Sem calçada unidas, Não identificável)",
        "nomes": ["Adequada", "Parcial", "Inad.+SemCalçada", "Não id."],
        "mapa": {0: 0, 1: 1, 2: 2, 3: 2, 4: 3},
    },
    "3_classes_sem_naoid": {
        "descricao": "3 Classes sem Não identificável (Adequada, Com Defeito [Parcial+Inadequada], Sem calçada)",
        "nomes": ["Adequada", "Com Defeito", "Sem calçada"],
        "mapa": {0: 0, 1: 1, 2: 1, 3: 2},
    },
    "3_classes_com_naoid": {
        "descricao": "3 Classes com Não identificável (Adequada, Inadequada Geral [Parcial+Inadequada+Sem calçada], Não id.)",
        "nomes": ["Adequada", "Inadequada Geral", "Não id."],
        "mapa": {0: 0, 1: 1, 2: 1, 3: 1, 4: 2},
    },
    "2_classes_sem_naoid": {
        "descricao": "2 Classes Binária Crítica (Transitável [Adequada+Parcial] vs Crítica [Inadequada+Sem calçada])",
        "nomes": ["Transitável", "Crítica (Inad+SemCalc)"],
        "mapa": {0: 0, 1: 0, 2: 1, 3: 1},
    },
}


def carregar_dados(data_dir="data/processed/apx2-bzsou-v3", raw_dir="data/raw/apx2-bzsou-v3"):
    """
    Carrega os vetores de features e rótulos de treino, validação e teste (.npy),
    além da lista ordenada de caminhos absolutos/relativos das imagens de teste
    conforme anotadas no arquivo COCO.
    """
    X_train = np.load(os.path.join(data_dir, "train_features.npy"))
    y_train = np.load(os.path.join(data_dir, "train_labels.npy"))
    X_valid = np.load(os.path.join(data_dir, "valid_features.npy"))
    y_valid = np.load(os.path.join(data_dir, "valid_labels.npy"))
    X_test = np.load(os.path.join(data_dir, "test_features.npy"))
    y_test = np.load(os.path.join(data_dir, "test_labels.npy"))

    coco_test_path = os.path.join(raw_dir, "test", "_annotations.coco.json")
    with open(coco_test_path, "r", encoding="utf-8") as f:
        coco_test = json.load(f)

    # Mapeia na mesma ordem exata em que extract_features.py percorreu coco_data["images"]
    img_to_cats = {}
    for ann in coco_test.get("annotations", []):
        img_to_cats.setdefault(ann["image_id"], set()).add(ann["category_id"])

    test_paths = []
    for img_info in coco_test["images"]:
        if img_to_cats.get(img_info["id"]):
            test_paths.append(os.path.join(raw_dir, "test", img_info["file_name"]))

    return {
        "X_train": X_train,
        "y_train": y_train,
        "X_valid": X_valid,
        "y_valid": y_valid,
        "X_test": X_test,
        "y_test": y_test,
        "test_paths": np.array(test_paths),
    }


def aplicar_taxonomia(X, y, mapa, paths=None):
    """
    Filtra amostras pertencentes às classes presentes nas chaves de `mapa`
    e remapeia seus índices de rótulo para os novos valores.
    Suporta opcionalmente sincronizar um array de caminhos de imagens `paths`.
    """
    mask = np.isin(y, list(mapa.keys()))
    X_f = X[mask]
    y_f = np.array([mapa[val] for val in y[mask]], dtype=int)
    if paths is not None:
        return X_f, y_f, paths[mask]
    return X_f, y_f


def balancear_undersampling(X, y, teto=None, seed=42):
    """
    Aplica undersampling nas classes majoritárias para limitar o número de amostras
    ao `teto` fornecido, reduzindo viés sem descartar dados das classes minoritárias.
    Retorna os arrays balanceados e permutados aleatoriamente.
    """
    if not teto:
        return X, y
    rng = np.random.RandomState(seed)
    classes = np.unique(y)
    X_l, y_l = [], []
    for c in classes:
        idx = np.where(y == c)[0]
        chosen = rng.choice(idx, size=teto, replace=False) if len(idx) > teto else idx
        X_l.append(X[chosen])
        y_l.append(y[chosen])
    X_b, y_b = np.vstack(X_l), np.concatenate(y_l)
    perm = rng.permutation(len(y_b))
    return X_b[perm], y_b[perm]


def selecionar_indices_estratificados(y, n_total=10, seed=42):
    """
    Seleciona `n_total` índices garantindo representatividade estratificada
    (round-robin balanceado) de todas as classes presentes em `y`.
    Útil para amostragens visuais justas em relatórios e notebooks.
    """
    rng = np.random.RandomState(seed)
    classes = np.unique(y)
    por_classe = {c: list(rng.permutation(np.where(y == c)[0])) for c in classes}

    escolhidos = []
    rodada = 0
    while len(escolhidos) < min(n_total, len(y)):
        adicionou = False
        for c in classes:
            if rodada < len(por_classe[c]) and len(escolhidos) < n_total:
                escolhidos.append(por_classe[c][rodada])
                adicionou = True
        if not adicionou:
            break
        rodada += 1
    return escolhidos

