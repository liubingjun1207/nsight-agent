"""Minimal Start/End plus Push/Pop NVTX workload for optional real validation."""

import torch


def main():
    if not torch.cuda.is_available():
        raise SystemExit("CUDA-enabled PyTorch and an NVIDIA GPU are required.")
    torch.manual_seed(42)
    matrix = torch.randn(512, 512, device="cuda")
    torch.cuda.synchronize()
    for _ in range(3):
        token = torch.cuda.nvtx.range_start("AsyncStep")
        with torch.cuda.nvtx.range("step"):
            result = matrix @ matrix
            result.relu_()
            torch.cuda.synchronize()
        torch.cuda.nvtx.range_end(token)
    print("Start/End sample complete")


if __name__ == "__main__":
    main()
