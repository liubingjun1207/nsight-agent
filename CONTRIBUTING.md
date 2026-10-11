# Contributing

Install the development extras and run the checks in README.md. Keep analysis in official Nsight reports; add tool-specific adapters only when the official report output cannot express the interface directly. Never silently change units, denominators or overlapping-event semantics.

For a new report/version adapter, include a small synthetic CSV regression test and validate against real Nsight. Do not commit private profiles. Preserve source/license/hash documentation for public fixtures. GPU-free CI cannot replace the real integration release gate.

The primary support target is Windows analysis of Linux reports. Report compatibility issues with the Nsight version, tool name, sanitized error and a shareable minimal capture if available.
