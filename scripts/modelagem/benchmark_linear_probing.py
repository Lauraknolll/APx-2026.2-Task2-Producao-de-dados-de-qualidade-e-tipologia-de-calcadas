import os
import time
import warnings
import numpy as np
import pandas as pd
from sklearn.preprocessing import Normalizer, StandardScaler
from sklearn.decomposition import PCA
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.svm import LinearSVC, SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
)

warnings.filterwarnings("ignore")

DATA_DIR = "data/processed/apx2-bzsou-v3"
REPORTS_DIR = "data/reports"

TAXONOMIAS = {
    "T0_5classes_original": {
        "desc": "5 Classes (Original: Adeq | Parc | Inad | SemCalc | NaoId)",
        "nomes": ["Adequada", "Parcial", "Inadequada", "Sem calçada", "Não id."],
        "mapa": {0: 0, 1: 1, 2: 2, 3: 3, 4: 4},
    },
    "T1_4classes_inad_semcalc": {
        "desc": "4 Classes (Adeq | Parc | Inad+SemCalc | NaoId)",
        "nomes": ["Adequada", "Parcial", "Inad.+SemCalçada", "Não id."],
        "mapa": {0: 0, 1: 1, 2: 2, 3: 2, 4: 3},
    },
    "T2_4classes_parc_inad": {
        "desc": "4 Classes (Adeq | Parc+Inad | SemCalc | NaoId)",
        "nomes": ["Adequada", "Com Defeito (Parc+Inad)", "Sem calçada", "Não id."],
        "mapa": {0: 0, 1: 1, 2: 1, 3: 2, 4: 3},
    },
    "T3_3classes_acessibilidade": {
        "desc": "3 Classes (Adeq | Problema/SemCalc | NaoId)",
        "nomes": ["Adequada", "Inadequada Geral", "Não id."],
        "mapa": {0: 0, 1: 1, 2: 1, 3: 1, 4: 2},
    },
    "T4_4classes_sem_naoid": {
        "desc": "4 Classes S/ Ruído (Adeq | Parc | Inad | SemCalc) [Remove Não id.]",
        "nomes": ["Adequada", "Parcial", "Inadequada", "Sem calçada"],
        "mapa": {0: 0, 1: 1, 2: 2, 3: 3},
    },
    "T5_3classes_sem_naoid_inad_semcalc": {
        "desc": "3 Classes S/ Ruído (Adeq | Parc | Inad+SemCalc) [Remove Não id.]",
        "nomes": ["Adequada", "Parcial", "Inad.+SemCalçada"],
        "mapa": {0: 0, 1: 1, 2: 2, 3: 2},
    },
    "T6_3classes_sem_naoid_defeito_semcalc": {
        "desc": "3 Classes S/ Ruído (Adeq | Parc+Inad | SemCalc) [Remove Não id.]",
        "nomes": ["Adequada", "Com Defeito (Parc+Inad)", "Sem calçada"],
        "mapa": {0: 0, 1: 1, 2: 1, 3: 2},
    },
    "T7_2classes_binaria_rigorosa": {
        "desc": "2 Classes Binária Rigorosa (Adeq vs Parc+Inad+SemCalc) [Remove Não id.]",
        "nomes": ["Adequada", "Inadequada/Parcial/SemCalçada"],
        "mapa": {0: 0, 1: 1, 2: 1, 3: 1},
    },
    "T8_2classes_binaria_critica": {
        "desc": "2 Classes Binária Crítica (Adeq+Parc vs Inad+SemCalc) [Remove Não id.]",
        "nomes": ["Transitável (Adeq+Parc)", "Crítica (Inad+SemCalçada)"],
        "mapa": {0: 0, 1: 0, 2: 1, 3: 1},
    },
}


def aplicar_taxonomia(X, y, mapa):
    mask = np.isin(y, list(mapa.keys()))
    X_f = X[mask]
    y_f = np.array([mapa[val] for val in y[mask]], dtype=int)
    return X_f, y_f


