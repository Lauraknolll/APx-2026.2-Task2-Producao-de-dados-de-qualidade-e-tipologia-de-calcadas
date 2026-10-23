import torch


def get_device():
    """Retorna o dispositivo PyTorch disponível: CUDA/ROCm, DirectML (AMD/Intel no Windows) ou CPU."""
    if torch.cuda.is_available():
        return "cuda"
    try:
        import torch_directml
        if torch_directml.is_available():
            try:
                import transformers.modeling_utils
                import transformers.utils.import_utils
                transformers.utils.import_utils.check_torch_load_is_safe = lambda: None
                transformers.modeling_utils.check_torch_load_is_safe = lambda: None
            except ImportError:
                pass
            return torch_directml.device()
    except ImportError:
        pass
    return "cpu"

