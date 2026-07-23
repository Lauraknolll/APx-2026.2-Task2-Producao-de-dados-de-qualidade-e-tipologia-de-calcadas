# 📊 Dados do Projeto — AP[x]

Esta pasta organiza todos os dados utilizados e gerados pelo projeto.

---

## 📁 Estrutura

```
data/
├── raw/          # Dados brutos (como recebidos do IPPUC ou fontes oficiais)
├── processed/    # Dados tratados, limpos e prontos para uso
└── reports/    # Relatórios, gráficos, dashboards gerados
```

---

## 📥 raw/ — Dados Brutos

Aqui vão os dados **exatamente como fornecidos** pelo IPPUC ou obtidos de fontes oficiais.

### Regras
- ✅ NUNCA alterar os arquivos originais
- ✅ Manter o formato original (.csv, .xlsx, .json, .shp, etc.)
- ✅ Incluir um README para cada dataset explicando:
  - Fonte dos dados
  - Data de obtenção
  - Descrição dos campos
  - Contato no IPPUC que forneceu

### Exemplo de organização
```
data/raw/
├── zoneamento/
│   ├── zoneamento_2024.csv
│   └── README.md
├── uso_solo/
│   ├── uso_solo_2024.xlsx
│   └── README.md
└── README.md
```

---

## 🔄 processed/ — Dados Processados

Aqui vão os dados depois de passarem pelos scripts de limpeza e transformação.

### Regras
- ✅ Versionar junto com o código que gerou o processamento
- ✅ Documentar as transformações aplicadas
- ✅ Manter formato padronizado (preferencialmente .csv UTF-8)

---

## 📈 reporting/ — Relatórios e Gráficos

Artefatos gerados para comunicação com o IPPUC.

### Exemplos
- 📊 Gráficos (PNG, SVG)
- 📑 Relatórios em PDF
- 📓 Notebooks exportados (.html)
- 📋 Dashboards interativos

---

## ⚠️ Boas Práticas

1. **Arquivos grandes (> 50 MB)** — usar Git LFS ou armazenar externamente
2. **Dados sensíveis** — não versionar; documentar a origem e solicitar acesso direto
3. **Sempre documentar** a origem e as transformações aplicadas
4. **Prefira CSV UTF-8** como formato de intercâmbio
