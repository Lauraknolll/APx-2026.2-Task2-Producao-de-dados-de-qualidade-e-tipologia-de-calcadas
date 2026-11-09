# 🧰 Scripts Utilitários

Scripts reutilizáveis de apoio ao projeto: ingestão, transformação, consultas, etc.

## Organização

```
scripts/
├── ingestao/        # Scripts de coleta/carga de dados
│   └── coleta_streetview/   # Coleta de imagens de calçadas no Street View (ver README da pasta)
├── interface/       # Mapa das calçadas e o coletor (.exe): ruas coloridas pela avaliação, avaliação e coleta (ver README da pasta)
├── transformacao/   # Scripts de limpeza e transformação
└── utils/           # Funções auxiliares compartilhadas
```

A coleta do Street View roda da raiz do repositório com
`python -m scripts.ingestao.coleta_streetview`; instalação e uso no
[README dela](ingestao/coleta_streetview/README.md). O mapa da coleta abre com
`python -m scripts.interface`, ou pelo `.exe` do coletor ([README](interface/README.md)).

> Crie subpastas conforme a demanda crescer. Código bem modularizado é mais fácil de testar e reutilizar.
