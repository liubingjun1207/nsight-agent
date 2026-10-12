"""Tiny real CUDA kernel using the driver API; useful without PyTorch in a Linux container.

Launches fill_int exactly 20 times and verifies its output. NVTX operator labels are
deliberately absent; use operator_workload.py for annotated PyTorch eager operations.
"""

import ctypes
import os

PTX = b"""
.version 6.0
.target sm_52
.address_size 64
.visible .entry fill_int(.param .u64 output) {
    .reg .u64 %rd<4>;
    .reg .u32 %r<4>;
    mov.u32 %r1, %tid.x;
    mov.u32 %r2, %ctaid.x;
    mad.lo.u32 %r3, %r2, 128, %r1;
    mul.wide.u32 %rd2, %r3, 4;
    ld.param.u64 %rd1, [output];
    add.s64 %rd3, %rd1, %rd2;
    st.global.u32 [%rd3], %r3;
    ret;
}
"""


def main():
    cuda = ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL("libcuda.so.1")

    def call(name, *args):
        code = getattr(cuda, name)(*args)
        if code:
            raise RuntimeError(f"{name} failed with CUDA driver error {code}")

    call("cuInit", 0)
    device, context, module, kernel = (
        ctypes.c_int(),
        ctypes.c_void_p(),
        ctypes.c_void_p(),
        ctypes.c_void_p(),
    )
    memory = ctypes.c_uint64()
    call("cuDeviceGet", ctypes.byref(device), 0)
    call("cuCtxCreate_v2", ctypes.byref(context), 0, device)
    try:
        call("cuModuleLoadData", ctypes.byref(module), ctypes.c_char_p(PTX))
        call("cuModuleGetFunction", ctypes.byref(kernel), module, b"fill_int")
        call("cuMemAlloc_v2", ctypes.byref(memory), ctypes.c_size_t(4096))
        arguments = (ctypes.c_void_p * 1)(ctypes.addressof(memory))
        for _ in range(20):
            call("cuLaunchKernel", kernel, 8, 1, 1, 128, 1, 1, 0, None, arguments, None)
        call("cuCtxSynchronize")
        output = (ctypes.c_uint32 * 1024)()
        call("cuMemcpyDtoH_v2", output, memory, ctypes.c_size_t(4096))
        if list(output) != list(range(1024)):
            raise RuntimeError("Kernel output mismatch")
        print(f"fill_int launches=20 checksum={sum(output)}")
    finally:
        if memory.value:
            call("cuMemFree_v2", memory)
        call("cuCtxDestroy_v2", context)


if __name__ == "__main__":
    main()
