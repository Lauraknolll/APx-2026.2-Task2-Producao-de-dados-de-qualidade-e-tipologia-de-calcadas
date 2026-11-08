# Relatório Consolidado: Avaliação de Taxonomias (Linear Probing v4)

| Cenário | Modelo | Pré-proc. | Undersampling | Acc (Val) | Macro F1 (Val) | Weighted F1 (Val) | Acc (Teste) | Bal. Acc (Teste) | Macro F1 (Teste) | Weighted F1 (Teste) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cenário 1: 5 Classes Originais (Baseline MLP)** | `MLP (256)` | `raw` | `Nenhum` | 58.12% | 0.4484 | 0.5489 | **62.61%** | **48.45%** | **0.5006** | **0.6070** |
| **Cenário 3: 3 Classes sem Não Identificável (Adequada | Com Defeito | Sem calçada)** | `Random Forest (100, balanced)` | `l2_pca64` | `100` | 73.93% | 0.7805 | 0.7426 | **65.05%** | **66.32%** | **0.6535** | **0.6575** |
| **Cenário 4: 3 Classes com Não Identificável (Adequada | Inadequada Geral | Não id.)** | `MLP (128, alpha=0.5, early_stopping)` | `l2_std` | `Nenhum` | 68.80% | 0.5424 | 0.6697 | **75.65%** | **64.67%** | **0.6640** | **0.7477** |
| **Cenário 5: 2 Classes Binária Crítica sem Não Identificável (Transitável vs Crítica)** | `Regressão Logística (C=0.5, balanced)` | `l2_pca64` | `100` | 83.41% | 0.8079 | 0.8405 | **85.44%** | **85.59%** | **0.8445** | **0.8563** |

## Detalhamento de F1 por Classe (Conjunto de Teste)

### Cenário 1: 5 Classes Originais (Baseline MLP)
- **Descrição**: Todas as 5 classes separadas sem pré-processamento e sem balanceamento.
- **F1 por Classe**: **Adequada**: `0.79` | **Parcial**: `0.30` | **Inadequada**: `0.50` | **Sem calçada**: `0.60` | **Não id.**: `0.32`
- **Matriz de Confusão**: `matrizes_confusao/01_5classes_baseline.png`

### Cenário 3: 3 Classes sem Não Identificável (Adequada | Com Defeito | Sem calçada)
- **Descrição**: Remove a classe de ruído (Não identificável) e agrupa Parcial + Inadequada como calçadas com defeito.
- **F1 por Classe**: **Adequada**: `0.70` | **Com Defeito**: `0.52` | **Sem calçada**: `0.74`
- **Matriz de Confusão**: `matrizes_confusao/03_3classes_sem_naoid.png`

### Cenário 4: 3 Classes com Não Identificável (Adequada | Inadequada Geral | Não id.)
- **Descrição**: Mantém a classe de rejeição (Não id.) para uso em produção e consolida inconformidades em Inadequada Geral.
- **F1 por Classe**: **Adequada**: `0.80` | **Inadequada Geral**: `0.77` | **Não id.**: `0.42`
- **Matriz de Confusão**: `matrizes_confusao/04_3classes_com_naoid.png`

### Cenário 5: 2 Classes Binária Crítica sem Não Identificável (Transitável vs Crítica)
- **Descrição**: Separa calçadas transitáveis (Adequada + Parcial) de situações críticas (Inadequada + Sem calçada).
- **F1 por Classe**: **Transitável**: `0.88` | **Crítica (Inad+SemCalc)**: `0.81`
- **Matriz de Confusão**: `matrizes_confusao/05_2classes_sem_naoid.png`
