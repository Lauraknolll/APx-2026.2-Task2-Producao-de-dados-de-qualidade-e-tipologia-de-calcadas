# Comece aqui: coletor de calçadas com avaliação automática

Esta pasta é o repositório do AP[x] Task 2 na branch
`feature/31-pipeline-unificado-de-inferencia`. Ela junta:

- a `main` (coleta no Street View e notebooks de modelagem);
- a interface do coletor (`feature/22-interface`): mapa, galeria, `.exe`;
- a publicação no Supabase (`feature/21-coleta-streetview`);
- a **avaliação automática da qualidade** (`scripts/inferencia/`). O modelo do Cenário 4
  classifica cada foto e pinta o mapa sem ninguém avaliar à mão.

O modelo treinado já está em `data/models/producao/classificador_qualidade.joblib`.
Ele reproduz o relatório v4: teste com acurácia de 75,65% e F1 macro de 0,664. Veja
`classificador_qualidade.json` ao lado.

## 1. Instalar (uma vez)

Requisitos: Windows 10/11, Python 3.12 ou mais novo
([python.org](https://www.python.org/downloads/), marque "Add to PATH"), internet e cerca de 3 GB livres.

No VS Code, abra esta pasta e um terminal (Ctrl+`), e rode:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # só se o Windows bloquear scripts
.\instalar.ps1
```

O script cria o `.venv`, instala as dependências (PyTorch, transformers, scikit-learn...)
e confere se a interface e o modelo carregam. Leva alguns minutos.

## 2. Rodar

No VS Code, abra a aba **Executar e Depurar** (Ctrl+Shift+D), escolha a configuração e aperte **F5**:

| Configuração | O que faz |
|---|---|
| **Abrir o coletor (janela)** | A janela do coletor. Clique em *Abrir o mapa* para coletar e ver as ruas |
| Abrir só o mapa (navegador) | A mesma página, sem a janela |
| Coletar uma rua (terminal) | O menu da coleta no terminal |
| **Avaliar com o modelo as fotos já coletadas** | Classifica as fotos que ainda não têm avaliação |
| Refazer as avaliações do modelo | Depois de trocar o `.joblib`. As avaliações manuais são mantidas |
| Treinar o modelo (Cenário 4) | Gera um `.joblib` novo (ver passo 4) |

Na primeira coleta e na primeira avaliação, o programa baixa dois modelos, uma vez só:
o de segmentação (~210 MB) e o backbone do Project Sidewalk (~1,2 GB, Hugging Face).

## 3. Testar a avaliação automática

1. Abra o coletor, clique em *Abrir o mapa* e depois em **Coletar uma rua**.
2. Digite *Rua Comendador Araújo*, clique em **Procurar**, ponha **3** zonas e clique em **Coletar**.
3. A coleta tem 4 etapas. Na 4ª, "Avaliando a qualidade", o modelo classifica as fotos.
4. Clique numa foto no mapa e abra **Avaliar**. Cada quadrado mostra "modelo · XX% de confiança".
   Para corrigir, clique em outra classe. A correção manual nunca é desfeita pelo modelo.

O teste do modelo (fotos com a classe real e a prevista, matriz de confusão, erros por rua)
fica em `data/reports/modelo_producao/` depois de rodar o treino.

## 4. Retreinar o modelo (opcional)

```powershell
.\instalar.ps1 -Treino
```

Preencha a seção **PREENCHA AQUI** no topo do `treinar_modelo.py` (chave e workspace do
Roboflow), ou ponha `ROBOFLOW_API_KEY=...` e `ROBOFLOW_WORKSPACE_NAME=...` no `.env`.
Depois rode a configuração *Treinar o modelo*. **Não faça commit com a chave preenchida.**

## 5. Gerar o .exe (opcional)

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller scripts\interface\exe\calcadas.spec
```

O `.exe` sai em `dist\Calcadas\` com o modelo dentro.

## Para saber mais

- `scripts/inferencia/README.md`: como a avaliação automática funciona e por que o Cenário 4
- `scripts/interface/README.md` e `docs/coletor-de-calcadas.md`: a interface
- `scripts/ingestao/coleta_streetview/README.md`: a coleta

## Git

Para a pasta ficar leve, ela não traz o histórico do Git (`.git`). Os commits novos estão em
`feature-31-pipeline.bundle`. Para publicar a branch, a partir de um clone do repositório:

```powershell
git clone https://github.com/Lauraknolll/APx-2026.2-Task2-Producao-de-dados-de-qualidade-e-tipologia-de-calcadas.git apx-git
cd apx-git
git fetch ..\<esta-pasta>\feature-31-pipeline.bundle feature/31-pipeline-unificado-de-inferencia:feature/31-pipeline-unificado-de-inferencia
git checkout feature/31-pipeline-unificado-de-inferencia
git push -u origin feature/31-pipeline-unificado-de-inferencia
```

O `.joblib` não vai para o Git (`.gitignore`). Guarde-o no Drive ou no Storage do Supabase.