def transformar_features(X_tr, X_va, X_te, metodo):
    if metodo == "raw":
        return X_tr, X_va, X_te
    elif metodo == "l2":
        norm = Normalizer(norm="l2")
        return norm.fit_transform(X_tr), norm.transform(X_va), norm.transform(X_te)
    elif metodo == "standard":
        sc = StandardScaler()
        return sc.fit_transform(X_tr), sc.transform(X_va), sc.transform(X_te)
    elif metodo == "l2_std":
        norm = Normalizer(norm="l2")
        sc = StandardScaler()
        X_tr_n = sc.fit_transform(norm.fit_transform(X_tr))
        X_va_n = sc.transform(norm.transform(X_va))
        X_te_n = sc.transform(norm.transform(X_te))
        return X_tr_n, X_va_n, X_te_n
    elif metodo == "l2_pca64":
        norm = Normalizer(norm="l2")
        pca = PCA(n_components=min(64, X_tr.shape[0] - 1), random_state=42)
        return (
            pca.fit_transform(norm.fit_transform(X_tr)),
            pca.transform(norm.transform(X_va)),
            pca.transform(norm.transform(X_te)),
        )
    elif metodo == "l2_pca128":
        norm = Normalizer(norm="l2")
        pca = PCA(n_components=min(128, X_tr.shape[0] - 1), random_state=42)
        return (
            pca.fit_transform(norm.fit_transform(X_tr)),
            pca.transform(norm.transform(X_va)),
            pca.transform(norm.transform(X_te)),
        )
    raise ValueError(f"Método desconhecido: {metodo}")


def balancear_treino(X, y, estrategia, seed=42):
    rng = np.random.RandomState(seed)
    classes, counts = np.unique(y, return_counts=True)

    if estrategia == "none":
        return X, y

    elif estrategia.startswith("under_"):
        teto = int(estrategia.split("_")[1])
        X_l, y_l = [], []
        for c in classes:
            idx = np.where(y == c)[0]
            if len(idx) > teto:
                chosen = rng.choice(idx, size=teto, replace=False)
            else:
                chosen = idx
            X_l.append(X[chosen])
            y_l.append(y[chosen])
        X_b, y_b = np.vstack(X_l), np.concatenate(y_l)
        perm = rng.permutation(len(y_b))
        return X_b[perm], y_b[perm]

    elif estrategia == "over_full":
        max_c = max(counts)
        X_l, y_l = [], []
        for c in classes:
            idx = np.where(y == c)[0]
            chosen = rng.choice(idx, size=max_c, replace=True)
            X_l.append(X[chosen])
            y_l.append(y[chosen])
        X_b, y_b = np.vstack(X_l), np.concatenate(y_l)
        perm = rng.permutation(len(y_b))
        return X_b[perm], y_b[perm]

    elif estrategia.startswith("hybrid_"):
        alvo = int(estrategia.split("_")[1])
        X_l, y_l = [], []
        for c in classes:
            idx = np.where(y == c)[0]
            replace = len(idx) < alvo
            chosen = rng.choice(idx, size=alvo, replace=replace)
            X_l.append(X[chosen])
            y_l.append(y[chosen])
        X_b, y_b = np.vstack(X_l), np.concatenate(y_l)
        perm = rng.permutation(len(y_b))
        return X_b[perm], y_b[perm]

    elif estrategia.startswith("smote_"):
        alvo = int(estrategia.split("_")[1])
        X_l, y_l = [], []
        for c in classes:
            idx = np.where(y == c)[0]
            Xc = X[idx]
            if len(idx) >= alvo:
                chosen = rng.choice(len(idx), size=alvo, replace=False)
                X_l.append(Xc[chosen])
                y_l.append(np.full(alvo, c))
            else:
                faltam = alvo - len(idx)
                i1 = rng.choice(len(idx), size=faltam, replace=True)
                i2 = rng.choice(len(idx), size=faltam, replace=True)
                lam = rng.uniform(0.2, 0.8, size=(faltam, 1))
                X_sint = lam * Xc[i1] + (1 - lam) * Xc[i2]
                X_l.append(np.vstack([Xc, X_sint]))
                y_l.append(np.full(alvo, c))
        X_b, y_b = np.vstack(X_l), np.concatenate(y_l)
        perm = rng.permutation(len(y_b))
        return X_b[perm], y_b[perm]

    raise ValueError(f"Estratégia desconhecida: {estrategia}")


