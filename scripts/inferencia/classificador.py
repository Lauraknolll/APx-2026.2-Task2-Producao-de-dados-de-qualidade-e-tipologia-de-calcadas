"""
O classificador de qualidade das calçadas, pronto para produção.

Uma foto (quadrado de calçada) passa pelo backbone DINOv2 do Project Sidewalk
(token [CLS], 1024D — o mesmo de scripts/transformacao/extract_features.py)
e o embedding vai para o pipeline do scikit-learn treinado no linear probing
(scripts/utils/linear_probing.py). A saída já vem nas classes da interface
(banco.CLASSES_AVALIACAO), com a probabilidade da classe escolhida.

O .joblib é um dicionário. Os de data/models/v4/ (notebook 05) têm só
{"pipeline", "classes"}; os gerados por `scripts.inferencia.treinar` têm
também "backbone", "nome" e "metricas". Os dois servem:

    clf = ClassificadorQualidade.carregar(caminho)
    clf.classificar([Path("1_2_3.jpg"), ...])  ->  [("adequada", 0.91), ...]
"""

import unicodedata
from pathlib import Path
from typing import Iterable, Optional

# Nome da classe no modelo (sem acento, minúsculo) -> classe da interface.
# Cobre as taxonomias de scripts/utils/data_utils.TAXONOMIAS que cabem nas
# cinco classes do mapa; a binária (Transitável vs Crítica) não cabe.
PARA_INTERFACE = {
    "adequada": "adequada",
    "parcial": "parcialmente_adequada",
    "parcialmente adequado": "parcialmente_adequada",
    "parcialmente adequada": "parcialmente_adequada",
    "inadequada": "inadequada",
    "inadequada geral": "inadequada",
    "com defeito": "inadequada",
    "inad.+semcalcada": "inadequada",
    "sem calcada": "sem_calcada",
    "nao id.": "nao_identificavel",
    "nao identificavel": "nao_identificavel",
}


def _chave(nome: str) -> str:
    return unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower().strip()


def classe_da_interface(nome: str) -> str:
    try:
        return PARA_INTERFACE[_chave(nome)]
    except KeyError:
        raise ValueError(f"A classe {nome!r} do modelo não corresponde a nenhuma classe do mapa "
                         f"({', '.join(sorted(set(PARA_INTERFACE.values())))}).") from None


class ClassificadorQualidade:
    def __init__(self, pipeline, classes: list[str], backbone: str, nome: str,
                 confianca_min: float = 0.0, lote: int = 16):
        self.pipeline = pipeline
        self.classes = list(classes)
        self.para_interface = [classe_da_interface(c) for c in self.classes]  # falha já, se não couber
        self.backbone = backbone
        self.nome = nome
        self.confianca_min = confianca_min
        self.lote = lote
        self._proc = self._modelo = self._disp = None

    @classmethod
    def carregar(cls, caminho: Path, backbone_padrao: str, confianca_min: float = 0.0,
                 lote: int = 16) -> "ClassificadorQualidade":
        import joblib

        ckpt = joblib.load(caminho)
        if not isinstance(ckpt, dict) or "pipeline" not in ckpt or "classes" not in ckpt:
            raise ValueError(f"{caminho} não é um classificador do projeto (esperado um dict com "
                             "'pipeline' e 'classes').")
        return cls(ckpt["pipeline"], ckpt["classes"], ckpt.get("backbone") or backbone_padrao,
                   ckpt.get("nome") or Path(caminho).stem, confianca_min, lote)

    # ------------------------------------------------------------------ #

    def _garantir_backbone(self):
        if self._modelo is not None:
            return
        from transformers import AutoImageProcessor, AutoModel

        from scripts.utils.device import get_device

        self._disp = get_device()
        self._proc = AutoImageProcessor.from_pretrained(self.backbone)
        self._modelo = AutoModel.from_pretrained(self.backbone).to(self._disp).eval()

    def embeddings(self, imagens: list) -> "np.ndarray":
        """Token [CLS] de cada imagem (PIL), como no treino."""
        import numpy as np
        import torch

        self._garantir_backbone()
        saida = []
        for i in range(0, len(imagens), self.lote):
            entradas = self._proc(images=imagens[i:i + self.lote], return_tensors="pt").to(self._disp)
            with torch.no_grad():
                cls_token = self._modelo(**entradas).last_hidden_state[:, 0, :]
            saida.append(cls_token.float().cpu().numpy())
        return np.vstack(saida) if saida else np.zeros((0, 0))

    def prever(self, X) -> list[tuple[str, Optional[float]]]:
        """(classe da interface, probabilidade) para cada embedding."""
        import numpy as np

        if hasattr(self.pipeline, "predict_proba"):
            probs = self.pipeline.predict_proba(X)
            # As colunas seguem pipeline.classes_ (os rótulos numéricos do treino).
            rotulos = list(self.pipeline.classes_)
            idx = probs.argmax(axis=1)
            resultado = [(int(rotulos[j]), float(probs[k, j])) for k, j in enumerate(idx)]
        else:
            resultado = [(int(r), None) for r in self.pipeline.predict(X)]
        saida = []
        for rotulo, conf in resultado:
            classe = self.para_interface[rotulo]
            if conf is not None and conf < self.confianca_min:
                classe = "nao_identificavel"
            saida.append((classe, conf))
        return saida

    def classificar(self, caminhos: Iterable[Path]) -> list[tuple[str, Optional[float]]]:
        from PIL import Image

        imagens = [Image.open(c).convert("RGB") for c in caminhos]
        if not imagens:
            return []
        return self.prever(self.embeddings(imagens))
