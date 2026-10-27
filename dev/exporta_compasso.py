"""Exporta o beat_this (final0, CPJKU) para ONNX, para o compasso.py rodar sem PyTorch: so no PC, com o python do
venv do dev (.venv_gabarito, fora do git), que tem o torch de CPU.

Os pesos vem do espelho em safetensors do Hugging Face (safe-models/beat-this-final0; o servidor da JKU estava fora,
503, em 21/10), baixados para dentro do venv como final0.safetensors e final0_config.json. As frequencias do rotary
nao vem no arquivo, mas sao fixas (nao aprendidas). Tambem grava a mel do PyTorch (torchaudio) para o compasso.py
conferir a dele.

Uso: dev/.venv_gabarito/Scripts/python dev/exporta_compasso.py <saida.onnx>"""
import inspect
import json
import sys

import numpy as np
import torch
from beat_this.model.beat_tracker import BeatThis
from beat_this.preprocessing import LogMelSpect
from safetensors.torch import load_file

VENV = sys.prefix


def carrega():
    cfg = json.load(open(f"{VENV}/final0_config.json"))
    m = BeatThis(**{k: v for k, v in cfg.items() if k in inspect.signature(BeatThis).parameters})
    faltam, sobram = m.load_state_dict(load_file(f"{VENV}/final0.safetensors"), strict=False)
    assert not sobram and all(k.endswith("rotary_embed.freqs") for k in faltam), (faltam, sobram)
    return m.eval()


class Saidas(torch.nn.Module):
    """O modelo devolve um dicionario; o ONNX quer uma tupla (logits da batida, logits do 1), por quadro de 20 ms."""

    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, spect):
        p = self.m(spect)
        return p["beat"], p["downbeat"]


if __name__ == "__main__":
    saida = sys.argv[1]
    m = Saidas(carrega())
    exemplo = torch.randn(1, 1500, 128)
    torch.onnx.export(m, (exemplo,), saida, input_names=["spect"], output_names=["batida", "um"],
                      dynamic_axes={"spect": {1: "quadros"}, "batida": {1: "quadros"}, "um": {1: "quadros"}},
                      opset_version=17, dynamo=False)
    # a mel de referencia: o filtro do torchaudio, para o compasso.py conferir o dele
    fb = LogMelSpect().spect_class.mel_scale.fb.numpy()
    np.save(saida.replace(".onnx", "_mel_torch.npy"), fb)
    print("ok:", saida)
