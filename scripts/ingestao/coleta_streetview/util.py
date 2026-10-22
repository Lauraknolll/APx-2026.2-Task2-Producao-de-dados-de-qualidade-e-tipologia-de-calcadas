"""Pequenas funções usadas por várias etapas."""

import sys
import time


def com_retry(funcao, *args, max_tentativas: int = 5, **kwargs):
    """
    Chama `funcao` repetindo com espera exponencial (1, 2, 4, 8, 16 s). Se
    nunca der certo, o mais provável é o Google ter bloqueado o IP por um
    tempo — melhor parar e rodar de novo mais tarde.
    """
    for tentativa in range(max_tentativas):
        try:
            return funcao(*args, **kwargs)
        except Exception as exc:
            espera = 2 ** tentativa
            print(f"  ! {type(exc).__name__}: {str(exc)[:150]} — tentando de novo em {espera}s",
                  file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"Street View falhou {max_tentativas} vezes seguidas; "
                       "pode ser bloqueio temporário. Rode de novo mais tarde.")


def dica(args, texto: str) -> str:
    """Dica de qual comando rodar depois — omitida dentro do fluxo completo
    ('rua'), que já roda tudo em sequência."""
    return "" if getattr(args, "fluxo", False) else texto
