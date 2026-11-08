import json
import os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from PIL import Image
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer, StandardScaler
from sklearn.decomposition import PCA
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    classification_report,
    confusion_matrix,
)

# Importa as utilidades gerais de dados e taxonomias
try:
    from scripts.utils.data_utils import (
        TAXONOMIAS,
        carregar_dados,
        aplicar_taxonomia,
        balancear_undersampling,
        selecionar_indices_estratificados,
    )
except ImportError:
    from data_utils import (
        TAXONOMIAS,
        carregar_dados,
        aplicar_taxonomia,
        balancear_undersampling,
        selecionar_indices_estratificados,
    )

# Catálogo dos 5 cenários principais validados no benchmark de Linear Probing
CENARIOS = {
    "01_5classes_baseline": {
        "titulo": "Cenário 1: 5 Classes Originais (Baseline MLP)",
        "descricao": "Todas as 5 classes separadas sem pré-processamento e sem balanceamento.",
        "nomes": TAXONOMIAS["5_classes_original"]["nomes"],
        "mapa": TAXONOMIAS["5_classes_original"]["mapa"],
        "preproc": "raw",
        "teto_under": None,
        "modelo_nome": "MLP (256)",
        "modelo_fn": lambda: MLPClassifier(hidden_layer_sizes=(256,), activation="relu", max_iter=1000, random_state=42),
    },
    "02_4classes_com_naoid": {
        "titulo": "Cenário 2: 4 Classes com Não Identificável (Inadequada + Sem calçada unidas)",
        "descricao": "Une Inadequada e Sem calçada na mesma categoria crítica, mantendo Parcial e Não identificável.",
        "nomes": TAXONOMIAS["4_classes_com_naoid"]["nomes"],
        "mapa": TAXONOMIAS["4_classes_com_naoid"]["mapa"],
        "preproc": "l2_pca64",
        "teto_under": 70,
        "modelo_nome": "SVC RBF (C=3.0, balanced)",
        "modelo_fn": lambda: SVC(C=3.0, kernel="rbf", class_weight="balanced", probability=True, random_state=42),
    },
    "03_3classes_sem_naoid": {
        "titulo": "Cenário 3: 3 Classes sem Não Identificável (Adequada | Com Defeito | Sem calçada)",
        "descricao": "Remove a classe de ruído (Não identificável) e agrupa Parcial + Inadequada como calçadas com defeito.",
        "nomes": TAXONOMIAS["3_classes_sem_naoid"]["nomes"],
        "mapa": TAXONOMIAS["3_classes_sem_naoid"]["mapa"],
        "preproc": "l2_pca64",
        "teto_under": 100,
        "modelo_nome": "Random Forest (100, balanced)",
        "modelo_fn": lambda: RandomForestClassifier(n_estimators=100, max_depth=10, class_weight="balanced_subsample", random_state=42),
    },
    "04_3classes_com_naoid": {
        "titulo": "Cenário 4: 3 Classes com Não Identificável (Adequada | Inadequada Geral | Não id.)",
        "descricao": "Mantém a classe de rejeição (Não id.) para uso em produção e consolida inconformidades em Inadequada Geral.",
        "nomes": TAXONOMIAS["3_classes_com_naoid"]["nomes"],
        "mapa": TAXONOMIAS["3_classes_com_naoid"]["mapa"],
        "preproc": "l2_std",
        "teto_under": None,
        "modelo_nome": "MLP (128, alpha=0.5, early_stopping)",
        "modelo_fn": lambda: MLPClassifier(hidden_layer_sizes=(128,), alpha=0.5, early_stopping=True, max_iter=300, random_state=42),
    },
    "05_2classes_sem_naoid": {
        "titulo": "Cenário 5: 2 Classes Binária Crítica sem Não Identificável (Transitável vs Crítica)",
        "descricao": "Separa calçadas transitáveis (Adequada + Parcial) de situações críticas (Inadequada + Sem calçada).",
        "nomes": TAXONOMIAS["2_classes_sem_naoid"]["nomes"],
        "mapa": TAXONOMIAS["2_classes_sem_naoid"]["mapa"],
        "preproc": "l2_pca64",
        "teto_under": 100,
        "modelo_nome": "Regressão Logística (C=0.5, balanced)",
        "modelo_fn": lambda: LogisticRegression(C=0.5, class_weight="balanced", max_iter=500, random_state=42),
    },
}


