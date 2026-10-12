"""Annotated PyTorch eager operators. No torch.compile/fusion attribution is claimed."""

import torch


def main():
    if not torch.cuda.is_available():
        raise SystemExit("CUDA-enabled PyTorch and an NVIDIA GPU are required.")
    torch.manual_seed(42)
    matrix = torch.randn(512, 512, device="cuda", requires_grad=True)
    for _ in range(3):
        _ = matrix @ matrix
    torch.cuda.synchronize()
    with torch.autograd.profiler.emit_nvtx(record_shapes=True):
        for _ in range(3):
            with torch.cuda.nvtx.range("operator_step"):
                loss = torch.relu(matrix @ matrix).sum()
                loss.backward()
                matrix.grad = None
                torch.cuda.synchronize()
    print("Annotated eager operator workload complete")


if __name__ == "__main__":
    main()