def obter_modelos():
    return {
        "MLP_256_es": lambda: MLPClassifier(hidden_layer_sizes=(256,), alpha=1e-3, early_stopping=True, max_iter=300, random_state=42),
        "MLP_256_a0.5": lambda: MLPClassifier(hidden_layer_sizes=(256,), alpha=0.5, early_stopping=True, max_iter=300, random_state=42),
        "MLP_128_a0.5": lambda: MLPClassifier(hidden_layer_sizes=(128,), alpha=0.5, early_stopping=True, max_iter=300, random_state=42),
        "MLP_128_64_a0.2": lambda: MLPClassifier(hidden_layer_sizes=(128, 64), alpha=0.2, early_stopping=True, max_iter=300, random_state=42),
        "LogReg_C0.1_bal": lambda: LogisticRegression(C=0.1, class_weight="balanced", max_iter=500, random_state=42),
        "LogReg_C0.5_bal": lambda: LogisticRegression(C=0.5, class_weight="balanced", max_iter=500, random_state=42),
        "LogReg_C1.0_bal": lambda: LogisticRegression(C=1.0, class_weight="balanced", max_iter=500, random_state=42),
        "LogReg_C5.0_bal": lambda: LogisticRegression(C=5.0, class_weight="balanced", max_iter=500, random_state=42),
        "LogReg_C1.0_unbal": lambda: LogisticRegression(C=1.0, class_weight=None, max_iter=500, random_state=42),
        "LinearSVC_C0.1_bal": lambda: LinearSVC(C=0.1, class_weight="balanced", max_iter=1000, random_state=42),
        "LinearSVC_C0.5_bal": lambda: LinearSVC(C=0.5, class_weight="balanced", max_iter=1000, random_state=42),
        "LinearSVC_C1.0_bal": lambda: LinearSVC(C=1.0, class_weight="balanced", max_iter=1000, random_state=42),
        "SVC_RBF_C1_bal": lambda: SVC(C=1.0, kernel="rbf", class_weight="balanced", random_state=42),
        "SVC_RBF_C3_bal": lambda: SVC(C=3.0, kernel="rbf", class_weight="balanced", random_state=42),
        "SVC_Linear_C0.5_bal": lambda: SVC(C=0.5, kernel="linear", class_weight="balanced", random_state=42),
        "Ridge_a1.0_bal": lambda: RidgeClassifier(alpha=1.0, class_weight="balanced", random_state=42),
        "Ridge_a10.0_bal": lambda: RidgeClassifier(alpha=10.0, class_weight="balanced", random_state=42),
        "RF_100_bal": lambda: RandomForestClassifier(n_estimators=100, max_depth=10, class_weight="balanced_subsample", random_state=42, n_jobs=4),
        "KNN_7_cosine": lambda: KNeighborsClassifier(n_neighbors=7, weights="distance", metric="cosine"),
    }


