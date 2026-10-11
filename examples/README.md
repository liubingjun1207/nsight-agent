# Capture your own small Linux report

Use a Linux GPU machine with Nsight Systems and CUDA-enabled PyTorch already installed. The workload is `profile_workload.py`: seeded matrices, three warmups, then three NVTX `step` ranges containing CPU sleep, pinned-memory transfer, matrix multiplication and ReLU. It downloads no model or dataset.

```bash
python -c 'import torch; print(torch.__version__); print(torch.cuda.is_available())'
nsys --version
nsys profile --trace=cuda,nvtx --sample=none --cpuctxsw=none \
  --output=sample-linux python profile_workload.py
```

Copy `sample-linux.nsys-rep` to Windows and give its absolute path to `nsight_open_report`. Prefer matching collection/analysis versions. A newer capture may require upgrading the Windows Nsight installation.

Try `query={"nvtx":"step/0"}` and compare with the whole-report kernel summary. The whole report includes initialization/warmup. `cpu_wait` is an intentional CPU delay; this example does not claim to diagnose real application stalls.

For a sample requiring no collection setup, use the bundled [official NVIDIA report](reports/README.md). The synthetic CSV strings in tests are test fixtures, not measured performance.
