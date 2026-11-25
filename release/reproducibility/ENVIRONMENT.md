# Measurement environment

All experiments ran on one cloud virtual machine, one experiment at a time unless stated in the paper.

| Item | Value |
|---|---|
| CPU | Intel(R) Xeon(R) Processor @ 2.10GHz (2 vCPUs) |
| Memory | 7.8 GiB |
| OS | Ubuntu 24.04.5 LTS |
| Kernel | 6.18.44-fc-v880 |
| strace | strace -- version 6.8 |
| git | git version 2.43.0 |
| CPython 3.9 (built from source) | Python 3.9.25 |
| CPython 3.11 (system) | Python 3.11.18 |
| Analysis Python | Python 3.13.18 |
| FUSE (remote-layer emulation) | fusermount3 3.14.0, pyfuse3 3.5.0, trio 0.35.0 |
| swebench (specifications) | Version: 4.1.0 |

Replay environments: one virtual environment per repository version; package lists in `envs.tar.gz`.