def treinar_pipeline(X_tr, y_tr, preproc, teto_under, modelo_fn, seed=42):
    """
    Ajusta a transformação de espaço (L2 / StandardScaler / PCA) usando toda a distribuição de treino,
    aplica o undersampling da classe majoritária no espaço transformado e treina o classificador.
    """
    steps_pre = []
    if preproc == "l2":
        steps_pre.append(("norm_l2", Normalizer(norm="l2")))
    elif preproc == "standard":
        steps_pre.append(("scaler", StandardScaler()))
    elif preproc == "l2_std":
        steps_pre.extend([("norm_l2", Normalizer(norm="l2")), ("scaler", StandardScaler())])
    elif preproc == "l2_pca64":
        n_comp = min(64, X_tr.shape[0] - 1)
        steps_pre.extend([("norm_l2", Normalizer(norm="l2")), ("pca", PCA(n_components=n_comp, random_state=seed))])

    if steps_pre:
        preproc_pipe = Pipeline(steps_pre)
        X_tr_p = preproc_pipe.fit_transform(X_tr)
    else:
        preproc_pipe = None
        X_tr_p = X_tr

    X_tr_b, y_tr_b = balancear_undersampling(X_tr_p, y_tr, teto=teto_under, seed=seed)

    clf = modelo_fn()
    clf.fit(X_tr_b, y_tr_b)

    final_steps = list(steps_pre) + [("clf", clf)]
    return Pipeline(final_steps), y_tr_b


