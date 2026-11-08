"""Módulo modular para geração de matrizes de confusão, gráficos comparativos de benchmarks
(v3 vs v4), inspeção qualitativa de predições de imagens e heatmaps de fine-tuning.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from PIL import Image


def _carregar_json_se_caminho(dados: Union[dict, str, Path]) -> dict:
    """Carrega dados em dicionário a partir de caminho de arquivo ou diretório de relatórios."""
    if isinstance(dados, (str, Path)):
        caminho = Path(dados)
        if caminho.is_dir():
            caminho = caminho / "resumo_resultados.json"
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo de resultados não encontrado: {caminho}")
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    if isinstance(dados, dict):
        return dados
    raise TypeError(f"Esperado dict, str ou Path, recebido {type(dados)}")


def plotar_matriz_confusao(
    cm: np.ndarray,
    nomes_classes: Sequence[str],
    titulo: str = "Matriz de Confusão (Teste)",
    caminho_salvar: Optional[Union[str, Path]] = None,
    normalizar: bool = False,
    ax: Optional[plt.Axes] = None,
    cmap: str = "Blues",
) -> Tuple[plt.Figure, plt.Axes]:
    """Renderiza uma matriz de confusão com anotações claras e opção de normalização percentual."""
    fig = ax.get_figure() if ax is not None else None
    if ax is None:
        fig, ax = plt.subplots(figsize=(6.5, 5))

    if normalizar:
        linhas_soma = cm.sum(axis=1, keepdims=True)
        # Evita divisão por zero em classes sem instâncias de teste
        cm_plot = np.divide(cm.astype(float), np.where(linhas_soma == 0, 1.0, linhas_soma))
        fmt = ".1%"
    else:
        cm_plot = cm
        fmt = "d"

    sns.heatmap(
        cm_plot,
        annot=True,
        fmt=fmt,
        cmap=cmap,
        xticklabels=nomes_classes,
        yticklabels=nomes_classes,
        annot_kws={"size": 13},
        ax=ax,
    )
    ax.set_title(titulo, fontsize=12, pad=12)
    ax.set_ylabel("Rótulo Verdadeiro", fontsize=11)
    ax.set_xlabel("Rótulo Previsto", fontsize=11)

    if fig is not None:
        try:
            fig.tight_layout()
        except Exception:
            pass

    if caminho_salvar is not None and fig is not None:
        caminho_p = Path(caminho_salvar)
        caminho_p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(caminho_p, dpi=140)

    return fig, ax


def plotar_amostras_predicao(
    paths: Sequence[Union[str, Path]],
    y_true: Sequence[int],
    y_pred: Sequence[int],
    nomes_classes: Sequence[str],
    probs: Optional[np.ndarray] = None,
    titulo: str = "Amostras do Conjunto de Teste — Predição vs Real",
    n_amostras: int = 10,
    n_cols: int = 5,
    seed: Optional[int] = 42,
    apenas_erros: bool = False,
    caminho_salvar: Optional[Union[str, Path]] = None,
) -> Tuple[Optional[plt.Figure], Optional[np.ndarray]]:
    """Exibe um grid de imagens reais de teste comparando rótulo humano vs predição do modelo."""
    arr_paths = np.asarray(paths)
    arr_y_true = np.asarray(y_true)
    arr_y_pred = np.asarray(y_pred)

    if apenas_erros:
        indices_candidatos = np.where(arr_y_true != arr_y_pred)[0]
    else:
        indices_candidatos = np.arange(len(arr_y_true))

    if len(indices_candidatos) == 0:
        print("[Aviso] Nenhuma amostra encontrada para o critério selecionado.")
        return None, None

    # Seleção estratificada se houver múltiplas classes e não for restrito a erros
    if not apenas_erros and len(np.unique(arr_y_true[indices_candidatos])) > 1:
        try:
            from scripts.utils.data_utils import selecionar_indices_estratificados
            escolhidos_locais = selecionar_indices_estratificados(
                arr_y_true[indices_candidatos], n_total=n_amostras, seed=seed or 42
            )
            indices_finais = indices_candidatos[escolhidos_locais]
        except Exception:
            rng = np.random.RandomState(seed)
            n_escolher = min(n_amostras, len(indices_candidatos))
            indices_finais = rng.choice(indices_candidatos, size=n_escolher, replace=False)
    else:
        rng = np.random.RandomState(seed)
        n_escolher = min(n_amostras, len(indices_candidatos))
        indices_finais = rng.choice(indices_candidatos, size=n_escolher, replace=False)

    n_itens = len(indices_finais)
    n_linhas = (n_itens + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_linhas, n_cols, figsize=(4.0 * n_cols, 4.2 * n_linhas), layout="constrained")
    axes_arr = np.atleast_1d(axes).flatten()
    fig.suptitle(titulo, fontsize=15, weight="bold")

    for i, idx in enumerate(indices_finais):
        ax = axes_arr[i]
        caminho_img = Path(arr_paths[idx])
        real_idx = int(arr_y_true[idx])
        pred_idx = int(arr_y_pred[idx])

        conf_str = ""
        if probs is not None and idx < len(probs):
            conf_str = f" ({probs[idx, pred_idx]:.1%})"

        try:
            img = Image.open(caminho_img).convert("RGB")
            ax.imshow(img)
        except Exception:
            ax.imshow(np.full((224, 224, 3), 220, dtype=np.uint8))

        ax.axis("off")
        nome_rua = caminho_img.name.split("__")[0].replace("avenida-", "av. ").replace("rua-", "r. ").replace("-", " ")[:24]
        acertou = (real_idx == pred_idx)
        cor = "forestgreen" if acertou else "crimson"
        status = "ACERTO" if acertou else "ERRO"

        ax.set_title(
            f"[{status}] {nome_rua}\nReal: {nomes_classes[real_idx]}\nPrev: {nomes_classes[pred_idx]}{conf_str}",
            color=cor,
            fontsize=10,
            weight="bold",
            pad=6,
        )

    for j in range(n_itens, len(axes_arr)):
        axes_arr[j].axis("off")

    if caminho_salvar is not None:
        caminho_p = Path(caminho_salvar)
        caminho_p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(caminho_p, dpi=140)

    return fig, axes_arr


def plotar_comparativo_v3_v4(
    resumo_v3: Union[dict, str, Path],
    resumo_v4: Union[dict, str, Path],
    cenarios: Optional[Sequence[str]] = None,
    metricas: Sequence[str] = ("macro_f1", "weighted_f1", "acc", "bal_acc"),
    split: str = "teste",
    titulo: str = "Comparativo de Desempenho de Taxonomias: Dataset v3 vs v4",
    caminho_salvar: Optional[Union[str, Path]] = None,
) -> Tuple[plt.Figure, np.ndarray]:
    """Gera gráfico de barras comparativas agrupadas lado a lado para cada métrica avaliada entre v3 e v4."""
    dados_v3 = _carregar_json_se_caminho(resumo_v3)
    dados_v4 = _carregar_json_se_caminho(resumo_v4)

    if cenarios is None:
        ordem_padrao = ["01_5classes_baseline", "03_3classes_sem_naoid", "04_3classes_com_naoid", "05_2classes_sem_naoid"]
        cenarios = [c for c in ordem_padrao if c in dados_v3 and c in dados_v4]
        if not cenarios:
            cenarios = sorted(list(set(dados_v3.keys()).intersection(set(dados_v4.keys()))))

    titulos_cenarios = [dados_v4.get(c, {}).get("titulo", c).split(":")[0].replace("Cenário ", "Cen. ") for c in cenarios]

    rotulos_metricas = {
        "macro_f1": "Macro F1",
        "weighted_f1": "Weighted F1",
        "acc": "Acurácia",
        "bal_acc": "Balanced Acc",
    }

    n_metricas = len(metricas)
    n_cols = 2 if n_metricas > 1 else 1
    n_linhas = (n_metricas + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_linhas, n_cols, figsize=(7.0 * n_cols, 4.5 * n_linhas), layout="constrained")
    axes_arr = np.atleast_1d(axes).flatten()
    fig.suptitle(titulo, fontsize=15, weight="bold")

    x = np.arange(len(cenarios))
    largura = 0.35

    for i, m_key in enumerate(metricas):
        ax = axes_arr[i]
        vals_v3 = [dados_v3.get(c, {}).get(split, {}).get(m_key, np.nan) for c in cenarios]
        vals_v4 = [dados_v4.get(c, {}).get(split, {}).get(m_key, np.nan) for c in cenarios]

        # Substitui possíveis NaNs por 0.0 na plotagem mantendo visual legível
        barras_v3 = ax.bar(x - largura / 2, [0.0 if np.isnan(v) else v for v in vals_v3], largura, label="v3 (75 teste)", color="#4c72b0")
        barras_v4 = ax.bar(x + largura / 2, [0.0 if np.isnan(v) else v for v in vals_v4], largura, label="v4 (115 teste)", color="#55a868")

        ax.set_title(rotulos_metricas.get(m_key, m_key), fontsize=12, weight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(titulos_cenarios, fontsize=10)
        ax.set_ylim(0, 1.05)
        ax.grid(axis="y", linestyle="--", alpha=0.6)
        ax.legend(loc="lower right", fontsize=9)

        # Adiciona rótulos de valores acima das barras
        for bar, val in zip(barras_v3, vals_v3):
            if not np.isnan(val) and val > 0:
                ax.annotate(f"{val:.3f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            ha="center", va="bottom", fontsize=8, xytext=(0, 2), textcoords="offset points")
            elif np.isnan(val):
                ax.annotate("N/A", (bar.get_x() + bar.get_width() / 2, 0.02),
                            ha="center", va="bottom", fontsize=7, color="gray", xytext=(0, 2), textcoords="offset points")

        for bar, val in zip(barras_v4, vals_v4):
            if not np.isnan(val) and val > 0:
                ax.annotate(f"{val:.3f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            ha="center", va="bottom", fontsize=8, xytext=(0, 2), textcoords="offset points")

    for j in range(n_metricas, len(axes_arr)):
        axes_arr[j].axis("off")

    if caminho_salvar is not None:
        caminho_p = Path(caminho_salvar)
        caminho_p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(caminho_p, dpi=140)

    return fig, axes_arr


def plotar_comparativo_f1_classes(
    resumo_v3: Union[dict, str, Path],
    resumo_v4: Union[dict, str, Path],
    chave_cenario: str,
    split: str = "teste",
    titulo: Optional[str] = None,
    caminho_salvar: Optional[Union[str, Path]] = None,
) -> Tuple[plt.Figure, plt.Axes]:
    """Compara o F1-score obtido em cada classe individualmente entre v3 e v4 para um cenário chave."""
    dados_v3 = _carregar_json_se_caminho(resumo_v3)
    dados_v4 = _carregar_json_se_caminho(resumo_v4)

    if chave_cenario not in dados_v4:
        raise KeyError(f"Cenário '{chave_cenario}' não encontrado em resumo_v4")

    f1_v3 = dados_v3.get(chave_cenario, {}).get(split, {}).get("f1_por_classe", {})
    f1_v4 = dados_v4.get(chave_cenario, {}).get(split, {}).get("f1_por_classe", {})

    classes = list(dados_v4[chave_cenario].get("classes", list(f1_v4.keys())))
    titulo_cenario = dados_v4[chave_cenario].get("titulo", chave_cenario)
    titulo_final = titulo or f"F1-Score por Classe (v3 vs v4) — {titulo_cenario}"

    x = np.arange(len(classes))
    largura = 0.35

    fig, ax = plt.subplots(figsize=(8.0, 4.8), layout="constrained")
    vals_v3 = [f1_v3.get(cls, np.nan) for cls in classes]
    vals_v4 = [f1_v4.get(cls, np.nan) for cls in classes]

    barras_v3 = ax.bar(x - largura / 2, [0.0 if np.isnan(v) else v for v in vals_v3], largura, label="v3 (75 teste)", color="#4c72b0")
    barras_v4 = ax.bar(x + largura / 2, [0.0 if np.isnan(v) else v for v in vals_v4], largura, label="v4 (115 teste)", color="#55a868")

    ax.set_title(titulo_final, fontsize=12, weight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(classes, fontsize=10)
    ax.set_ylim(0, 1.08)
    ax.grid(axis="y", linestyle="--", alpha=0.6)
    ax.legend(loc="lower right", fontsize=9)

    for bar, val in zip(barras_v3, vals_v3):
        if not np.isnan(val) and val > 0:
            ax.annotate(f"{val:.2f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=9, xytext=(0, 2), textcoords="offset points")

    for bar, val in zip(barras_v4, vals_v4):
        if not np.isnan(val) and val > 0:
            ax.annotate(f"{val:.2f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        ha="center", va="bottom", fontsize=9, xytext=(0, 2), textcoords="offset points")

    if caminho_salvar is not None:
        caminho_p = Path(caminho_salvar)
        caminho_p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(caminho_p, dpi=140)

    return fig, ax


def gerar_tabela_comparativa_v3_v4(
    resumo_v3: Union[dict, str, Path],
    resumo_v4: Union[dict, str, Path],
    cenarios: Optional[Sequence[str]] = None,
    split: str = "teste",
    calcular_weighted_v3_se_ausente: bool = False,
) -> pd.DataFrame:
    """Gera DataFrame estruturado comparando métricas v3 vs v4 com variações delta calculadas."""
    dados_v3 = _carregar_json_se_caminho(resumo_v3)
    dados_v4 = _carregar_json_se_caminho(resumo_v4)

    if cenarios is None:
        ordem_padrao = ["01_5classes_baseline", "03_3classes_sem_naoid", "04_3classes_com_naoid", "05_2classes_sem_naoid"]
        cenarios = [c for c in ordem_padrao if c in dados_v4]
        if not cenarios:
            cenarios = sorted(list(dados_v4.keys()))

    dados_v3_brutos = None
    if calcular_weighted_v3_se_ausente:
        try:
            from scripts.utils.data_utils import carregar_dados
            dados_v3_brutos = carregar_dados()
        except Exception:
            dados_v3_brutos = None

    linhas = []
    for c in cenarios:
        t_v3 = dados_v3.get(c, {}).get(split, {})
        t_v4 = dados_v4.get(c, {}).get(split, {})

        acc_v3 = t_v3.get("acc", np.nan)
        acc_v4 = t_v4.get("acc", np.nan)
        bal_v3 = t_v3.get("bal_acc", np.nan)
        bal_v4 = t_v4.get("bal_acc", np.nan)
        macro_v3 = t_v3.get("macro_f1", np.nan)
        macro_v4 = t_v4.get("macro_f1", np.nan)
        w_v3 = t_v3.get("weighted_f1", np.nan)
        w_v4 = t_v4.get("weighted_f1", np.nan)

        if pd.isna(w_v3) and calcular_weighted_v3_se_ausente and dados_v3_brutos is not None:
            try:
                from scripts.utils.data_utils import aplicar_taxonomia
                from scripts.utils.linear_probing import CENARIOS, treinar_pipeline
                from sklearn.metrics import f1_score
                cfg = CENARIOS[c]
                X_tr, y_tr = aplicar_taxonomia(dados_v3_brutos["X_train"], dados_v3_brutos["y_train"], cfg["mapa"])
                split_k = "X_test" if split == "teste" else "X_valid"
                split_y = "y_test" if split == "teste" else "y_valid"
                X_s, y_s = aplicar_taxonomia(dados_v3_brutos[split_k], dados_v3_brutos[split_y], cfg["mapa"])
                clf, _ = treinar_pipeline(X_tr, y_tr, preproc=cfg["preproc"], teto_under=cfg["teto_under"], modelo_fn=cfg["modelo_fn"], seed=42)
                preds = clf.predict(X_s)
                w_v3 = round(float(f1_score(y_s, preds, average="weighted", zero_division=0)), 4)
            except Exception:
                pass

        delta_acc = round(acc_v4 - acc_v3, 4) if pd.notna(acc_v3) and pd.notna(acc_v4) else np.nan
        delta_bal = round(bal_v4 - bal_v3, 4) if pd.notna(bal_v3) and pd.notna(bal_v4) else np.nan
        delta_macro = round(macro_v4 - macro_v3, 4) if pd.notna(macro_v3) and pd.notna(macro_v4) else np.nan
        delta_w = round(w_v4 - w_v3, 4) if pd.notna(w_v3) and pd.notna(w_v4) else np.nan

        linhas.append({
            "Cenário": c,
            "Título": dados_v4.get(c, {}).get("titulo", c),
            "Acc v3": acc_v3,
            "Acc v4": acc_v4,
            "Delta Acc": delta_acc,
            "Bal Acc v3": bal_v3,
            "Bal Acc v4": bal_v4,
            "Delta Bal Acc": delta_bal,
            "Macro F1 v3": macro_v3,
            "Macro F1 v4": macro_v4,
            "Delta Macro F1": delta_macro,
            "Weighted F1 v3": w_v3,
            "Weighted F1 v4": w_v4,
            "Delta Weighted F1": delta_w,
        })

    return pd.DataFrame(linhas)


def plotar_comparativo_tagger_heatmaps(
    medias_orig: pd.DataFrame,
    medias_ft: pd.DataFrame,
    split: str = "test",
    titulo: str = "Ativação Média de Tags do Sidewalk: Tagger Original vs Fine-Tunado (sem brick)",
    caminho_salvar: Optional[Union[str, Path]] = None,
) -> Tuple[plt.Figure, np.ndarray]:
    """Renderiza heatmaps comparativos lado a lado das probabilidades médias de ativação das tags por classe real."""
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=True, layout="constrained")
    fig.suptitle(titulo, fontsize=14, weight="bold")

    sns.heatmap(
        medias_orig,
        annot=True,
        fmt=".2f",
        cmap="YlOrRd",
        vmin=0.0,
        vmax=1.0,
        cbar=False,
        ax=axes[0],
    )
    axes[0].set_title(f"Tagger Original ({split})", fontsize=12, pad=10)
    axes[0].set_xlabel("Classes Reais", fontsize=11)
    axes[0].set_ylabel("Tags do Sidewalk", fontsize=11)

    sns.heatmap(
        medias_ft,
        annot=True,
        fmt=".2f",
        cmap="YlOrRd",
        vmin=0.0,
        vmax=1.0,
        cbar=True,
        cbar_kws={"label": "Probabilidade Média"},
        ax=axes[1],
    )
    axes[1].set_title(f"Tagger Fine-Tunado sem brick ({split})", fontsize=12, pad=10)
    axes[1].set_xlabel("Classes Reais", fontsize=11)
    axes[1].set_ylabel("")

    if caminho_salvar is not None:
        caminho_p = Path(caminho_salvar)
        caminho_p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(caminho_p, dpi=140)

    return fig, axes


__all__ = [
    "plotar_matriz_confusao",
    "plotar_amostras_predicao",
    "plotar_comparativo_v3_v4",
    "plotar_comparativo_f1_classes",
    "gerar_tabela_comparativa_v3_v4",
    "plotar_comparativo_tagger_heatmaps",
]
