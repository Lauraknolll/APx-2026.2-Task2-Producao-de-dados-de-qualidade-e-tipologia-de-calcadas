# -*- mode: python ; coding: utf-8 -*-
# O .exe da interface: a janela (link do mapa + logs das coletas), o servidor
# e a coleta com o modelo de segmentação. Da raiz do repositório:
#     .venv\Scripts\python.exe -m PyInstaller scripts\interface\exe\calcadas.spec
# Sai em dist\Calcadas\ (Calcadas.exe e a pasta _internal\, que vão juntos).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

RAIZ = Path(SPECPATH).resolve().parents[2]

# A parte nativa do torchvision (que o processador do SegFormer usa) é carregada como biblioteca, por
# caminho, e não por import: o PyInstaller não a vê. Ela vai ao lado do pacote, onde ele procura
# (torchvision/_internally_replaced_utils.py, _get_extension_path).
import torchvision
_TV = Path(torchvision.__file__).parent
NATIVOS_TORCHVISION = [(str(f), "torchvision") for f in [*_TV.glob("*.pyd"), *_TV.glob("*.dll")]]

# Pacotes cuja versão o transformers confere ao ser importado.
METADADOS = ["transformers", "torch", "torchvision", "tqdm", "regex", "requests", "packaging", "filelock", "numpy",
             "tokenizers", "huggingface-hub", "safetensors", "pyyaml", "pillow"]

a = Analysis(
    [str(RAIZ / "scripts" / "interface" / "exe" / "calcadas.py")],
    pathex=[str(RAIZ)],
    binaries=[*collect_dynamic_libs("pyexiv2"), *NATIVOS_TORCHVISION],
    datas=[
        (str(RAIZ / "scripts" / "interface" / "static"), "scripts/interface/static"),
        # O fundo e o ícone da janela (exe/arte.py)
        *[(str(f), "scripts/interface/exe") for f in (RAIZ / "scripts" / "interface" / "exe").glob("*.png")],
        (str(RAIZ / "scripts" / "interface" / "exe" / "icone.ico"), "scripts/interface/exe"),
        # Para o .exe copiado para fora do repositório (calcadas.py, _semear_dados).
        (str(RAIZ / "data" / "raw" / "_Passeio_CWB.zip"), "semente/data/raw"),
        (str(RAIZ / "data" / "raw" / "ruas_osm"), "semente/data/raw/ruas_osm"),
        *collect_data_files("pyexiv2"),
        *[m for pacote in METADADOS for m in copy_metadata(pacote)],
    ],
    hiddenimports=[
        *collect_submodules("scripts.interface"),
        *collect_submodules("scripts.ingestao.coleta_streetview"),
        "scripts.utils.device",
        "PIL.ImageTk",
        *collect_submodules("streetlevel"),
        *collect_submodules("transformers.models.segformer"),
    ],
    excludes=["scripts.utils.dinov2", "scripts.utils.sidewalk_models", "matplotlib", "notebook", "IPython",
              "jupyter", "pandas", "sklearn", "seaborn"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Calcadas",
    console=False,  # janela, sem console
    icon=str(RAIZ / "scripts" / "interface" / "exe" / "icone.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Calcadas", upx=False)
