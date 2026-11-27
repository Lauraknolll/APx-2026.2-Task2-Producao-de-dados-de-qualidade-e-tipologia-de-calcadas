"""Pacote de inferência de qualidade e diagnóstico de calçadas de Curitiba."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pipeline import SidewalkPipeline, inferir_calcadas

__all__ = ["SidewalkPipeline", "inferir_calcadas"]


def __getattr__(name: str):
    # O executável da coleta exclui dependências do pipeline, como pandas e matplotlib.
    if name in __all__:
        from . import pipeline

        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
