"""Módulo modular (facade) para execução, registro e análise comparativa de
experimentos e benchmarks de linear probing sobre features DINOv2.

Re-exporta pipelines, taxonomias e cenários de linear_probing.py, adicionando:
- Cálculo estrito de Weighted F1 (junto a Macro F1, Acc e Bal Acc).
- Suporte nativo a diretórios customizados de relatórios (default: data/reports/avaliacao_taxonomias_v4).
- Geração aprimorada de resumo_resultados.json e resumo_resultados.md.
- Funções auxiliares para execução em lote (executar_bateria_v4) e tabela comparativa v3 vs v4.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

# Re-exportações canônicas de dados e linear_probing
from scripts.utils.data_utils import (
    CLASSES_V3,
    TAXONOMIAS,
    aplicar_taxonomia,
    balancear_undersampling,
    carregar_dados,
    listar_imagens_coco,
    selecionar_indices_estratificados,
)
from scripts.utils.linear_probing import (
    CENARIOS,
    plotar_10_amostras_teste,
    treinar_pipeline,
)
from scripts.utils.visualizacoes import (
    gerar_tabela_comparativa_v3_v4,
    plotar_amostras_predicao,
    plotar_matriz_confusao,
)

DEFAULT_REPORTS_DIR_V4 = "data/reports/avaliacao_taxonomias_v4"
DEFAULT_REPORTS_DIR_V3 = "data/reports/avaliacao_taxonomias"
CENARIOS_PRIORITARIOS_V4 = [
    "04_3classes_com_naoid",
    "05_2classes_sem_naoid",
    "01_5classes_baseline",
    "03_3classes_sem_naoid",
]


def calcular_metricas(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels_idx: Optional[List[int]] = None,
    nomes_classes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Calcula conjunto abrangente de métricas: Acc, Balanced Acc, Macro F1, Weighted F1 e F1 por classe."""
    if labels_idx is None:
        labels_idx = sorted(list(np.unique(np.concatenate([y_true, y_pred]))))

    acc = float(accuracy_score(y_true, y_pred))
    bal_acc = float(balanced_accuracy_score(y_true, y_pred))
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    weighted_f1 = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))
    f1_cls = f1_score(y_true, y_pred, average=None, labels=labels_idx, zero_division=0)

    f1_por_classe = {}
    for i, idx in enumerate(labels_idx):
        cls_nome = nomes_classes[i] if nomes_classes and i < len(nomes_classes) else str(idx)
        f1_por_classe[cls_nome] = round(float(f1_cls[i]), 4)

    return {
        "acc": round(acc, 4),
        "bal_acc": round(bal_acc, 4),
        "macro_f1": round(macro_f1, 4),
        "weighted_f1": round(weighted_f1, 4),
        "f1_por_classe": f1_por_classe,
    }


