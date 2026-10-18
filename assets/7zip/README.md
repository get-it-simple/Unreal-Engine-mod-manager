# Bundled 7-Zip

The generated Windows x64 `7z.exe` and `7z.dll` are unmodified files from the official
[7-Zip 26.04 release](https://github.com/ip7z/7zip/releases/tag/26.04).
They provide offline 7z and RAR extraction without a system installation.

Copyright Igor Pavlov. See `License.txt` for LGPL, BSD and unRAR terms.
The corresponding source code is available from the same upstream release.
`manifest.json` records the download URL and SHA-256 hashes of the package
and distributed binaries. The binaries are ignored by Git. Run
`python build-gui-exe.py --prepare-only` from the repository root to download
and extract them with Windows tar. Normal builds perform the same preparation
automatically. Verified existing files work offline; the application never
downloads dependencies at runtime.
