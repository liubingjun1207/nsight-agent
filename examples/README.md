# Capture your own small Linux report

Use a Linux GPU machine with Nsight Systems and CUDA-enabled PyTorch already installed. The workload is `profile_workload.py`: seeded matrices, three warmups, then three NVTX `step` ranges containing CPU sleep, pinned-memory transfer, matrix multiplication and ReLU. It downloads no model or dataset.

```bash
python -c 'import torch; print(torch.__version__); print(torch.cuda.is_available())'
nsys --version
nsys profile --trace=cuda,nvtx --sample=none --cpuctxsw=none \
  --output=sample-linux python profile_workload.py
```

Give the report's absolute path to `nsight_open_report` on the same Linux MCP host, or copy it to Windows for analysis. Prefer matching collection/analysis versions. A newer capture may require upgrading the reader. v1.1 can also collect an owner-registered local task; see [the extension guide](../docs/EXTENSIONS.md).

Try `query={"nvtx":"step/0"}` and compare with the whole-report kernel summary. The whole report includes initialization/warmup. `cpu_wait` is an intentional CPU delay; this example does not claim to diagnose real application stalls.

For a sample requiring no collection setup, use the bundled [official NVIDIA report](reports/README.md). The synthetic CSV strings in tests are test fixtures, not measured performance.

## Capture a baseline/candidate pair

`compare_workload.py` uses identical seeded inputs, five steps, and five matrix/ReLU operations per step. Baseline synchronizes every operation and allocates a ReLU result; candidate uses in-place ReLU and synchronizes at each step end. Both print a checksum for a numerical sanity check. Speedup is not guaranteed.

```bash
nsys profile --trace=cuda,nvtx --sample=none --cpuctxsw=none \
  --output=baseline-linux python compare_workload.py --variant baseline
nsys profile --trace=cuda,nvtx --sample=none --cpuctxsw=none \
  --output=candidate-linux python compare_workload.py --variant candidate
```

Keep the machine, inputs, software versions and power settings consistent. Check both checksums, compare `Train` or corresponding `step` windows, and inspect count changes. These instructions require your Linux GPU environment. The bundled NVIDIA pair is available when you cannot collect locally.

## Optional Start/End validation

`startend_workload.py` records three same-thread `AsyncStep` Start/End ranges plus nested Push/Pop ranges, with seeded CUDA matrices and no external dataset. Capture it with:

```bash
nsys profile --trace=cuda,nvtx --sample=none --cpuctxsw=none \
  --output=startend-validation python startend_workload.py
```

For the optional test, set `NSIGHT_STARTEND_REPORT` to the captured report's absolute path alongside `NSIGHT_INTEGRATION=1`. The test expects three `AsyncStep` instances. Our local positive validation was collected on Windows; it is not presented as a Linux capture. The public NVIDIA Linux baseline exercises the missing-data path for Start/End instead.

## v1.1 eager operators and a dependency-light CUDA example

`operator_workload.py` records `aten::` eager operation labels with `emit_nvtx(record_shapes=True)` over three matrix/ReLU/reduction/backward steps. Capture it using the same CUDA/NVTX flags or register it as a local capture target. Query `nsight_operator_summary`; nested labels can associate a kernel repeatedly and do not establish unique operator totals. No compiled/fused graph attribution is claimed.

`driver_workload.py` needs only Python, an NVIDIA GPU and the CUDA driver. It launches a small `fill_int` PTX kernel exactly 20 times and verifies checksum 523776. It has no NVTX operator labels and cannot validate framework attribution. It is useful for Linux containers without a PyTorch installation.