def salvar_artefatos_relatorio(
    chave: str,
    cfg: Dict[str, Any],
    metricas: Dict[str, Any],
    cm_test: np.ndarray,
    reports_dir: str = DEFAULT_REPORTS_DIR_V4,
    titulo_relatorio: str = "Relatório Consolidado: Avaliação de Taxonomias (Linear Probing v4)",
) -> None:
    """Salva matriz de confusão e consolida resumo em JSON e Markdown incluindo Weighted F1."""
    pasta_matrizes = Path(reports_dir) / "matrizes_confusao"
    pasta_matrizes.mkdir(parents=True, exist_ok=True)

    caminho_img = pasta_matrizes / f"{chave}.png"
    plotar_matriz_confusao(
        cm_test,
        cfg["nomes"],
        titulo=f"Matriz de Confusão (Teste) - {chave}",
        caminho_salvar=caminho_img,
    )
    plt.close("all")

    json_path = Path(reports_dir) / "resumo_resultados.json"
    dados_json = {}
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            try:
                dados_json = json.load(f)
            except Exception:
                dados_json = {}

    valid_m = metricas.get("valid", metricas.get("validacao", {}))
    test_m = metricas.get("test", metricas.get("teste", {}))

    dados_json[chave] = {
        "titulo": cfg["titulo"],
        "descricao": cfg["descricao"],
        "modelo": cfg["modelo_nome"],
        "preproc": cfg["preproc"],
        "undersampling_teto": cfg["teto_under"],
        "classes": cfg["nomes"],
        "validacao": valid_m,
        "teste": test_m,
        "matriz_confusao_arquivo": f"matrizes_confusao/{chave}.png",
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dados_json, f, indent=2, ensure_ascii=False)

    md_path = Path(reports_dir) / "resumo_resultados.md"
    linhas = [
        f"# {titulo_relatorio}\n",
        "| Cenário | Modelo | Pré-proc. | Undersampling | Acc (Val) | Macro F1 (Val) | Weighted F1 (Val) | Acc (Teste) | Bal. Acc (Teste) | Macro F1 (Teste) | Weighted F1 (Teste) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for k, v in sorted(dados_json.items()):
        teto_str = str(v["undersampling_teto"]) if v["undersampling_teto"] else "Nenhum"
        val_w = f"{v['validacao'].get('weighted_f1', 0.0):.4f}" if "weighted_f1" in v["validacao"] else "-"
        test_w = f"**{v['teste'].get('weighted_f1', 0.0):.4f}**" if "weighted_f1" in v["teste"] else "-"
        linhas.append(
            f"| **{v['titulo']}** | `{v['modelo']}` | `{v['preproc']}` | `{teto_str}` "
            f"| {v['validacao']['acc']:.2%} | {v['validacao']['macro_f1']:.4f} | {val_w} "
            f"| **{v['teste']['acc']:.2%}** | **{v['teste']['bal_acc']:.2%}** | **{v['teste']['macro_f1']:.4f}** | {test_w} |"
        )

    linhas.append("\n## Detalhamento de F1 por Classe (Conjunto de Teste)\n")
    for k, v in sorted(dados_json.items()):
        linhas.append(f"### {v['titulo']}")
        linhas.append(f"- **Descrição**: {v['descricao']}")
        f1_str = " | ".join([f"**{cls}**: `{score:.2f}`" for cls, score in v["teste"]["f1_por_classe"].items()])
        linhas.append(f"- **F1 por Classe**: {f1_str}")
        linhas.append(f"- **Matriz de Confusão**: `{v['matriz_confusao_arquivo']}`\n")

    md_path.write_text("\n".join(linhas), encoding="utf-8")


def avaliar_cenario(
    chave_cenario: str,
    dados: Dict[str, Any],
    reports_dir: str = DEFAULT_REPORTS_DIR_V4,
    seed: int = 42,
    plotar_amostras: bool = True,
    retornar_metricas: bool = False,
    titulo_relatorio: str = "Relatório Consolidado: Avaliação de Taxonomias (Linear Probing v4)",
) -> Any:
    """Executa o pipeline completo do cenário com cálculo de Weighted F1, salvamento em reports_dir e plotagem."""
    if chave_cenario not in CENARIOS:
        raise KeyError(f"Cenário '{chave_cenario}' não encontrado em CENARIOS. Opções: {list(CENARIOS.keys())}")

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
        m = calcular_metricas(y_s, preds, labels_idx=labels_idx, nomes_classes=nomes)
        metricas[split_key] = m

        print(f"\n--- Resultados no conjunto de {split_label} ({len(y_s)} amostras) ---")
        print(f"Acurácia Geral: {m['acc']:.4f} | Balanced Accuracy: {m['bal_acc']:.4f} | Macro F1: {m['macro_f1']:.4f} | Weighted F1: {m['weighted_f1']:.4f}\n")
        print(classification_report(y_s, preds, labels=labels_idx, target_names=target_names, zero_division=0))

    cm_test = confusion_matrix(y_te, clf.predict(X_te), labels=labels_idx)
    salvar_artefatos_relatorio(
        chave_cenario,
        cfg,
        metricas,
        cm_test,
        reports_dir=reports_dir,
        titulo_relatorio=titulo_relatorio,
    )
    print(f"[Relatório e Matriz de Confusão salvos em '{reports_dir}/']")

    if plotar_amostras:
        try:
            pasta_amostras = Path(reports_dir) / "amostras_teste"
            caminho_amostra = pasta_amostras / f"{chave_cenario}.png"
            probs = clf.predict_proba(X_te) if hasattr(clf, "predict_proba") else None
            plotar_amostras_predicao(
                paths_te,
                y_te,
                clf.predict(X_te),
                nomes,
                probs=probs,
                titulo=f"Amostras do Conjunto de Teste — {cfg['titulo']}",
                seed=seed,
                caminho_salvar=caminho_amostra,
            )
            plt.close("all")
        except Exception as e:
            print(f"[Aviso] Não foi possível exibir amostras visuais: {e}")

    setattr(clf, "metricas_", metricas)
    if retornar_metricas:
        return clf, metricas
    return clf


def carregar_resumo_resultados(reports_dir: str = DEFAULT_REPORTS_DIR_V4) -> Dict[str, Any]:
    """Carrega o arquivo resumo_resultados.json do diretório de relatórios fornecido."""
    json_path = Path(reports_dir) / "resumo_resultados.json"
    if not json_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def executar_bateria_v4(
    dados: Optional[Dict[str, Any]] = None,
    cenarios: Optional[List[str]] = None,
    reports_dir: str = DEFAULT_REPORTS_DIR_V4,
    seed: int = 42,
    plotar_amostras: bool = True,
) -> Dict[str, Any]:
    """Executa a bateria de benchmarks prioritários no dataset v4 e retorna dicionário com modelos e métricas."""
    if dados is None:
        dados = carregar_dados(processed_dir="data/processed/apx2-bzsou-v4")
    if cenarios is None:
        cenarios = CENARIOS_PRIORITARIOS_V4

    resultados = {}
    for chave in cenarios:
        print(f"\n>>> Executando benchmark para {chave}...")
        clf, met = avaliar_cenario(
            chave,
            dados,
            reports_dir=reports_dir,
            seed=seed,
            plotar_amostras=plotar_amostras,
            retornar_metricas=True,
        )
        resultados[chave] = {"modelo": clf, "metricas": met}
    return resultados


def comparar_desempenho_v3_v4(
    reports_dir_v3: str = DEFAULT_REPORTS_DIR_V3,
    reports_dir_v4: str = DEFAULT_REPORTS_DIR_V4,
    cenarios: Optional[List[str]] = None,
    calcular_weighted_v3_se_ausente: bool = False,
) -> pd.DataFrame:
    """Gera DataFrame comparativo direto entre benchmarks do dataset v3 e v4 para os cenários selecionados."""
    return gerar_tabela_comparativa_v3_v4(
        reports_dir_v3,
        reports_dir_v4,
        cenarios=cenarios,
        calcular_weighted_v3_se_ausente=calcular_weighted_v3_se_ausente,
    )


__all__ = [
    # Re-exportações de dados e taxonomias
    "CLASSES_V3",
    "TAXONOMIAS",
    "carregar_dados",
    "aplicar_taxonomia",
    "balancear_undersampling",
    "selecionar_indices_estratificados",
    "listar_imagens_coco",
    # Re-exportações de linear_probing
    "CENARIOS",
    "treinar_pipeline",
    "plotar_10_amostras_teste",
    # Constantes
    "DEFAULT_REPORTS_DIR_V4",
    "DEFAULT_REPORTS_DIR_V3",
    "CENARIOS_PRIORITARIOS_V4",
    # Novas funcionalidades aprimoradas
    "calcular_metricas",
    "salvar_artefatos_relatorio",
    "avaliar_cenario",
    "executar_bateria_v4",
    "carregar_resumo_resultados",
    "comparar_desempenho_v3_v4",
]
