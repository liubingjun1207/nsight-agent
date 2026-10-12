# CSV schema fixtures

`official_2025.6.3.json` contains the header and first record produced by official Nsight Systems 2025.6.3 reports on the bundled public NVIDIA Linux capture. Source hash and license are documented in `examples/reports/README.md`.

The null Start/End schema records an observed empty output because this capture lacks those ranges. It is not a zero measurement. Synthetic/non-GPU tests use these frozen schemas; real integration independently invokes the installed official reports.
