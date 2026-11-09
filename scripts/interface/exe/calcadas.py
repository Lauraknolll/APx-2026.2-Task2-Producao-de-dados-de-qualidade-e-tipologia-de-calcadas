"""
Ponto de entrada do .exe (calcadas.spec): abre a janela (scripts/interface/janela.py).

O .exe também roda os módulos que a interface chama em subprocesso (a coleta
e a publicação), já que não há um `python` para chamar:
    Calcadas.exe --modulo scripts.ingestao.coleta_streetview rua --nome "..."
"""

import os
import runpy
import shutil
import sys
from pathlib import Path


def _saidas():
    """Sem console (o .exe é de janela), stdout e stderr vêm vazios: os
    subprocessos escrevem no cano que a interface lê; a janela, em lugar nenhum.

    E sempre em UTF-8, uma linha de cada vez: o Python do .exe ignora o
    PYTHONIOENCODING e o PYTHONUNBUFFERED que a interface passa (servidor.py),
    e sem isso escreveria no código de página do Windows (os acentos chegam
    trocados) e guardaria o log até encher o buffer (a etapa não andava)."""
    for nome, fd in (("stdout", 1), ("stderr", 2)):
        saida = getattr(sys, nome)
        if saida is None:
            try:
                setattr(sys, nome, open(fd, "w", encoding="utf-8", errors="replace", buffering=1, closefd=False))
            except OSError:
                setattr(sys, nome, open(os.devnull, "w", encoding="utf-8"))
        elif hasattr(saida, "reconfigure"):
            saida.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _semear_dados():
    """Copiado para fora do repositório, o .exe traz consigo a camada de
    calçadas, os traçados das ruas (data/raw/) e o modelo de qualidade
    (data/models/producao/), para a coleta começar do zero. Só copia o que
    falta: um .exe novo, com um modelo que a pasta ainda não tem, completa a
    pasta sem mexer no que já foi coletado."""
    exe = Path(sys.executable).resolve().parent
    raiz = next((p for p in (exe, *exe.parents) if (p / "data" / "raw" / "_Passeio_CWB.zip").is_file()), None)
    if raiz is not None and raiz != exe:
        return  # dentro do repositório (dist/): usa os dados dele
    semente = Path(getattr(sys, "_MEIPASS", exe)) / "semente"
    if not semente.is_dir():
        return
    for arquivo in semente.rglob("*"):
        destino = exe / arquivo.relative_to(semente)
        if arquivo.is_file() and not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo, destino)


_saidas()
if getattr(sys, "frozen", False):
    _semear_dados()

if len(sys.argv) > 2 and sys.argv[1] == "--modulo":
    modulo = sys.argv[2]
    sys.argv = [modulo, *sys.argv[3:]]
    runpy.run_module(modulo, run_name="__main__", alter_sys=True)
else:
    from scripts.interface.janela import main

    main()
