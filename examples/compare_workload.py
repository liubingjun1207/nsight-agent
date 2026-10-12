"""Equal seeded work with two synchronization/allocation strategies; no speedup guarantee."""

import argparse

import torch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("baseline", "candidate"), required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("CUDA-enabled PyTorch and an NVIDIA GPU are required.")
    torch.manual_seed(42)
    host = torch.randn(1024, 1024, pin_memory=True)
    matrix = torch.randn(1024, 1024, device="cuda") / 32
    for _ in range(3):
        _ = matrix @ matrix
    torch.cuda.synchronize()
    with torch.cuda.nvtx.range("Train"):
        for _ in range(5):
            with torch.cuda.nvtx.range("step"):
                value = host.to("cuda", non_blocking=True)
                for _ in range(5):
                    value = value @ matrix
                    if args.variant == "baseline":
                        value = torch.relu(value)
                        torch.cuda.synchronize()
                    else:
                        value.relu_()
                torch.cuda.synchronize()
    print(f"{args.variant}: checksum={value.sum().item():.6f}")


if __name__ == "__main__":
    main()
