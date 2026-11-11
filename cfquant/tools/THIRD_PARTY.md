# Third-party tool: UPX

`cfquant/tools/upx/` contains the unmodified Windows x64 distribution of UPX 5.3.0.
It is invoked only to decompress temporary copies of UPX-packed QMT modules.
UPX is not installed system-wide and is not used to modify the QMT installation.

- Project and release: https://github.com/upx/upx/releases/tag/v5.3.0
- Distribution: https://github.com/upx/upx/releases/download/v5.3.0/upx-5.3.0-win64.zip
- Distribution SHA-256: `d127996c76615e431be810e9c8d2910dbe3dd400600c5c0c50276fc5a17a9705`
- Corresponding source: https://github.com/upx/upx/releases/download/v5.3.0/upx-5.3.0-src.tar.xz
- License and copyright terms: [LICENSE](upx/LICENSE) and [COPYING](upx/COPYING).

The archive digest was checked against the upstream GitHub release asset metadata
before extraction. The upstream README, documentation and other distribution
files are preserved alongside the executable. Retain these files when copying
this project to another machine.