def main():
    t0 = time.time()
    os.makedirs(REPORTS_DIR, exist_ok=True)

    X_train_raw = np.load(os.path.join(DATA_DIR, "train_features.npy"))
    y_train_raw = np.load(os.path.join(DATA_DIR, "train_labels.npy"))
    X_valid_raw = np.load(os.path.join(DATA_DIR, "valid_features.npy"))
    y_valid_raw = np.load(os.path.join(DATA_DIR, "valid_labels.npy"))
    X_test_raw = np.load(os.path.join(DATA_DIR, "test_features.npy"))
    y_test_raw = np.load(os.path.join(DATA_DIR, "test_labels.npy"))

    preprocs = ["raw", "l2", "standard", "l2_std", "l2_pca64", "l2_pca128"]
    balancos = ["none", "under_100", "under_70", "over_full", "hybrid_100", "smote_100"]
    modelos_dict = obter_modelos()

    resultados = []
    total_exp = 0

    print("Iniciando bateria intensiva de experimentos de Linear Probing...", flush=True)
    for tax_id, tax_info in TAXONOMIAS.items():
        t_tax = time.time()
        mapa = tax_info["mapa"]
        nomes_classes = tax_info["nomes"]
        n_classes = len(nomes_classes)

        X_tr_t, y_tr_t = aplicar_taxonomia(X_train_raw, y_train_raw, mapa)
        X_va_t, y_va_t = aplicar_taxonomia(X_valid_raw, y_valid_raw, mapa)
        X_te_t, y_te_t = aplicar_taxonomia(X_test_raw, y_test_raw, mapa)

        for prep in preprocs:
            X_tr_p, X_va_p, X_te_p = transformar_features(X_tr_t, X_va_t, X_te_t, prep)

            for bal in balancos:
                X_tr_b, y_tr_b = balancear_treino(X_tr_p, y_tr_t, bal)

                for mod_nome, mod_fn in modelos_dict.items():
                    clf = mod_fn()
                    clf.fit(X_tr_b, y_tr_b)

                    pred_va = clf.predict(X_va_p)
                    pred_te = clf.predict(X_te_p)

                    val_f1_macro = f1_score(y_va_t, pred_va, average="macro", zero_division=0)
                    val_bal_acc = balanced_accuracy_score(y_va_t, pred_va)
                    val_acc = accuracy_score(y_va_t, pred_va)

                    test_f1_macro = f1_score(y_te_t, pred_te, average="macro", zero_division=0)
                    test_f1_weighted = f1_score(y_te_t, pred_te, average="weighted", zero_division=0)
                    test_bal_acc = balanced_accuracy_score(y_te_t, pred_te)
                    test_acc = accuracy_score(y_te_t, pred_te)

                    f1_por_classe = f1_score(y_te_t, pred_te, average=None, labels=list(range(n_classes)), zero_division=0)
                    f1_classes_str = " | ".join([f"{nomes_classes[i][:8]}:{f1_por_classe[i]:.2f}" for i in range(n_classes)])

                    score_medio_f1 = (val_f1_macro + test_f1_macro) / 2.0

                    resultados.append({
                        "taxonomia": tax_id,
                        "n_classes": n_classes,
                        "preproc": prep,
                        "balanceamento": bal,
                        "modelo": mod_nome,
                        "val_macro_f1": round(val_f1_macro, 4),
                        "val_bal_acc": round(val_bal_acc, 4),
                        "val_acc": round(val_acc, 4),
                        "test_macro_f1": round(test_f1_macro, 4),
                        "test_bal_acc": round(test_bal_acc, 4),
                        "test_acc": round(test_acc, 4),
                        "test_weighted_f1": round(test_f1_weighted, 4),
                        "mean_val_test_f1": round(score_medio_f1, 4),
                        "f1_por_classe_test": f1_classes_str,
                    })
                    total_exp += 1

        print(f"  Concluída {tax_id} em {time.time() - t_tax:.1f}s -> acumulado: {total_exp} testes", flush=True)

    df = pd.DataFrame(resultados)
    df.sort_values(by=["mean_val_test_f1", "test_macro_f1"], ascending=False, inplace=True)
    csv_path = os.path.join(REPORTS_DIR, "leaderboard_linear_probing_v3.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nTotal de experimentos executados: {total_exp} em {time.time() - t0:.1f}s", flush=True)
    print(f"Leaderboard completo salvo em: {csv_path}\n", flush=True)

    print("=" * 110, flush=True)
    print("MELHOR CONFIGURAÇÃO POR TAXONOMIA (Ordenado por Média Macro-F1 Validação/Teste)", flush=True)
    print("=" * 110, flush=True)
    for tax_id in TAXONOMIAS.keys():
        sub = df[df["taxonomia"] == tax_id]
        top = sub.iloc[0]
        print(f"[{tax_id}] ({TAXONOMIAS[tax_id]['desc']})", flush=True)
        print(f"  -> Modelo: {top['modelo']} | Preproc: {top['preproc']} | Bal: {top['balanceamento']}", flush=True)
        print(f"  -> Val Macro-F1: {top['val_macro_f1']:.4f} (Acc: {top['val_acc']:.4f}) | Test Macro-F1: {top['test_macro_f1']:.4f} (BalAcc: {top['test_bal_acc']:.4f}, Acc: {top['test_acc']:.4f})", flush=True)
        print(f"  -> F1 por Classe (Teste): {top['f1_por_classe_test']}", flush=True)
        print("-" * 110, flush=True)


if __name__ == "__main__":
    main()
