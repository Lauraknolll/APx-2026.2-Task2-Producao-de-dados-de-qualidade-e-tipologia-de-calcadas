# Instala o ambiente do coletor de calçadas (coleta + interface + avaliação automática).
# Da raiz do repositório, no PowerShell:
#     .\instalar.ps1              # ambiente da coleta e da interface (.venv)
#     .\instalar.ps1 -Treino      # também o ambiente de treino do modelo (.venv-treino)
#
# Se o Windows bloquear o script ("execução de scripts foi desabilitada"), rode antes:
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

param([switch]$Treino)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Achar-Python([string[]]$versoes) {
    foreach ($v in $versoes) {
        try { & py "-$v" -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { return $v } } catch {}
    }
    return $null
}

# --- Ambiente da coleta e da interface ------------------------------------- #
# O README da coleta usa Python 3.14; 3.13 e 3.12 também servem.
$py = Achar-Python @("3.14", "3.13", "3.12")
if (-not $py) {
    Write-Host "Nenhum Python 3.12+ encontrado pelo launcher 'py'. Instale em https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}
Write-Host "== Ambiente da coleta (.venv) com Python $py" -ForegroundColor Cyan
if (-not (Test-Path .venv)) { & py "-$py" -m venv .venv }
$pip = ".venv\Scripts\python.exe"
& $pip -m pip install --upgrade pip
& $pip -m pip install -r scripts\ingestao\coleta_streetview\requirements.txt
& $pip -m pip install --no-deps streetlevel

# --- GPU -------------------------------------------------------------------- #
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $cuda = & $pip -c "import torch; print(torch.cuda.is_available())"
    if ($cuda -ne "True") {
        Write-Host ""
        Write-Host "Há uma GPU NVIDIA, mas o PyTorch instalado roda só na CPU." -ForegroundColor Yellow
        Write-Host "Para usar a GPU (mais rápido na segmentação e na avaliação), pegue o comando em"
        Write-Host "https://pytorch.org/get-started/locally/ (Windows, Pip, Python, CUDA <= a do nvidia-smi)"
        Write-Host "e rode-o com .venv\Scripts\python.exe -m pip install ... --force-reinstall"
    }
}

# --- Conferência ------------------------------------------------------------ #
& $pip -c "import scripts.interface.servidor, scripts.inferencia.etapa; print('Imports OK')"
if (Test-Path data\models\producao\classificador_qualidade.joblib) {
    & $pip -c @"
from pathlib import Path
from scripts.inferencia.classificador import ClassificadorQualidade
c = ClassificadorQualidade.carregar(Path('data/models/producao/classificador_qualidade.joblib'), '')
print('Modelo OK:', c.nome, '->', ', '.join(c.para_interface))
"@
} else {
    Write-Host "Sem data\models\producao\classificador_qualidade.joblib: a coleta funciona, mas sem avaliação automática." -ForegroundColor Yellow
}

# --- Ambiente de treino (opcional) ------------------------------------------ #
if ($Treino) {
    $pyt = Achar-Python @("3.11", "3.12")
    if (-not $pyt) { Write-Host "Treino: instale o Python 3.11 ou 3.12." -ForegroundColor Red; exit 1 }
    Write-Host "== Ambiente de treino (.venv-treino) com Python $pyt" -ForegroundColor Cyan
    if (-not (Test-Path .venv-treino)) { & py "-$pyt" -m venv .venv-treino }
    & .venv-treino\Scripts\python.exe -m pip install --upgrade pip
    & .venv-treino\Scripts\python.exe -m pip install -r requirements-treino.txt
}

Write-Host ""
Write-Host "Pronto. No VS Code: aba 'Executar e Depurar' (Ctrl+Shift+D) -> 'Abrir o coletor (janela)' -> F5." -ForegroundColor Green
Write-Host "Pelo terminal: .venv\Scripts\python.exe -m scripts.interface.janela"
