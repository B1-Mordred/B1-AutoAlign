# Third-party notices

## OpenAstroTracker-Firmware / OpenAstroExplorer

B1-AutoAlign uses the OpenAstroExplorer v1 GPIO assignments and implements the small subset of the OpenAstroTech serial protocol needed for polar-alignment control and INDI compatibility.

Upstream project: <https://github.com/OpenAstroTech/OpenAstroTracker-Firmware>

OAE v1 pin map: <https://github.com/OpenAstroTech/OpenAstroTracker-Firmware/blob/develop/boards/ESP32_ESP32DEV/pins_OAE_V1.hpp>

The upstream project is distributed under the MIT License. B1-AutoAlign is a separate PA-only implementation and retains this attribution.

## INDI OpenAstroTech driver patch

The optional patch in `integrations/indi-1.9.9` modifies portions of the INDI OpenAstroTech driver. INDI is licensed under the GNU Lesser General Public License; consult the upstream project for the applicable source and license text:

<https://github.com/indilib/indi>
