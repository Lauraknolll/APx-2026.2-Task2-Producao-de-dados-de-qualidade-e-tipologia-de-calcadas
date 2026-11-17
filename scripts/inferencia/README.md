# 🚀 Módulo de Inferência de Calçadas (`scripts/inferencia/`)

Pipeline unificado e autocontido de inferência de ponta a ponta para classificação de qualidade viária e diagnóstico de problemas físicos em calçadas de Curitiba.

---

## Como Utilizar em Código (Python)

### 1. Inicialização do Pipeline

```python
from scripts.inferencia import SidewalkPipeline

# Inicializa com o cenário recomendado para o IPPUC (Binário: Transitável vs Crítica)
pipeline = SidewalkPipeline(
    cenario="binario",  # ou "3classes" (Adequada | Inadequada Geral | Não id.)
    versao="v4",        # modelos calibrados no dataset v4
    incluir_tags=True,  # ativa diagnóstico de 11 defeitos pelo Tagger
)
```

> **Resolução de Pesos:** O pipeline busca os pesos automaticamente em `data/models/v4/`. Caso não existam localmente, faz o download automático via Hugging Face Hub (`caduobristo/calcadas-curitiba`).

---

### 2. Formas de Entrada Flexíveis

#### A) Imagem Única (ideal para APIs e interfaces)
```python
# Aceita caminho em string, Path, ou imagem PIL já aberta em memória
resultado = pipeline.predict("caminho/para/imagem.jpg")
print(resultado[0]["classe_predita"])  # 'Transitável' ou 'Crítica'
print(resultado[0]["confianca"])       # 0.8942
print(resultado[0]["principais_defeitos"])
# [{'tag': 'cracks', 'probabilidade': 0.621}, {'tag': 'bumpy', 'probabilidade': 0.543}]
```

#### B) Lote de Imagens (Lista)
```python
lista_fotos = ["foto1.jpg", "foto2.jpg", "foto3.jpg"]
resultados = pipeline.predict(lista_fotos)
```

#### C) Diretório Completo (ideal para batches do Street View)
```python
# Processa todas as imagens da pasta e já exporta para CSV
df = pipeline.predict(
    "data/raw/apx2-bzsou-v4/test",
    retornar_df=True,
    salvar_em="relatorio_predicoes.csv"
)
```

#### D) Visualização Gráfica
```python
fig = pipeline.plotar_resultados(resultados, max_imagens=10, salvar_caminho="diagnostico.png")
```

---

## Como Utilizar via Linha de Comando (CLI)

```bash
# Inferência em uma pasta inteira salvando CSV
python -m scripts.inferencia --input data/raw/apx2-bzsou-v4/test --cenario binario --output predicoes.csv

# Inferência em imagem avulsa salvando plot
python -m scripts.inferencia --input foto_calcada.jpg --plot diagnostico.png
```
