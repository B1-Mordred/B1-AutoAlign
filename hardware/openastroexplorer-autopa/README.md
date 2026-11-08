# OpenAstroExplorer AutoPA printable parts

This directory contains the complete AutoPA/ALTAZ printable-parts subset from
the official OpenAstroExplorer model repository. The ten STL files are
unmodified, byte-for-byte copies of `STL/ALTAZ` at upstream commit
[`a5373d654d3d14ce146800848f2b174f9c0f6e27`](https://github.com/OpenAstroTech/OpenAstroExplorer/tree/a5373d654d3d14ce146800848f2b174f9c0f6e27/STL/ALTAZ),
retrieved on 2026-11-08.

No RA/DEC, tracking, focuser, tripod, counterweight, or unrelated enclosure
models are included.

## Print set

| File | Quantity | Upstream print note |
|---|---:|---|
| `51111_adapter_left.STL` | 1 | — |
| `51111_adapter_right.STL` | 1 | Supports required |
| `ALT_Knob.STL` | 2 | — |
| `ALT_slider.STL` | 1 | — |
| `AZ_connector.STL` | 1 | — |
| `AZ_coupler.STL` | 1 | Use extra perimeters for strength |
| `AZ_slider.STL` | 1 | — |
| `ESP_lid.STL` | 1 | — |
| `MGN9C_adapter.STL` | 1 | — |
| `driver_lid.STL` | 1 | — |

The quantities and notes above come from the
[official printed-parts list](https://docs.google.com/spreadsheets/d/12bo7vfit7GZXNui0Y1q4IBbTn9S2-HQub6Z6bK9Nim4/edit?usp=sharing).
The corresponding installation steps are in the OpenAstroExplorer
[azimuth assembly](https://wiki.openastrotech.com/en/OpenAstroExplorer/Assembly_part4)
and [altitude assembly](https://wiki.openastrotech.com/en/OpenAstroExplorer/Assembly_part5)
guides.

## Integrity

From this directory, verify the imported files with:

```bash
sha256sum --check SHA256SUMS
```

Repository tests also verify the exact filename set, checksums, and binary STL
record structure.

## License and mechanical scope

These model files are licensed separately from the B1-AutoAlign firmware under
the [Creative Commons Attribution-NonCommercial 4.0 International License](LICENSE.md).
They are not covered by the repository's root MIT license. Preserve attribution
and observe the non-commercial restriction when redistributing or adapting them.

The models reproduce the OpenAstroExplorer AutoPA hardware. Their presence in
this repository does not establish a 25 kg load rating for a printed assembly.
Material, print orientation, fasteners, bearings, motor torque, balance, safety
factors, and physical load testing still need to be engineered for the actual
telescope system.
