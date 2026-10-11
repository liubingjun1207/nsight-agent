"""Small, self-contained CUDA workload for a redistributable Nsight capture.

Requires a CUDA-enabled PyTorch installation. No datasets or model downloads.
"""

import time

import torch


def main():
    if not torch.cuda.is_available():
        raise SystemExit("A CUDA-enabled PyTorch installation and NVIDIA GPU are required.")
    torch.manual_seed(42)
    host = torch.randn(1024, 1024, pin_memory=True)
    matrix = torch.randn(1024, 1024, device="cuda")
    for _ in range(3):
        _ = matrix @ matrix
    torch.cuda.synchronize()
    for _ in range(3):
        with torch.cuda.nvtx.range("step"):
            with torch.cuda.nvtx.range("cpu_wait"):
                time.sleep(0.01)
            with torch.cuda.nvtx.range("copy"):
                value = host.to("cuda", non_blocking=True)
            with torch.cuda.nvtx.range("compute"):
                for _ in range(5):
                    value = torch.relu(value @ matrix)
            torch.cuda.synchronize()
    print("Nsight sample workload complete")


if __name__ == "__main__":
    main()
