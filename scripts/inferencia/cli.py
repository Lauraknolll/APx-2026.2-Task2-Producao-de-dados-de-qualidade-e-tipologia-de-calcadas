"""Interface de linha de comando (CLI) para execução de inferência de calçadas."""

import argparse
import sys
from pathlib import Path

from scripts.inferencia.pipeline import SidewalkPipeline


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline unificado de inferência para classificação e diagnóstico de calçadas de Curitiba."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Caminho para uma imagem (.jpg, .png) ou um diretório de imagens.",
    )
    parser.add_argument(
        "--cenario",
        "-c",
        default="binario",
        choices=["binario", "3classes", "3classes_sem_naoid"],
        help="Cenário de taxonomia (default: binario [Transitável vs Crítica]).",
    )
    parser.add_argument(
        "--versao",
        "-v",
        default="v4",
        help="Versão dos modelos de treino (default: v4).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Caminho opcional para exportação dos resultados (.csv ou .json).",
    )
    parser.add_argument(
        "--plot",
        default=None,
        help="Caminho opcional para salvar o gráfico com as amostras preditas (.png).",
    )
    parser.add_argument(
        "--batch-size",
        "-b",
        type=int,
        default=16,
        help="Tamanho do lote para inferência na GPU (default: 16).",
    )
    parser.add_argument(
        "--sem-tags",
        action="store_true",
        help="Desativa a extração das 11 tags de defeito pelo Tagger.",
    )
    parser.add_argument(
        "--limiar-defeito",
        type=float,
        default=0.20,
        help="Probabilidade mínima para considerar um defeito relevante (default: 0.20).",
    )
    parser.add_argument(
        "--recursivo",
        "-r",
        action="store_true",
        help="Busca recursiva em subdiretórios se o input for uma pasta.",
    )

    args = parser.parse_args()

    print(f"Inicializando SidewalkPipeline (cenário='{args.cenario}', versão='{args.versao}')...")
    pipe = SidewalkPipeline(
        cenario=args.cenario,
        versao=args.versao,
        incluir_tags=not args.sem_tags,
        batch_size=args.batch_size,
    )

    print(f"Executando predição sobre '{args.input}'...")
    resultados = pipe.predict(
        args.input,
        retornar_df=False,
        salvar_em=args.output,
        limiar_defeito=args.limiar_defeito,
        recursivo=args.recursivo,
    )

    print(f"\nInferência concluída para {len(resultados)} imagem(ns)!")

    # Exibição resumida no terminal
    for r in resultados[:5]:
        defeitos_txt = ""
        if "principais_defeitos" in r and r["principais_defeitos"]:
            top = [f"{d['tag']}: {int(d['probabilidade']*100)}%" for d in r["principais_defeitos"][:2]]
            defeitos_txt = f" | Defeitos: {', '.join(top)}"
        print(f" -> {r['imagem']}: {r['classe_predita']} ({r['confianca']*100:.1f}%){defeitos_txt}")

    if len(resultados) > 5:
        print(f" ... e mais {len(resultados) - 5} imagens processadas.")

    if args.plot:
        pipe.plotar_resultados(resultados, salvar_caminho=args.plot)


if __name__ == "__main__":
    main()
