"""Pipeline unificado de inferência de qualidade e diagnóstico de calçadas."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torchvision.transforms as T
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

from scripts.utils.device import get_device
from scripts.utils.sidewalk_inference import TAGS_SEM_BRICK, criar_tagger_sem_brick

# Modelos padrão e mapeamento de cenários
HF_REPO_PADRAO = "caduobristo/calcadas-curitiba"
DINO_LARGE_ID = "projectsidewalk/sidewalk-validator-ai-surfaceproblem"

MAPEAMENTO_CENARIOS = {
    "binario": "classificador_cenario05_2classes_binario.joblib",
    "cenario5": "classificador_cenario05_2classes_binario.joblib",
    "2classes": "classificador_cenario05_2classes_binario.joblib",
    "3classes": "classificador_cenario04_3classes_com_naoid.joblib",
    "cenario4": "classificador_cenario04_3classes_com_naoid.joblib",
    "3classes_com_naoid": "classificador_cenario04_3classes_com_naoid.joblib",
    "3classes_sem_naoid": "classificador_cenario03_3classes_sem_naoid.joblib",
    "cenario3": "classificador_cenario03_3classes_sem_naoid.joblib",
}

EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def resolver_caminho_modelo(
    nome_arquivo: str,
    versao: str = "v4",
    models_dir: str = "data/models",
    hf_repo_id: str = HF_REPO_PADRAO,
) -> str:
    """Busca o modelo no diretório local ou faz download via Hugging Face Hub."""
    caminho_local = Path(models_dir) / versao / nome_arquivo
    if caminho_local.exists():
        return str(caminho_local)

    # Fallback para download via Hugging Face Hub
    try:
        from huggingface_hub import hf_hub_download
        print(f"Modelo local não encontrado em '{caminho_local}'. Baixando de '{hf_repo_id}'...")
        caminho_hf = hf_hub_download(
            repo_id=hf_repo_id,
            filename=f"{versao}/{nome_arquivo}",
        )
        return caminho_hf
    except Exception as e:
        raise FileNotFoundError(
            f"Não foi possível carregar '{nome_arquivo}' nem localmente em '{caminho_local}' "
            f"nem remotamente no Hugging Face Hub ('{hf_repo_id}'): {e}"
        )


class SidewalkPipeline:
    """Pipeline de inferência de ponta a ponta para qualidade e diagnóstico de calçadas."""

    def __init__(
        self,
        cenario: str = "binario",
        versao: str = "v4",
        models_dir: str = "data/models",
        hf_repo_id: str = HF_REPO_PADRAO,
        incluir_tags: bool = True,
        batch_size: int = 16,
        device: Optional[Union[str, torch.device]] = None,
    ):
        cenario_norm = cenario.lower().strip()
        if cenario_norm not in MAPEAMENTO_CENARIOS:
            opcoes = list(MAPEAMENTO_CENARIOS.keys())
            raise ValueError(f"Cenário '{cenario}' inválido. Opções disponíveis: {opcoes}")

        self.cenario_chave = cenario_norm
        self.versao = versao
        self.incluir_tags = incluir_tags
        self.batch_size = max(1, batch_size)
        self.device = device or get_device()

        # 1. Carregamento do classificador de qualidade (.joblib)
        nome_clf = MAPEAMENTO_CENARIOS[self.cenario_chave]
        caminho_clf = resolver_caminho_modelo(
            nome_arquivo=nome_clf,
            versao=self.versao,
            models_dir=models_dir,
            hf_repo_id=hf_repo_id,
        )
        dados_clf = joblib.load(caminho_clf)
        self.clf_pipeline = dados_clf["pipeline"]
        self.classes = dados_clf["classes"]
        self.titulo_cenario = dados_clf.get("titulo", self.cenario_chave)

        # 2. Carregamento do extrator de embeddings DINOv2-Large (1024D)
        self.processor = AutoImageProcessor.from_pretrained(DINO_LARGE_ID)
        self.dino_model = AutoModel.from_pretrained(DINO_LARGE_ID).to(self.device)
        self.dino_model.eval()

        # 3. Carregamento opcional do Tagger de explicabilidade (11 classes)
        if self.incluir_tags:
            caminho_tagger = resolver_caminho_modelo(
                nome_arquivo="tagger_sem_brick.pth",
                versao=self.versao,
                models_dir=models_dir,
                hf_repo_id=hf_repo_id,
            )
            _, self.tagger_model, _ = criar_tagger_sem_brick(device=self.device)
            ckpt_tagger = torch.load(caminho_tagger, map_location="cpu", weights_only=False)
            self.tagger_model.classifier.load_state_dict(ckpt_tagger["classifier_state_dict"])
            self.tagger_model.to(self.device)
            self.tagger_model.eval()

            self.transform_tagger = T.Compose([
                T.Resize(266),
                T.CenterCrop(266),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])
            self.tags_nomes = TAGS_SEM_BRICK
        else:
            self.tagger_model = None
            self.tags_nomes = []

    def _normalizar_entradas(
        self,
        entrada: Union[str, Path, Image.Image, np.ndarray, Sequence[Any]],
        recursivo: bool = False,
    ) -> List[Tuple[str, Optional[str], Image.Image]]:
        """Normaliza qualquer formato de entrada em uma lista de tuplas (nome, caminho, PIL.Image)."""
        itens: List[Tuple[str, Optional[str], Image.Image]] = []

        if isinstance(entrada, (str, Path)):
            p = Path(entrada)
            if p.is_dir():
                padrao = "**/*" if recursivo else "*"
                arquivos = sorted([f for f in p.glob(padrao) if f.suffix.lower() in EXTENSOES_IMAGEM])
                if not arquivos:
                    raise FileNotFoundError(f"Nenhuma imagem suportada encontrada no diretório '{p}'.")
                for f in arquivos:
                    itens.append((f.name, str(f), Image.open(f).convert("RGB")))
            elif p.is_file():
                itens.append((p.name, str(p), Image.open(p).convert("RGB")))
            else:
                raise FileNotFoundError(f"Caminho não encontrado: '{p}'.")

        elif isinstance(entrada, Image.Image):
            itens.append(("imagem_0", None, entrada.convert("RGB")))

        elif isinstance(entrada, np.ndarray):
            itens.append(("imagem_0", None, Image.fromarray(entrada).convert("RGB")))

        elif isinstance(entrada, (list, tuple)):
            for i, elem in enumerate(entrada):
                if isinstance(elem, (str, Path)):
                    fp = Path(elem)
                    itens.append((fp.name, str(fp), Image.open(fp).convert("RGB")))
                elif isinstance(elem, Image.Image):
                    itens.append((f"imagem_{i}", None, elem.convert("RGB")))
                elif isinstance(elem, np.ndarray):
                    itens.append((f"imagem_{i}", None, Image.fromarray(elem).convert("RGB")))
                else:
                    raise TypeError(f"Elemento de tipo não suportado no lote: {type(elem)}")
        else:
            raise TypeError(f"Tipo de entrada não suportado: {type(entrada)}")

        return itens

    def predict(
        self,
        entrada: Union[str, Path, Image.Image, np.ndarray, Sequence[Any]],
        retornar_df: bool = False,
        salvar_em: Optional[Union[str, Path]] = None,
        limiar_defeito: float = 0.20,
        recursivo: bool = False,
    ) -> Union[List[Dict[str, Any]], pd.DataFrame]:
        """Executa a inferência sobre imagem única, lote ou diretório."""
        amostras = self._normalizar_entradas(entrada, recursivo=recursivo)
        resultados: List[Dict[str, Any]] = []

        for i in range(0, len(amostras), self.batch_size):
            lote = amostras[i : i + self.batch_size]
            lote_pils = [img for _, _, img in lote]

            # 1. Extração de features DINOv2-Large (1024D)
            inputs = self.processor(images=lote_pils, return_tensors="pt").to(self.device)
            with torch.no_grad():
                out = self.dino_model(**inputs)
                cls_tokens = out.last_hidden_state[:, 0, :].cpu().numpy()

            # 2. Predição da classe de qualidade
            preds_cls = self.clf_pipeline.predict(cls_tokens)
            if hasattr(self.clf_pipeline, "predict_proba"):
                probas_cls = self.clf_pipeline.predict_proba(cls_tokens)
            else:
                probas_cls = np.zeros((len(lote), len(self.classes)))

            # 3. Predição opcional das 11 tags de defeito
            tags_probs_lote: Optional[np.ndarray] = None
            if self.incluir_tags and self.tagger_model is not None:
                tensores_tagger = [self.transform_tagger(img) for img in lote_pils]
                bt = torch.stack(tensores_tagger).to(self.device)
                with torch.no_grad():
                    feat = self.tagger_model.transformer(bt)
                    feat_norm = self.tagger_model.transformer.norm(feat)
                    logits = self.tagger_model.classifier(feat_norm)
                    tags_probs_lote = torch.sigmoid(logits).cpu().numpy()

            # 4. Formatação dos resultados estruturados
            for j, (nome, caminho, _) in enumerate(lote):
                cid = int(preds_cls[j])
                c_nome = self.classes[cid] if cid < len(self.classes) else str(cid)
                c_conf = float(probas_cls[j, cid]) if probas_cls.shape[1] > cid else 1.0

                mapa_probs = {
                    self.classes[k]: float(round(probas_cls[j, k], 4))
                    for k in range(min(len(self.classes), probas_cls.shape[1]))
                }

                res: Dict[str, Any] = {
                    "imagem": nome,
                    "caminho": caminho,
                    "classe_id": cid,
                    "classe_predita": c_nome,
                    "confianca": round(c_conf, 4),
                    "probabilidades_classes": mapa_probs,
                }

                if tags_probs_lote is not None:
                    probs_item = tags_probs_lote[j]
                    mapa_tags = {
                        self.tags_nomes[k]: float(round(probs_item[k], 4))
                        for k in range(len(self.tags_nomes))
                    }
                    tags_ordenadas = sorted(
                        [
                            {"tag": t, "probabilidade": float(round(probs_item[k], 4))}
                            for k, t in enumerate(self.tags_nomes)
                        ],
                        key=lambda x: x["probabilidade"],
                        reverse=True,
                    )
                    principais = [d for d in tags_ordenadas if d["probabilidade"] >= limiar_defeito]
                    if not principais and tags_ordenadas:
                        principais = [tags_ordenadas[0]]

                    res["principais_defeitos"] = principais
                    res["tags_defeitos"] = mapa_tags

                resultados.append(res)

        # 5. Salvamento opcional em disco
        if salvar_em is not None:
            p_out = Path(salvar_em)
            p_out.parent.mkdir(parents=True, exist_ok=True)
            if p_out.suffix.lower() == ".csv":
                df_temp = pd.json_normalize(resultados)
                df_temp.to_csv(p_out, index=False, encoding="utf-8")
                print(f"[Inferência] Resultados salvos em CSV: '{p_out}'")
            elif p_out.suffix.lower() == ".json":
                import json
                with open(p_out, "w", encoding="utf-8") as f:
                    json.dump(resultados, f, indent=2, ensure_ascii=False)
                print(f"[Inferência] Resultados salvos em JSON: '{p_out}'")

        if retornar_df:
            return pd.json_normalize(resultados)

        return resultados

    def plotar_resultados(
        self,
        resultados: Union[List[Dict[str, Any]], pd.DataFrame],
        max_imagens: int = 10,
        colunas: int = 5,
        salvar_caminho: Optional[Union[str, Path]] = None,
    ) -> plt.Figure:
        """Renderiza visualmente as imagens avaliadas com título colorido e principais defeitos."""
        if isinstance(resultados, pd.DataFrame):
            itens = resultados.to_dict(orient="records")
        else:
            itens = resultados

        amostras = itens[:max_imagens]
        n = len(amostras)
        if n == 0:
            raise ValueError("Nenhum resultado para plotar.")

        linhas = int(np.ceil(n / colunas))
        fig, axes = plt.subplots(
            linhas,
            colunas,
            figsize=(colunas * 3.4, linhas * 3.8),
            constrained_layout=True,
            squeeze=False,
        )

        for idx in range(linhas * colunas):
            ax = axes[idx // colunas, idx % colunas]
            if idx < n:
                res = amostras[idx]
                caminho = res.get("caminho")
                nome = res.get("imagem", f"Img {idx}")
                cls_pred = res.get("classe_predita", "")
                conf = res.get("confianca", 0.0)

                if caminho and Path(caminho).exists():
                    img = Image.open(caminho).convert("RGB")
                    ax.imshow(img)
                else:
                    ax.text(0.5, 0.5, nome, ha="center", va="center")

                # Cor do título de acordo com a categoria predita
                cor = "#1e7e34" if cls_pred in ("Transitável", "Adequada") else "#d9534f"
                if "Não id" in cls_pred:
                    cor = "#6c757d"

                principais = res.get("principais_defeitos", [])
                sub_texto = ""
                if principais and isinstance(principais, list):
                    top2 = [f"{p['tag']} ({int(p['probabilidade']*100)}%)" for p in principais[:2]]
                    sub_texto = "\n" + " | ".join(top2)

                ax.set_title(
                    f"{cls_pred} ({conf*100:.1f}%){sub_texto}",
                    fontsize=9.5,
                    fontweight="bold",
                    color=cor,
                    pad=6,
                )
            ax.axis("off")

        if salvar_caminho:
            p_fig = Path(salvar_caminho)
            p_fig.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(p_fig, dpi=130)
            print(f"[Inferência] Gráfico salvo em: '{p_fig}'")

        return fig


def inferir_calcadas(
    entrada: Union[str, Path, Image.Image, np.ndarray, Sequence[Any]],
    cenario: str = "binario",
    versao: str = "v4",
    **kwargs: Any,
) -> Union[List[Dict[str, Any]], pd.DataFrame]:
    """Função utilitária rápida de conveniência para inferência direta."""
    pipeline = SidewalkPipeline(cenario=cenario, versao=versao, **kwargs)
    return pipeline.predict(entrada)