def salvar_artefatos_relatorio(chave, cfg, metricas, cm_test, reports_dir="data/reports/avaliacao_taxonomias"):
    """Salva a imagem da matriz de confusão e atualiza os relatórios consolidados (.json e .md)."""
    pasta_matrizes = Path(reports_dir) / "matrizes_confusao"
    pasta_matrizes.mkdir(parents=True, exist_ok=True)

    # 1. Salvar figura da matriz de confusão silenciosamente (sem poluir o notebook)
    fig, ax = plt.subplots(figsize=(6.5, 5))
    sns.heatmap(
        cm_test,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=cfg["nomes"],
        yticklabels=cfg["nomes"],
        annot_kws={"size": 13},
        ax=ax,
    )
    ax.set_title(f"Matriz de Confusão (Teste) - {chave}", fontsize=12, pad=12)
    ax.set_ylabel("Rótulo Verdadeiro", fontsize=11)
    ax.set_xlabel("Rótulo Previsto", fontsize=11)
    fig.tight_layout()
    caminho_img = pasta_matrizes / f"{chave}.png"
    fig.savefig(caminho_img, dpi=140)
    plt.close(fig)

    # 2. Atualizar arquivo JSON consolidado
    json_path = Path(reports_dir) / "resumo_resultados.json"
    dados_json = {}
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            dados_json = json.load(f)

    dados_json[chave] = {
        "titulo": cfg["titulo"],
        "descricao": cfg["descricao"],
        "modelo": cfg["modelo_nome"],
        "preproc": cfg["preproc"],
        "undersampling_teto": cfg["teto_under"],
        "classes": cfg["nomes"],
        "validacao": metricas["valid"],
        "teste": metricas["test"],
        "matriz_confusao_arquivo": f"matrizes_confusao/{chave}.png",
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dados_json, f, indent=2, ensure_ascii=False)

    # 3. Atualizar resumo em Markdown
    md_path = Path(reports_dir) / "resumo_resultados.md"
    linhas = [
        "# Relatório Consolidado: Avaliação de Taxonomias (Linear Probing v3)\n",
        "| Cenário | Modelo | Pré-proc. | Undersampling | Acc (Val) | Macro F1 (Val) | Acc (Teste) | Bal. Acc (Teste) | Macro F1 (Teste) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for k, v in sorted(dados_json.items()):
        teto_str = str(v["undersampling_teto"]) if v["undersampling_teto"] else "Nenhum"
        linhas.append(
            f"| **{v['titulo']}** | `{v['modelo']}` | `{v['preproc']}` | `{teto_str}` "
            f"| {v['validacao']['acc']:.2%} | {v['validacao']['macro_f1']:.4f} "
            f"| **{v['teste']['acc']:.2%}** | **{v['teste']['bal_acc']:.2%}** | **{v['teste']['macro_f1']:.4f}** |"
        )

    linhas.append("\n## Detalhamento de F1 por Classe (Conjunto de Teste)\n")
    for k, v in sorted(dados_json.items()):
        linhas.append(f"### {v['titulo']}")
        linhas.append(f"- **Descrição**: {v['descricao']}")
        f1_str = " | ".join([f"**{cls}**: `{score:.2f}`" for cls, score in v["teste"]["f1_por_classe"].items()])
        linhas.append(f"- **F1 por Classe**: {f1_str}")
        linhas.append(f"- **Matriz de Confusão**: `{v['matriz_confusao_arquivo']}`\n")

    md_path.write_text("\n".join(linhas), encoding="utf-8")


def plotar_10_amostras_teste(X_te, y_te, paths_te, clf, nomes_classes, titulo_cenario, seed=42):
    """Exibe um grid 2x5 com 10 amostras reais do conjunto de teste, comparando Real vs Previsto."""
    indices = selecionar_indices_estratificados(y_te, n_total=10, seed=seed)
    preds = clf.predict(X_te[indices])
    probs = clf.predict_proba(X_te[indices])

    fig, axes = plt.subplots(2, 5, figsize=(20, 10.5), layout="constrained")
    axes = axes.flatten()
    fig.suptitle(f"Amostras do Conjunto de Teste — {titulo_cenario}", fontsize=16, weight="bold")

    for i, idx in enumerate(indices):
        img_path = paths_te[idx]
        real_idx = int(y_te[idx])
        pred_idx = int(preds[i])
        conf = probs[i][pred_idx]

        nome_arq = os.path.basename(img_path)
        rua_curta = nome_arq.split("__")[0].replace("avenida-", "av. ").replace("rua-", "r. ")[:22]

        image = Image.open(img_path).convert("RGB")
        ax = axes[i]
        ax.imshow(image)
        ax.axis("off")

        acertou = real_idx == pred_idx
        cor = "forestgreen" if acertou else "crimson"
        status = "ACERTO" if acertou else "ERRO"

        ax.set_title(
            f"[{status}] {rua_curta}\nReal: {nomes_classes[real_idx]}\nPrev: {nomes_classes[pred_idx]} ({conf:.1%})",
            color=cor,
            fontsize=11,
            weight="bold",
            pad=10,
        )

    plt.show()


def avaliar_cenario(chave_cenario, dados, reports_dir="data/reports/avaliacao_taxonomias", seed=42):
    """Executa o fluxo completo de um cenário: filtra classes, treina pipeline, imprime logs, salva report e plota 10 imagens de teste."""
    cfg = CENARIOS[chave_cenario]
    nomes = cfg["nomes"]
    labels_idx = list(range(len(nomes)))
    target_names = [f"{n} ({i})" for i, n in enumerate(nomes)]

    X_tr, y_tr = aplicar_taxonomia(dados["X_train"], dados["y_train"], cfg["mapa"])
    X_va, y_va = aplicar_taxonomia(dados["X_valid"], dados["y_valid"], cfg["mapa"])
    X_te, y_te, paths_te = aplicar_taxonomia(dados["X_test"], dados["y_test"], cfg["mapa"], dados["test_paths"])

    clf, y_tr_b = treinar_pipeline(
        X_tr, y_tr, preproc=cfg["preproc"], teto_under=cfg["teto_under"], modelo_fn=cfg["modelo_fn"], seed=seed
    )

    print("=" * 80)
    print(f"{cfg['titulo'].upper()}")
    print(f"Modelo: {cfg['modelo_nome']} | Pré-proc: {cfg['preproc']} | Undersampling: {cfg['teto_under'] or 'Nenhum'}")
    print("Treino (após balanceamento) -> " + " | ".join([f"{nomes[c]}: {np.sum(y_tr_b == c)}" for c in labels_idx]))
    print("=" * 80)

    metricas = {}
    for split_key, split_label, X_s, y_s in [("valid", "VALIDAÇÃO", X_va, y_va), ("test", "TESTE", X_te, y_te)]:
        preds = clf.predict(X_s)
        acc = accuracy_score(y_s, preds)
        bal_acc = balanced_accuracy_score(y_s, preds)
        m_f1 = f1_score(y_s, preds, average="macro", zero_division=0)
        f1_cls = f1_score(y_s, preds, average=None, labels=labels_idx, zero_division=0)

        metricas[split_key] = {
            "acc": round(float(acc), 4),
            "bal_acc": round(float(bal_acc), 4),
            "macro_f1": round(float(m_f1), 4),
            "f1_por_classe": {nomes[i]: round(float(f1_cls[i]), 4) for i in labels_idx},
        }

        print(f"\n--- Resultados no conjunto de {split_label} ({len(y_s)} amostras) ---")
        print(f"Acurácia Geral: {acc:.4f} | Balanced Accuracy: {bal_acc:.4f} | Macro F1: {m_f1:.4f}\n")
        print(classification_report(y_s, preds, labels=labels_idx, target_names=target_names, zero_division=0))

    cm_test = confusion_matrix(y_te, clf.predict(X_te), labels=labels_idx)
    salvar_artefatos_relatorio(chave_cenario, cfg, metricas, cm_test, reports_dir=reports_dir)
    print(f"[Relatório e Matriz de Confusão salvos em '{reports_dir}/']")

    plotar_10_amostras_teste(X_te, y_te, paths_te, clf, nomes, cfg["titulo"], seed=seed)
    return clf


__all__ = [
    "TAXONOMIAS",
    "CENARIOS",
    "carregar_dados",
    "aplicar_taxonomia",
    "balancear_undersampling",
    "selecionar_indices_estratificados",
    "treinar_pipeline",
    "salvar_artefatos_relatorio",
    "plotar_10_amostras_teste",
    "avaliar_cenario",
]
