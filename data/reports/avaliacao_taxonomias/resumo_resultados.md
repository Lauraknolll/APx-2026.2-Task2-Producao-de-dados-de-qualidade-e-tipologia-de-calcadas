# Relatório Consolidado: Avaliação de Taxonomias (Linear Probing v3)

| Cenário | Modelo | Pré-proc. | Undersampling | Acc (Val) | Macro F1 (Val) | Acc (Teste) | Bal. Acc (Teste) | Macro F1 (Teste) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cenário 1: 5 Classes Originais (Baseline MLP)** | `MLP (256)` | `raw` | `Nenhum` | 67.33% | 0.5228 | **58.67%** | **38.29%** | **0.4021** |
| **Cenário 2: 4 Classes com Não Identificável (Inadequada + Sem calçada unidas)** | `SVC RBF (C=3.0, balanced)` | `l2_pca64` | `70` | 60.00% | 0.5244 | **62.67%** | **65.03%** | **0.6223** |
| **Cenário 3: 3 Classes sem Não Identificável (Adequada | Com Defeito | Sem calçada)** | `Random Forest (100, balanced)` | `l2_pca64` | `100` | 76.81% | 0.7851 | **71.88%** | **72.31%** | **0.7117** |
| **Cenário 4: 3 Classes com Não Identificável (Adequada | Inadequada Geral | Não id.)** | `MLP (128, alpha=0.5, early_stopping)` | `l2_std` | `Nenhum` | 72.00% | 0.5978 | **78.67%** | **71.47%** | **0.7341** |
| **Cenário 5: 2 Classes Binária Crítica sem Não Identificável (Transitável vs Crítica)** | `Regressão Logística (C=0.5, balanced)` | `l2_pca64` | `100` | 87.68% | 0.8535 | **89.06%** | **90.70%** | **0.8744** |

## Detalhamento de F1 por Classe (Conjunto de Teste)

### Cenário 1: 5 Classes Originais (Baseline MLP)
- **Descrição**: Todas as 5 classes separadas sem pré-processamento e sem balanceamento.
- **F1 por Classe**: **Adequada**: `0.78` | **Parcial**: `0.00` | **Inadequada**: `0.22` | **Sem calçada**: `0.58` | **Não id.**: `0.43`
- **Matriz de Confusão**: `matrizes_confusao/01_5classes_baseline.png`

### Cenário 2: 4 Classes com Não Identificável (Inadequada + Sem calçada unidas)
- **Descrição**: Une Inadequada e Sem calçada na mesma categoria crítica, mantendo Parcial e Não identificável.
- **F1 por Classe**: **Adequada**: `0.62` | **Parcial**: `0.34` | **Inad.+SemCalçada**: `0.82` | **Não id.**: `0.70`
- **Matriz de Confusão**: `matrizes_confusao/02_4classes_com_naoid.png`

### Cenário 3: 3 Classes sem Não Identificável (Adequada | Com Defeito | Sem calçada)
- **Descrição**: Remove a classe de ruído (Não identificável) e agrupa Parcial + Inadequada como calçadas com defeito.
- **F1 por Classe**: **Adequada**: `0.79` | **Com Defeito**: `0.59` | **Sem calçada**: `0.76`
- **Matriz de Confusão**: `matrizes_confusao/03_3classes_sem_naoid.png`

### Cenário 4: 3 Classes com Não Identificável (Adequada | Inadequada Geral | Não id.)
- **Descrição**: Mantém a classe de rejeição (Não id.) para uso em produção e consolida inconformidades em Inadequada Geral.
- **F1 por Classe**: **Adequada**: `0.79` | **Inadequada Geral**: `0.85` | **Não id.**: `0.56`
- **Matriz de Confusão**: `matrizes_confusao/04_3classes_com_naoid.png`

### Cenário 5: 2 Classes Binária Crítica sem Não Identificável (Transitável vs Crítica)
- **Descrição**: Separa calçadas transitáveis (Adequada + Parcial) de situações críticas (Inadequada + Sem calçada).
- **F1 por Classe**: **Transitável**: `0.92` | **Crítica (Inad+SemCalc)**: `0.83`
- **Matriz de Confusão**: `matrizes_confusao/05_2classes_sem_naoid.png`
