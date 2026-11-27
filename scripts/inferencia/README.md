# Inferência de qualidade e diagnóstico de calçadas

## Pipeline unificado

Pipeline unificado e autocontido de inferência de ponta a ponta para classificação de qualidade viária e diagnóstico de problemas físicos em calçadas de Curitiba.

### Uso em Python

#### Inicialização do pipeline

```python
from scripts.inferencia import SidewalkPipeline

# Inicializa com o cenário recomendado para o IPPUC (Binário: Transitável vs Crítica)
pipeline = SidewalkPipeline(
    cenario="binario",  # ou "3classes" (Adequada | Inadequada Geral | Não id.)
    versao="v4",        # modelos calibrados no dataset v4
    incluir_tags=True,  # ativa diagnóstico de 11 defeitos pelo Tagger
)
```

> O pipeline busca os pesos automaticamente em `data/models/v4/`. Caso não existam localmente, faz o download automático via Hugging Face Hub (`caduobristo/calcadas-curitiba`).

#### Formas de entrada

##### Imagem única
```python
# Aceita caminho em string, Path, ou imagem PIL já aberta em memória
resultado = pipeline.predict("caminho/para/imagem.jpg")
print(resultado[0]["classe_predita"])  # 'Transitável' ou 'Crítica'
print(resultado[0]["confianca"])       # 0.8942
print(resultado[0]["principais_defeitos"])
# [{'tag': 'cracks', 'probabilidade': 0.621}, {'tag': 'bumpy', 'probabilidade': 0.543}]
```

##### Lote de imagens
```python
lista_fotos = ["foto1.jpg", "foto2.jpg", "foto3.jpg"]
resultados = pipeline.predict(lista_fotos)
```

##### Diretório de imagens
```python
# Processa todas as imagens da pasta e já exporta para CSV
df = pipeline.predict(
    "data/raw/apx2-bzsou-v4/test",
    retornar_df=True,
    salvar_em="relatorio_predicoes.csv"
)
```

##### Visualização gráfica
```python
fig = pipeline.plotar_resultados(resultados, max_imagens=10, salvar_caminho="diagnostico.png")
```

### Uso pela linha de comando

```bash
# Inferência em uma pasta inteira salvando CSV
python -m scripts.inferencia --input data/raw/apx2-bzsou-v4/test --cenario binario --output predicoes.csv

# Inferência em imagem avulsa salvando plot
python -m scripts.inferencia --input foto_calcada.jpg --plot diagnostico.png
```

## Avaliação automática na coleta Street View

Cada quadrado de calçada que a coleta aprova (`scripts/ingestao/coleta_streetview`)
é classificado pelo modelo de produção. O resultado vai para a tabela
`avaliacoes` com `origem = "modelo"` e a confiança, e é o que colore as
ruas no mapa da interface (`scripts/interface`). Assim, ninguém precisa
avaliar as fotos à mão.

```
foto do quadrado ─► backbone DINOv2 do Project Sidewalk ─► [CLS] 1024D ─► pipeline sklearn (Cenário 4) ─► classe + confiança
                    projectsidewalk/sidewalk-validator-ai-surfaceproblem                      L2 + StandardScaler + MLP(128)
```

O modelo é o **Cenário 4** do benchmark v4 (`data/reports/avaliacao_taxonomias_v4/`):
*Adequada | Inadequada Geral | Não identificável* (75,6% de acurácia e
0,66 de F1 macro no teste). Ele foi escolhido porque cabe direto nas
classes do mapa e tem uma classe de rejeição: sem ninguém revisando, uma
foto ruim vira "não identificável" e fica fora da nota da rua, em vez de ser
forçada para adequada ou inadequada. O binário (Cenário 5) acerta mais, mas
não tem essa classe nem cabe nas classes do mapa.

| Classe do modelo | Classe no mapa | Nota |
|---|---|---|
| Adequada | `adequada` | 1 |
| Inadequada Geral (parcial + inadequada + sem calçada) | `inadequada` | 0,4 |
| Não id. | `nao_identificavel` | fora da média |

### Gerar o modelo

> **Recomendado:** `treinar_modelo.py`, na raiz. É um arquivo só, com os campos do Roboflow
> marcados em "PREENCHA AQUI", e gera também o relatório do teste em
> `data/reports/modelo_producao/` (predições por imagem, matriz de confusão, amostras de
> acertos e erros). O `scripts.inferencia.treinar` abaixo faz o mesmo treino usando os
> utilitários de `scripts/utils/`.

Da raiz do repositório, com o ambiente dos notebooks (`requirements.txt`) e o
`.env` com as chaves do Roboflow:

```bash
python -m scripts.inferencia.treinar
```

O script baixa o dataset do Roboflow (ou usa `--dataset data/raw/<pasta>`),
extrai os embeddings (com cache em `data/processed/<dataset>/`), treina com a
receita do Cenário 4 (`scripts/utils/linear_probing.CENARIOS`), mostra as
métricas de validação e teste e grava:

- `data/models/producao/classificador_qualidade.joblib`: pipeline, classes,
  backbone e métricas;
- `classificador_qualidade.json`, ao lado, com o resumo legível.

Por padrão, o modelo final é treinado de novo com treino + validação (as
métricas mostradas são as do modelo treinado só com o treino). Use
`--so-treino` para não fazer isso, e `--cenario` para outra receita: só as
que cabem nas classes do mapa são aceitas.

**Atalho:** os `.joblib` de `data/models/v4/` (notebook 05) também servem.
Basta copiar `classificador_cenario04_3classes_com_naoid.joblib` para
`data/models/producao/classificador_qualidade.joblib`.

> O arquivo em `data/models/producao/` fica fora do Git. Os classificadores
> de `data/models/v4/` estão no repositório.

### Avaliar

- **Coletas novas:** é automático. A coleta de uma rua tem agora uma 4ª
  etapa, "Avaliando a qualidade das calçadas", que roda pelo terminal e pela
  interface (`.exe`). Sem o `.joblib`, a etapa é pulada com um aviso e as
  fotos ficam salvas.
- **Ruas já coletadas:**

  ```bash
  python -m scripts.ingestao.coleta_streetview avaliar                 # tudo que falta
  python -m scripts.ingestao.coleta_streetview avaliar --rua "Rua X"   # uma rua
  python -m scripts.ingestao.coleta_streetview avaliar --refazer       # refaz as do modelo (ex.: modelo novo)
  ```

  Na interface, *Procurar* uma rua já coletada mostra quantas fotos estão sem
  avaliação, e *Coletar* avalia essas fotos.

Regras:

- **A avaliação manual vence.** O modelo nunca sobrescreve uma avaliação
  feita à mão, nem com `--refazer`. Avaliar à mão na interface passa a ser
  uma correção opcional.
- **Confiança mínima** (`--confianca-min`, ou `CONFIANCA_MIN` em
  `coleta_streetview/config.py`, que vem desligado): abaixo dela, o quadrado
  vira `nao_identificavel`. Use se aparecerem muitos erros com baixa
  confiança.
- O backbone (~1,2 GB) é baixado do Hugging Face na primeira vez e fica em
  cache. Ele usa a GPU (CUDA ou DirectML) quando houver, como a segmentação.

### Arquivos da avaliação automática

| Arquivo | O que faz |
|---|---|
| `classificador.py` | Carrega o `.joblib`, extrai o [CLS] e traduz a classe para a do mapa |
| `etapa.py` | A etapa `avaliar` da coleta: o que falta, o lote e a gravação em `avaliacoes` |
| `treinar.py` | Gera o modelo de produção a partir do dataset do Roboflow |
