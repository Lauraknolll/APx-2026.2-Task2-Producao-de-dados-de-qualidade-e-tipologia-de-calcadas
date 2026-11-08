# Modelos e Checkpoints (`data/models/`)

Este diretório centraliza os pesos e pipelines treinados para os dados de calçadas de Curitiba, organizados por versão de dataset (`v3/` e `v4/`) e baselines originais (`baselines/`).

> **Nota:** Todos os binários de modelos (`*.pth`, `*.joblib`) são mantidos localmente e ignorados pelo `.gitignore` para preservar o versionamento do repositório.

---

## Estrutura do Diretório

```
data/models/
├── v4/                                                    # Modelos treinados com Dataset v4 (10 ruas, 1.171 imagens)
│   ├── tagger_sem_brick.pth                               # Cabeça linear (11 classes) sem falso-positivo de petit-pavé
│   ├── classificador_cenario04_3classes_com_naoid.joblib  # Pipeline MLP Cenário 4 (Adequada | Inadequada Geral | Não ID)
│   ├── classificador_cenario05_2classes_binario.joblib    # Pipeline LogReg Cenário 5 (Transitável vs Crítica - 85.4% Acc)
│   └── classificador_cenario03_3classes_sem_naoid.joblib  # Pipeline Random Forest Cenário 3 (Adequada | Com Defeito | Sem calçada)
│
├── v3/                                                    # Modelos de referência treinados com Dataset v3 (6 ruas, 750 imagens)
│   ├── tagger_sem_brick.pth                               # Cabeça linear (11 classes) calibrada no v3
│   ├── classificador_cenario04_3classes_com_naoid.joblib  # Pipeline MLP Cenário 4 no v3
│   ├── classificador_cenario05_2classes_binario.joblib    # Pipeline LogReg Cenário 5 no v3
│   └── classificador_cenario03_3classes_sem_naoid.joblib  # Pipeline Random Forest Cenário 3 no v3
│
└── baselines/                                             # Modelos originais do Project Sidewalk
    ├── sidewalk_dinov2_base_backbone.pth                  # Backbone DINOv2-Base pré-treinado (768D)
    └── sidewalk_validator_severity.pth                    # Validador de severidade original
```

---

## Como Carregar e Usar em Python

### 1. Classificadores de Taxonomia (`.joblib`)
Cada arquivo `.joblib` contém um dicionário autocontido com o pipeline completo (pré-processamento + classificador):

```python
import joblib

# Carrega o classificador do Cenário 4 (v4)
ckpt = joblib.load("data/models/v4/classificador_cenario04_3classes_com_naoid.joblib")
pipeline = ckpt["pipeline"]
classes = ckpt["classes"]  # ['Adequada', 'Inadequada Geral', 'Não id.']

# Predição direta a partir dos embeddings DINOv2 (1024D)
preds = pipeline.predict(X_embeddings)
preds_labels = [classes[i] for i in preds]
```

### 2. Tagger Multi-Label de Defeitos (`.pth`)
```python
import torch
from scripts.utils.sidewalk_inference import criar_tagger_sem_brick

# Carrega pesos da cabeça com 11 defeitos sem brick
transform, model, dev = criar_tagger_sem_brick(device="cpu")
state = torch.load("data/models/v4/tagger_sem_brick.pth", map_location="cpu", weights_only=False)
model.classifier.load_state_dict(state["classifier_state_dict"])
model.eval()
```
